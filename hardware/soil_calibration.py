"""ADC 土壤湿度传感器的自动校准算法。

浇水后，水分在土壤中缓慢渗透、分布，最终达到田间持水量。本模块通过
EMA 平滑 + 滑动窗口极差检测，等待读数趋于平稳后，将平稳值记录为
新的 100% 湿度基准（VAL_WATER）。

纯算法模块，不依赖项目的 core 层（state / config / database / logic），
仅使用标准库。可被任何 ADC 土壤传感器驱动复用，也可被其他项目直接拿走。

算法核心--延迟盲区 + 极差稳态检测
====================================

物理现实：传感器与水管存在物理距离，大颗粒赤玉土的水分依靠极缓慢的
横向毛细作用渗透。浇水后读数表现为一条长达数十分钟的缓慢下行渐近线，
**不会出现** "瞬间积水 -> 排空回升" 的理想波形。若土壤已饱和，甚至连
下降都不会出现。

因此算法不做任何方向性假设（不看反转、不看斜率），只做两件事：

1. **强制物理盲区 (settle_delay)**：浇水后前 N 分钟只采集数据更新 EMA，
   不做稳定判定。让水在土壤中完成横向移动和重力分布。

2. **大窗口极差检测**：盲区结束后，观察一个 10 分钟滑动窗口内 EMA 值的
   极差（max - min）。极差低于 ``stable_threshold`` 说明数据已彻底平稳，
   水分分布结束。

**毛刺过滤**：实际硬件（ADS1115 + I2C）偶尔会产生数量级异常的读数
（如实测中出现 22612 而正常值约 5744）。单个毛刺会让窗口极差暴涨至
数千，永远无法低于阈值。因此在入队前过滤：偏离当前 EMA 超过
``GLITCH_THRESHOLD`` 的读数直接跳过。

实测数据参考（树莓派 + ADS1115 + 赤玉土）：
- 正常读数 raw ≈ 5700-6000，噪声 stdev ≈ 4-10 ADC；
- EMA 平滑后 60 样本窗口的极差约 5-10 ADC；
- ``stable_threshold=18`` 留有充足余量（~2x 噪声极差）；
- ``settle_delay=600``（10 分钟）覆盖典型渗透时间；
- ``timeout_min=120``（2 小时）覆盖极慢渗透场景，超时不更新基准。
"""

import collections
import json
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)

# ---- 默认参数（可被驱动传入的 config 覆盖）----
DEFAULT_ALPHA = 0.2               # EMA 平滑系数
DEFAULT_WINDOW_SIZE = 60           # 滑动窗口长度（60 × 10s = 10 分钟）
DEFAULT_STABLE_THRESHOLD = 18      # 窗口极差阈值（max - min < 此值则稳定）
DEFAULT_STABLE_CONFIRM = 2         # 连续命中阈值的次数
DEFAULT_TIMEOUT_MIN = 120          # 校准超时（分钟）
DEFAULT_SETTLE_DELAY_SEC = 600     # 浇水后物理盲区（10 分钟）
DEFAULT_SAMPLE_INTERVAL_SEC = 10   # 校准采样间隔（秒）
SAMPLE_INTERVAL_SEC = 10           # 校准采样间隔（模块级常量，向后兼容）
MAX_READ_FAILURES = 5              # 连续读取失败上限
GLITCH_THRESHOLD = 500             # 毛刺过滤：偏离 EMA 超过此值则跳过


class SoilCalibrator:
    """封装 EMA、滑动窗口与极差稳定判定的纯算法状态机。

    不含 I/O 与线程逻辑--调用方喂数值进来，它告诉你什么时候稳定。
    可直接用于单元测试。
    """

    def __init__(self, config=None):
        cfg = config or {}
        self.alpha = cfg.get("alpha", DEFAULT_ALPHA)
        self.window_size = cfg.get("window_size", DEFAULT_WINDOW_SIZE)
        self.stable_threshold = cfg.get("stable_threshold", DEFAULT_STABLE_THRESHOLD)
        self.confirm = cfg.get("stable_confirm", DEFAULT_STABLE_CONFIRM)
        self.timeout_sec = cfg.get("timeout_min", DEFAULT_TIMEOUT_MIN) * 60
        self.settle_delay = cfg.get("settle_delay_sec", DEFAULT_SETTLE_DELAY_SEC)
        self.sample_interval = cfg.get("sample_interval_sec", DEFAULT_SAMPLE_INTERVAL_SEC)
        self._reset()

    def _reset(self):
        """重置 EMA、窗口与计数器（每次进入校准前调用）。"""
        self.ema = None              # S_{t-1}，首个样本直接赋值（避免用 0 初始化的冷启动偏置）
        self.window = collections.deque(maxlen=self.window_size)
        self.stable_count = 0
        self.samples_seen = 0        # 已处理的样本数（含盲区期）
        # 盲区样本数：settle_delay 期间采集但不判定。
        # 向上取整避免因整除丢失最后一个间隔。
        self.settle_samples = int(self.settle_delay / self.sample_interval + 0.5)

    # ---- 算法核心（纯逻辑，无副作用）----

    def update_ema(self, raw_value):
        """EMA 一步更新：S_t = α·Y_t + (1-α)·S_{t-1}。

        首个样本直接赋值而非从 0 起步--后者会让前 5 个样本
        系统性偏低，白白浪费滑动窗口的前几个位置。
        """
        if self.ema is None:
            self.ema = raw_value
        else:
            self.ema = self.alpha * raw_value + (1 - self.alpha) * self.ema
        return self.ema

    def push_and_check(self, ema_value):
        """将平滑值入队，返回 (window_full, window_range, is_stable)。

        窗口未满或仍在盲区时不做稳定判断。

        盲区结束后，计算窗口内 EMA 值的极差（max - min）。
        极差低于 ``stable_threshold`` 说明 10 分钟内数据波动极小，
        水分分布已结束。连续 ``confirm`` 次命中则判定稳定。
        """
        self.window.append(ema_value)
        self.samples_seen += 1

        # 盲区期：只采集，不判定
        if self.samples_seen <= self.settle_samples:
            return len(self.window) >= self.window.maxlen, None, False

        # 窗口未满：无法计算有意义的极差
        if len(self.window) < self.window.maxlen:
            return False, None, False

        window_range = max(self.window) - min(self.window)

        if window_range < self.stable_threshold:
            self.stable_count += 1
        else:
            self.stable_count = 0

        return True, window_range, self.stable_count >= self.confirm


