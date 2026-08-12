"""ADC 土壤湿度传感器的自动基准校准算法（ABC, Automatic Baseline Calibration）。

纯算法模块，不依赖项目的 core 层（state / config / database / logic），
仅使用标准库。可被任何 ADC 土壤传感器驱动复用，也可被其他项目直接拿走。

算法核心--离线滑动窗口统计 + 防错门控
====================================

物理现实：传感器与水管存在物理距离，大颗粒赤玉土的水分依靠极缓慢的
横向毛细作用渗透，浇水后读数是一条长达数十分钟到数小时的缓慢下行渐近线。
实时监测"何时到达田间持水量"没有可靠判据——任意窗口内数据平稳，
既可能是渗透已完成，也可能只是渗透速度暂时很慢；耐旱植物长期不浇水时
更是完全没有事件可以触发实时监测。

因此本模块不再追踪单次浇水事件，而是每天离线扫描过去 N 天的历史读数，
统计意义上找出"最湿的那些时刻"作为 100% 湿度基准：

1. **日内 P5**：按天分组，每天取当日读数的第 5 百分位数。
   ADC 值越低代表越湿，取最小值会被瞬时局部积水污染，
   取第 5 百分位数可以切掉这类短暂的物理伪影。

2. **跨日 P10**：把每天的日内 P5 值再取一次第 10 百分位数（即取
   "最湿的那几天"的代表值，而非只取单一最湿的那一天——避免单日异常
   把估计值锚死在一个孤立的伪影上）。这一步是关键：如果直接对全部
   原始样本取一次全局百分位，估计量会随浇水频率系统性漂移——
   浇水越少，"最湿的 5% 样本"这个固定预算就越可能被并非真正饱和的、
   稍干一些的时刻填满。按天而非按样本取百分位，把预算从"时长"换成
   "天数"，同一水平的分位数在窗口内命中的始终是浇水后最接近田间持水量
   的那几天，不因窗口期内总共浇了几次水而系统性偏移，同样适用于长期
   不浇水的耐旱植物场景。（实测：分位数越高，越依赖窗口内"足够多的
   湿润天数"才能保持无偏——过高会在浇水稀疏时引入可观漂移，故取偏低
   的 P10 而非更高的分位数。）

3. **防错门控**：
   - 单次漂移率 = |候选值 - 旧基准| / 旧基准，超过 ``max_drift_ratio``
     判定为异常漂移（长时间未浇透导致窗口期数据整体偏干等），拒绝更新。
   - 候选值必须落在出厂值 ±30% 范围内——门控 1 只挡单次跳变，
     不挡多次同方向的小步漂移累积成的长期偏移，这里再加一道绝对夹紧。
   - 候选值必须低于 VAL_AIR 的 80%，防止 VAL_WATER 逼近甚至超过 VAL_AIR
     导致 ``(VAL_AIR - raw) / (VAL_AIR - VAL_WATER)`` 分母趋零甚至变号。

4. **EMA 平滑更新**：通过门控后，新基准 = 0.8 × 旧基准 + 0.2 × 候选值，
   防止单日统计的偶然偏差造成基准剧烈跳变。
"""

import json
import logging
import math
import os
import tempfile
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---- 默认参数（可被驱动传入的 config 覆盖）----
DEFAULT_WINDOW_DAYS = 30            # 统计窗口（天）
DEFAULT_MAX_DRIFT_RATIO = 0.15      # 单次基准最大允许偏移率
DEFAULT_INTRA_DAY_PCT = 0.05        # 日内百分位（P5）
DEFAULT_CROSS_DAY_PCT = 0.10        # 跨日百分位（P10）
DEFAULT_EMA_ALPHA = 0.2             # EMA 权重：新值 = alpha*候选 + (1-alpha)*旧值
MIN_VALID_DAYS = 7                  # 参与统计的最少天数
MIN_TOTAL_SAMPLES = 500             # 参与统计的最少样本总数
ABSOLUTE_BOUND_RATIO = 0.3          # 候选值相对出厂值的最大允许偏移率
VAL_AIR_MARGIN_RATIO = 0.2          # 候选值必须低于 VAL_AIR 的 (1 - 此值)


