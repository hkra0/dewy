"""节点传感器时间窗口降采样聚合器 (Sensor Window Aggregator)。

在 10 分钟的归档周期内，节点（如 ESP32 或本地传感器）会多次上报读数。
前端看板与告警依赖高频的单次读数（保持实时响应）；
而后台归档如果直接抓取单点瞬间快照，会将环境微对流和瞬态抖动混叠（Aliasing）为锯齿。

本模块在内存中暂存窗口内的采样点：
- 连续数值量（温度、湿度、气压、水温、电压、电流等）：在归档时计算修剪均值 (Trimmed Mean)，过滤偶然突刺；
- 离散/状态量（如 fed, fed_time）：透传或保留最新有效状态；
- 窗口采样不足或节点离线时优雅回退至当前快照。
"""

import threading
from collections import defaultdict

# 每个指标在单个 10 分钟窗口内保留的最大样本数，防止极端异常下内存无界膨胀
MAX_WINDOW_SAMPLES = 200

# 常用物理量的标准舍入精度
_FIELD_PRECISION = {
    "temperature": 2,
    "humidity": 1,
    "pressure": 2,
    "water_temp": 2,
    "soil_moisture": 1,
    "soil_adc_raw": 1,
    "voltage": 2,
    "current": 1,
}


def _trimmed_mean(values):
    """计算列表的修剪均值 (Trimmed Mean)。

    样本数 >= 4 时剔除最高和最低各 trim 个数；不足时计算全量均值。
    """
    if not values:
        return None
    if len(values) == 1:
        return values[0]

    s = sorted(values)
    n = len(s)
    trim = max(1, n // 8) if n >= 4 else 0
    valid = s[trim:n - trim] if trim > 0 else s
    if not valid:
        valid = s
    return sum(valid) / len(valid)


class SensorAggregator:
    def __init__(self):
        self._lock = threading.Lock()
        # 结构：{node_id: {metric: [val1, val2, ...]}}
        self._numeric_buffers = defaultdict(lambda: defaultdict(list))
        # 结构：{node_id: {metric: latest_val}} 用于状态量或布尔量
        self._state_buffers = defaultdict(dict)

    def record_sample(self, node_id, data):
        """记录一次采样数据。

        支持任意字典，自动区分连续数值与离散/布尔状态。
        """
        if not data or not isinstance(data, dict):
            return

        with self._lock:
            for k, v in data.items():
                if v is None:
                    continue
                # 布尔量（bool 是 int 的子类，需优先判断）
                if isinstance(v, bool):
                    self._state_buffers[node_id][k] = v
                elif isinstance(v, (int, float)):
                    buf = self._numeric_buffers[node_id][k]
                    if len(buf) < MAX_WINDOW_SAMPLES:
                        buf.append(float(v))
                    else:
                        # 超过上限时移除最旧的并追加最新
                        buf.pop(0)
                        buf.append(float(v))
                else:
                    # 字符串或其他离散状态
                    self._state_buffers[node_id][k] = v

    def get_window_summary(self, node_id, latest_snapshot=None):
        """计算指定节点在当前窗口内的聚合汇总，返回 dict。

        latest_snapshot: 该节点的当前最新快照，用于窗口无样本时的兜底或补齐未聚合字段。
        """
        result = {}
        fallback = dict(latest_snapshot or {})

        with self._lock:
            num_metrics = dict(self._numeric_buffers.get(node_id, {}))
            state_metrics = dict(self._state_buffers.get(node_id, {}))

        # 1. 聚合数值型指标
        all_numeric_keys = set(num_metrics.keys())
        # 如果 fallback 中有数值键，但窗口中未捕获，也纳入考虑
        for k, v in fallback.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                all_numeric_keys.add(k)

        for k in all_numeric_keys:
            vals = num_metrics.get(k)
            if vals:
                mean_val = _trimmed_mean(vals)
                prec = _FIELD_PRECISION.get(k, 2)
                result[k] = round(mean_val, prec)
            elif k in fallback:
                result[k] = fallback[k]

        # 2. 状态量与非数值指标透传
        # 先合并状态缓冲区中的值
        for k, v in state_metrics.items():
            result[k] = v
        # 再由 fallback 补充尚未覆盖的状态量（例如 node_id 等）
        for k, v in fallback.items():
            if k not in result:
                result[k] = v

        return result

    def reset_window(self, node_id=None):
        """重置窗口累积数据。若 node_id 为 None 则重置全部节点。"""
        with self._lock:
            if node_id is None:
                self._numeric_buffers.clear()
                self._state_buffers.clear()
            else:
                self._numeric_buffers.pop(node_id, None)
                self._state_buffers.pop(node_id, None)


# 单例实例，供各模块统一导入使用
aggregator = SensorAggregator()