def run_calibration(read_func, config=None, restart_event=None):
    """执行一轮完整校准。

    Args:
        read_func: 无参回调，返回 compensated_raw (float) 或 None（读取失败）。
                   由驱动提供，通常是 driver._read_compensated_raw。
        config: 校准参数字典，缺省用模块默认值。
        restart_event: threading.Event；校准期间被 set 则立即返回 None。
                       调用方据此区分"重启"（再次浇水）与"超时/失败"。

    Returns:
        float - 新的 VAL_WATER（校准成功）
        None  - 超时、传感器故障、或收到重启信号
    """
    cal = SoilCalibrator(config)
    start_time = time.time()

    consecutive_failures = 0
    while True:
        # ---- 退出条件检查 ----
        if restart_event and restart_event.is_set():
            return None          # 调用方检查 event 区分"重启"与"超时"

        if time.time() - start_time > cal.timeout_sec:
            logger.warning("⏱️ 校准超时（%d 分钟），未更新基准",
                           int(cal.timeout_sec // 60))
            return None

        # ---- 读取传感器 ----
        raw = read_func()
        if raw is None:
            consecutive_failures += 1
            if consecutive_failures >= MAX_READ_FAILURES:
                logger.error("❌ 连续 %d 次读取失败，中止校准",
                             consecutive_failures)
                return None
            time.sleep(cal.sample_interval)
            continue
        consecutive_failures = 0

        # ---- 毛刺过滤 ----
        # ADS1115 + I2C 偶尔产生数量级异常的读数（实测 22612 vs 正常 5744）。
        # 单个毛刺会让窗口极差暴涨，永远无法低于阈值。
        # 500 ADC 远超真实变化率（~50-100/10s），远低于毛刺幅度（~16000+）。
        if cal.ema is not None and abs(raw - cal.ema) > GLITCH_THRESHOLD:
            logger.warning("⚠️ 校准采样异常值跳过: raw=%.1f ema=%.1f (偏差=%.1f)",
                           raw, cal.ema, abs(raw - cal.ema))
            time.sleep(cal.sample_interval)
            continue

        # ---- EMA -> 窗口 -> 稳定判定 ----
        smoothed = cal.update_ema(raw)
        window_full, window_range, is_stable = cal.push_and_check(smoothed)

        if window_full:
            in_settle = cal.samples_seen <= cal.settle_samples
            logger.debug("校准采样: raw=%.1f ema=%.1f range=%s count=%d %s",
                         raw, smoothed,
                         f"{window_range:.1f}" if window_range is not None else "-",
                         cal.stable_count,
                         "盲区" if in_settle else "观测")

        if is_stable:
            new_val = round(smoothed, 1)
            logger.info("✅ 土壤校准稳定检测命中，新 VAL_WATER=%.1f", new_val)
            return new_val

        time.sleep(cal.sample_interval)


# ---- 持久化读写 ----

def _calibration_file(data_dir):
    return os.path.join(data_dir, "calibration.json")


def load_calibration(data_dir, node_id, sensor_id):
    """读取持久化的校准基准。返回 val_water (float) 或 None。

    文件不存在或损坏时静默返回 None--驱动退回 hardware_config 里的原始值。
    """
    try:
        with open(_calibration_file(data_dir), "r") as f:
            data = json.load(f)
        entry = data.get(f"{node_id}:{sensor_id}")
        if entry:
            return entry.get("val_water")
    except (OSError, ValueError, KeyError):
        pass
    return None


def save_calibration(data_dir, node_id, sensor_id, val_water):
    """持久化校准基准。

    原子读改写：先读已有内容（多节点多传感器共存），更新当前条目，再写回。
    文件不存在时从空字典开始。写入失败只记日志--内存中的 VAL_WATER
    已经更新，只是重启后会丢失。

    写入采用 temp-file + ``os.replace`` 原子模式：先写到同目录下的临时文件，
    ``fsync`` 落盘后原子替换目标文件。即使写入过程中进程崩溃，
    calibration.json 要么是完整的旧内容、要么是完整的新内容，
    不会出现截断/半写的损坏状态--``load_calibration`` 遇到损坏会静默退回
    配置默认值，但有了原子写就不会走到那一步。
    """
    path = _calibration_file(data_dir)
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}

    data[f"{node_id}:{sensor_id}"] = {
        "val_water": val_water,
        "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 临时文件必须与目标在同一目录（同一文件系统），os.replace 才是原子的；
    # 跨文件系统时会退化为复制+删除，中间崩溃可能留下半写文件。
    # mkstemp 保证文件名唯一，避免多线程/多进程并发写时互相覆盖。
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=data_dir, suffix=".tmp", prefix=".calibration-")
    except OSError as e:
        logger.error("校准临时文件创建失败: %s", e)
        return

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError as e:
        logger.error("校准文件写入失败: %s", e)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