def percentile(sorted_values, q):
    """线性插值百分位数（与 numpy 默认 method='linear' 一致）。

    ``sorted_values`` 必须已升序排列且非空。
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = q * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def field_capacity_estimate(day_values, intra_day_pct=DEFAULT_INTRA_DAY_PCT,
                             cross_day_pct=DEFAULT_CROSS_DAY_PCT,
                             min_valid_days=MIN_VALID_DAYS,
                             min_total_samples=MIN_TOTAL_SAMPLES):
    """两级百分位数统计，估计田间持水量对应的 ADC 值。

    Args:
        day_values: [(本地日期字符串, ADC 原始值), ...]，来自
            ``core.database.query_soil_adc_series``。
        intra_day_pct: 日内百分位（默认 P5，切掉瞬时积水伪影）。
        cross_day_pct: 跨日百分位（默认 P10，只看最湿的那几天，
            按天而非按样本数分配预算，减轻浇水频率对估计量的影响）。
        min_valid_days / min_total_samples: 样本量下限，不足时拒绝估计
            （新装机、长期掉线、窗口期数据不足等场景）。

    Returns:
        (estimate, valid_days, total_samples)
        estimate 在样本不足时为 None。
    """
    by_day = defaultdict(list)
    for day, value in day_values:
        if value is not None:
            by_day[day].append(value)

    valid_days = len(by_day)
    total_samples = sum(len(v) for v in by_day.values())

    if valid_days < min_valid_days or total_samples < min_total_samples:
        return None, valid_days, total_samples

    daily_wettest = sorted(
        percentile(sorted(values), intra_day_pct)
        for values in by_day.values()
    )
    estimate = percentile(daily_wettest, cross_day_pct)
    return estimate, valid_days, total_samples


def evaluate_update(old_val_water, factory_val_water, val_air, candidate,
                     max_drift_ratio=DEFAULT_MAX_DRIFT_RATIO,
                     absolute_bound_ratio=ABSOLUTE_BOUND_RATIO,
                     val_air_margin_ratio=VAL_AIR_MARGIN_RATIO,
                     ema_alpha=DEFAULT_EMA_ALPHA):
    """防错门控 + EMA 融合，决定是否接受候选基准以及融合后的新值。

    三道门槛依次检查，任意一道未过直接拒绝：
      1. 单次漂移率 <= max_drift_ratio（挡单次跳变/异常周期）
      2. 候选值落在出厂值 ±absolute_bound_ratio 范围内（挡多次同向漂移累积）
      3. 候选值 < VAL_AIR * (1 - val_air_margin_ratio)（挡分母趋零/变号）

    Returns:
        (new_val_water, reason)
        通过门控时 new_val_water 为融合后的浮点数、reason 为 None；
        被拒绝时 new_val_water 为 None、reason 是人类可读的拒绝原因。
    """
    if candidate is None:
        return None, "样本不足，跳过本轮"

    if old_val_water:
        drift_ratio = abs(candidate - old_val_water) / abs(old_val_water)
    else:
        drift_ratio = float("inf")
    if drift_ratio > max_drift_ratio:
        return None, (f"单次漂移率 {drift_ratio:.1%} 超过阈值 {max_drift_ratio:.1%}"
                       f"（候选={candidate:.1f} 旧值={old_val_water:.1f}）")

    lower = factory_val_water * (1 - absolute_bound_ratio)
    upper = factory_val_water * (1 + absolute_bound_ratio)
    if not (lower <= candidate <= upper):
        return None, (f"候选值 {candidate:.1f} 超出出厂值 ±{absolute_bound_ratio:.0%} "
                       f"范围 [{lower:.1f}, {upper:.1f}]")

    max_val_water = val_air * (1 - val_air_margin_ratio)
    if candidate >= max_val_water:
        return None, (f"候选值 {candidate:.1f} 逼近 VAL_AIR({val_air:.1f})，"
                       f"超过安全上限 {max_val_water:.1f}")

    new_val = ema_alpha * candidate + (1 - ema_alpha) * old_val_water
    return round(new_val, 1), None


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
