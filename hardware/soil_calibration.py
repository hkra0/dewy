"""ADC 土壤湿度传感器的自动校准算法。

浇水后土壤经历"积水尖峰 → 重力排水 → 田间持水量稳定"三个阶段。
本模块通过 EMA 平滑 + 滑动窗口首尾差值检测排水曲线的拐点，
将稳定期的平滑 ADC 值记录为新的 100% 湿度基准（VAL_WATER）。

纯算法模块，不依赖项目的 core 层（state / config / database / logic），
仅使用标准库。可被任何 ADC 土壤传感器驱动复用，也可被其他项目直接拿走。

参数选择依据（基于树莓派 + ADS1115 + 赤玉土的实际历史数据分析）：
- stable_threshold=20: 稳定期 3 分钟窗口 |Δ| 为 0–3 ADC，后期排水为 16+，
  20 处于间隙正中。3 次连续确认能过滤排水末期的单次反弹。
- timeout_min=90: 实测从浇水到稳定约 100 分钟（尖峰 8 分钟 + 排水再分布
  约 90 分钟）。赤玉土大颗粒积水排空快，但毛管水再分布缓慢。
"""

import collections
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# ---- 默认参数（可被驱动传入的 config 覆盖）----
DEFAULT_ALPHA = 0.2              # EMA 平滑系数
DEFAULT_WINDOW_SIZE = 18          # 滑动窗口长度（18 × 10s = 3 分钟）
DEFAULT_STABLE_THRESHOLD = 20.0   # |Δ| < 此值视为稳定（ADC 单位）
DEFAULT_STABLE_CONFIRM = 3        # 连续命中阈值的次数
DEFAULT_TIMEOUT_MIN = 90          # 校准超时（分钟）
DEFAULT_SETTLE_DELAY_SEC = 30     # 浇水后等水渗到传感器的延迟
DEFAULT_SAMPLE_INTERVAL_SEC = 10    # 校准采样间隔（秒）
SAMPLE_INTERVAL_SEC = 10          # 校准采样间隔（模块级常量，向后兼容）
MAX_READ_FAILURES = 5             # 连续读取失败上限


class SoilCalibrator:
    """封装 EMA、滑动窗口与稳定判定的纯算法状态机。

    不含 I/O 与线程逻辑——调用方喂数值进来，它告诉你什么时候稳定。
    可直接用于单元测试。
    """

    def __init__(self, config=None):
        cfg = config or {}
        self.alpha = cfg.get("alpha", DEFAULT_ALPHA)
        self.window_size = cfg.get("window_size", DEFAULT_WINDOW_SIZE)
        self.threshold = cfg.get("stable_threshold", DEFAULT_STABLE_THRESHOLD)
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
        窗口满后计算首尾差值 Δ = S_newest - S_oldest，
        |Δ| < threshold 计入 stable_count，连续命中 confirm 次则判定稳定。
        任何一次未命中都清零——排水末期的单次反弹不应触发误判。
        """
        self.window.append(ema_value)
        if len(self.window) < self.window.maxlen:
            return False, None, False

        delta = self.window[-1] - self.window[0]
        if abs(delta) < self.threshold:
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

    # 等待水渗到传感器，避免首个样本落在积水尖峰的上升沿
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

        # ---- EMA → 窗口 → 稳定判定 ----
        smoothed = cal.update_ema(raw)
        window_full, delta, is_stable = cal.push_and_check(smoothed)

        if window_full:
            logger.debug("校准采样: raw=%.1f ema=%.1f delta=%s count=%d",
                         raw, smoothed,
                         f"{delta:.1f}" if delta is not None else "-",
                         cal.stable_count)

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
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error("校准文件写入失败: %s", e)
