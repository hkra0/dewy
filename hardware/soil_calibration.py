"""ADC 土壤湿度传感器的自动校准算法。

浇水后土壤经历"积水尖峰 → 重力排水 → 田间持水量稳定"三个阶段。
本模块通过 EMA 平滑 + 滑动窗口首尾差值检测排水曲线的拐点，
将稳定期的平滑 ADC 值记录为新的 100% 湿度基准（VAL_WATER）。

纯算法模块，不依赖项目的 core 层（state / config / database / logic），
仅使用标准库。可被任何 ADC 土壤传感器驱动复用，也可被其他项目直接拿走。

算法核心——自适应阈值 + 反转检测
================================

旧版使用写死的绝对阈值 ``stable_threshold=20`` 判断稳定，存在两个缺陷：
1. 不同传感器量程、分辨率各异，写死 ADC 绝对值无法通用；
2. 积水尖峰的平台期 |Δ| 也接近 0，算法会误判为"已稳定"，把尖峰值当作基准。

新版用两个机制解决：

**自适应阈值** — 跟踪本轮校准的峰值 |Δ|（``max_delta``），稳定判定阈值
= ``max(max_delta × stable_ratio, |ema| × noise_ratio)``。
- ``stable_ratio=0.1``：排水期 |Δ| 可达数百 ADC，稳定期趋近 0；10% 的峰值
  能可靠区分两者，同时对小幅变化也保持敏感。
- ``noise_ratio=0.001``：信号量级的 0.1% 作为噪声地板，低于此值的 Δ 视为
  随机噪声。对 ~6000 ADC 的信号，噪声地板 ≈ 6，足以过滤量化噪声。
全部参数均为无量纲比例，不依赖任何绝对 ADC 值。

**反转检测（has_drained）** — 积水尖峰与重力排水始终方向相反。当滑动窗口
首尾差值 Δ 的符号发生反转时，判定排水已开始。只有 ``has_drained=True``
后才接受稳定判定——积水平台期 |Δ| 虽小但排水尚未开始，不会被误判为稳定。

**无需 settle_delay** — 反转检测天然过滤积水尖峰，采样从浇水瞬间即开始。
首个窗口捕获"浇水前 → 积水尖峰"的跳变，为反转检测提供初始方向。
``settle_delay`` 默认为 0，保留参数供特殊场景使用。

实测数据参考（树莓派 + ADS1115 + 赤玉土）：
- 浇水前 raw ≈ 5950，积水尖峰 raw ≈ 5890（下降 ~60 ADC）；
- 尖峰持续约 8 分钟，排水再分布约 90 分钟后趋于稳定；
- ``timeout_min=90`` 覆盖典型排水周期，超时不更新基准（安全退出）。
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
DEFAULT_WINDOW_SIZE = 18           # 滑动窗口长度（18 × 10s = 3 分钟）
DEFAULT_STABLE_RATIO = 0.1         # 稳定判定：|Δ| < 峰值 |Δ| × 此比例
DEFAULT_NOISE_RATIO = 0.001        # 噪声地板：|ema| × 此比例
DEFAULT_STABLE_CONFIRM = 3         # 连续命中阈值的次数
DEFAULT_TIMEOUT_MIN = 90           # 校准超时（分钟）
DEFAULT_SETTLE_DELAY_SEC = 0       # 浇水后等待延迟（反转检测已处理尖峰）
DEFAULT_SAMPLE_INTERVAL_SEC = 10   # 校准采样间隔（秒）
SAMPLE_INTERVAL_SEC = 10           # 校准采样间隔（模块级常量，向后兼容）
MAX_READ_FAILURES = 5              # 连续读取失败上限


class SoilCalibrator:
    """封装 EMA、滑动窗口与稳定判定的纯算法状态机。

    不含 I/O 与线程逻辑——调用方喂数值进来，它告诉你什么时候稳定。
    可直接用于单元测试。
    """

    def __init__(self, config=None):
        cfg = config or {}
        self.alpha = cfg.get("alpha", DEFAULT_ALPHA)
        self.window_size = cfg.get("window_size", DEFAULT_WINDOW_SIZE)
        self.stable_ratio = cfg.get("stable_ratio", DEFAULT_STABLE_RATIO)
        self.noise_ratio = cfg.get("noise_ratio", DEFAULT_NOISE_RATIO)
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
        self.max_delta = 0.0         # 本轮峰值 |Δ|（自适应阈值的基准）
        self.drift_sign = 0          # 上一次显著 Δ 的方向（+1 / -1 / 0=未确定）
        self.has_drained = False     # 是否检测到排水（Δ 符号反转）

    # ---- 算法核心（纯逻辑，无副作用）----

    def update_ema(self, raw_value):
        """EMA 一步更新：S_t = α·Y_t + (1-α)·S_{t-1}。

        首个样本直接赋值而非从 0 起步——后者会让前 5 个样本
        系统性偏低，白白浪费滑动窗口的前几个位置。
        """
        if self.ema is None:
            self.ema = raw_value
        else:
            self.ema = self.alpha * raw_value + (1 - self.alpha) * self.ema
        return self.ema

    def push_and_check(self, ema_value):
        """将平滑值入队，返回 (window_full, delta, is_stable)。

        窗口未满时不做稳定判断——18 个样本才覆盖 3 分钟，
        之前的首尾差值没有物理意义。

        窗口满后依次执行：

        1. **计算 Δ** = S_newest − S_oldest
        2. **跟踪峰值** max_delta = max(max_delta, |Δ|)
        3. **反转检测**：仅当 |Δ| 超过噪声地板时更新 drift_sign。
           若新方向与上一次显著方向相反 → has_drained = True。
           积水平台期 |Δ| ≈ 0（不更新方向），不会触发误判。
        4. **自适应阈值** = max(max_delta × stable_ratio, |ema| × noise_ratio)
        5. **稳定判定**：has_drained 且 |Δ| < 阈值 → stable_count++；
           否则清零。连续 confirm 次则判定稳定。
        """
        self.window.append(ema_value)
        if len(self.window) < self.window.maxlen:
            return False, None, False

        delta = self.window[-1] - self.window[0]
        abs_delta = abs(delta)

        # 噪声地板：信号量级的固定比例，过滤量化噪声与微小抖动
        noise_floor = abs(self.ema) * self.noise_ratio

        # 跟踪本轮峰值 |Δ|（自适应阈值的基准）
        if abs_delta > self.max_delta:
            self.max_delta = abs_delta

        # 反转检测：只有显著 Δ（超过噪声地板）才参与方向判断。
        # 积水尖峰与排水方向相反，符号反转 = 排水已开始。
        # 平台期 Δ ≈ 0（低于噪声地板），不更新 drift_sign，
        # 因此平台期不会产生反转、不会设置 has_drained。
        if abs_delta > noise_floor:
            current_sign = 1 if delta > 0 else -1
            if self.drift_sign != 0 and current_sign != self.drift_sign:
                self.has_drained = True
            self.drift_sign = current_sign

        # 自适应阈值：峰值的固定比例，至少不低于噪声地板
        threshold = max(self.max_delta * self.stable_ratio, noise_floor)

        # 稳定判定：必须在排水确认后才接受
        if self.has_drained and abs_delta < threshold:
            self.stable_count += 1
        else:
            self.stable_count = 0

        return True, delta, self.stable_count >= self.confirm


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

    # settle_delay 默认为 0：反转检测已处理积水尖峰，无需人为跳过。
    # 保留参数供特殊场景（如传感器响应极慢、需等水到达）使用。
    if cal.settle_delay > 0:
        time.sleep(cal.settle_delay)

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

        # ---- EMA -> 窗口 -> 稳定判定 ----
        smoothed = cal.update_ema(raw)
        window_full, delta, is_stable = cal.push_and_check(smoothed)

        if window_full:
            logger.debug("校准采样: raw=%.1f ema=%.1f delta=%s count=%d drained=%s",
                         raw, smoothed,
                         f"{delta:.1f}" if delta is not None else "-",
                         cal.stable_count, cal.has_drained)

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

    文件不存在或损坏时静默返回 None——驱动退回 hardware_config 里的原始值。
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
    文件不存在时从空字典开始。写入失败只记日志——内存中的 VAL_WATER
    已经更新，只是重启后会丢失。

    写入采用 temp-file + ``os.replace`` 原子模式：先写到同目录下的临时文件，
    ``fsync`` 落盘后原子替换目标文件。即使写入过程中进程崩溃，
    calibration.json 要么是完整的旧内容、要么是完整的新内容，
    不会出现截断/半写的损坏状态——``load_calibration`` 遇到损坏会静默退回
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
