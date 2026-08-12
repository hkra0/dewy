import logging
import threading
import time

try:
    import smbus2
except ImportError:  # 非树莓派环境下允许导入本模块，实例化时再报错
    smbus2 = None

logger = logging.getLogger(__name__)

# VCC 比例补偿的基准值（A3 通道在标称供电下的读数）。
# 独立为类常量，方便子类或测试覆盖。
_VCC_BASE = 22581.0


class ADS1115_Soil:
    """ADS1115 + 电容式土壤湿度传感器驱动。

    采用中值平均滤波 + A3 通道 VCC 比例补偿算法，输出 0–100% 的湿度百分比
    与补偿后的原始 ADC 值（``soil_adc_raw``）。

    100% 湿度基准（``VAL_WATER``）由离线 ABC（Automatic Baseline Calibration）
    任务每日校准：扫描历史 ``soil_adc_raw`` 统计出田间持水量，经门控后通过
    ``apply_calibration()`` 推送到本驱动。算法与门控逻辑在
    ``hardware/soil_calibration.py``，编排在 ``core/logic/soil_abc.py``，
    本驱动只负责暴露状态（``calibration_state()``）与接受更新（``apply_calibration()``）。
    """

    def __init__(self, **kwargs):
        self.bus_num = int(kwargs.get("bus", 1))
        addr = kwargs.get("address", 0x48)
        if isinstance(addr, str):
            self.address = int(addr, 16)
        else:
            self.address = addr

        self.VAL_AIR = int(kwargs.get("val_air", 17545))
        self.VAL_WATER = int(kwargs.get("val_water", 6883))
        # 出厂/配置值：ABC 门控用它做绝对夹紧，防止多次小步漂移累积成大偏移
        self._factory_val_water = self.VAL_WATER

        # ---- 由 HardwareManager 注入的元信息（驱动本身无依赖 core） ----
        self._data_dir = kwargs.get("_data_dir")
        self._node_id = kwargs.get("_node_id", "main")
        self._sensor_id = kwargs.get("_sensor_id", "soil")

        # I2C 读取锁：与并发读取互斥（当前仅正常采样使用，保留以防未来的
        # 并发读取路径，例如手动重校准脚本）
        self._lock = threading.Lock()

        if smbus2 is None:
            logger.error("未安装 smbus2，ADS1115 不可用（pip install smbus2）")
            self.bus = None
            return

        try:
            self.bus = smbus2.SMBus(self.bus_num)
        except Exception as e:
            logger.error("ADS1115 初始化失败 (bus=%s addr=0x%02X): %s", self.bus_num, self.address, e)
            self.bus = None

        # 启动时尝试加载之前持久化的校准基准
        self._load_persisted_calibration()

    # ==================== I2C 读取 ====================

    def _read_compensated_raw(self):
        """中值平均滤波 + A3 通道 VCC 比例补偿，返回 compensated_raw (float)。

        读取失败返回 None。
        """
        if not self.bus:
            return None

        with self._lock:
            try:
                # 1. 先读取 A3 通道 (0xF3) 获取此刻真实的供电电压参考值
                self.bus.write_i2c_block_data(self.address, 0x01, [0xF3, 0x83])
                time.sleep(0.05)
                data_vcc = self.bus.read_i2c_block_data(self.address, 0x00, 2)
                vcc_raw = (data_vcc[0] << 8) | data_vcc[1]
                if vcc_raw > 32767:
                    vcc_raw -= 65536
                if vcc_raw <= 0:
                    return None

                # 2. 读取 A0 通道 (0xC3) 连续采样土壤数据
                raw_values = []
                for _ in range(11):
                    self.bus.write_i2c_block_data(self.address, 0x01, [0xC3, 0x83])
                    time.sleep(0.05)
                    data = self.bus.read_i2c_block_data(self.address, 0x00, 2)
                    raw_val = (data[0] << 8) | data[1]
                    if raw_val > 32767:
                        raw_val -= 65536
                    raw_values.append(raw_val)
                    time.sleep(0.01)

                if not raw_values:
                    return None

                # 排序并掐头去尾
                raw_values.sort()
                trim_count = len(raw_values) // 4
                if trim_count > 0:
                    valid_raws = raw_values[trim_count:-trim_count]
                else:
                    valid_raws = raw_values

                avg_raw = sum(valid_raws) / len(valid_raws)
                compensated_raw = avg_raw * (_VCC_BASE / vcc_raw)
                return compensated_raw
            except (OSError, ZeroDivisionError, ValueError) as e:
                logger.warning("ADS1115 土壤湿度读取失败 (bus=%s): %s", self.bus_num, e)
                return None

    def read(self):
        """读取土壤湿度，返回 ``{"soil_moisture": pct, "soil_adc_raw": raw}``。

        读取失败返回 ``{"soil_moisture": None}``。``soil_adc_raw`` 是补偿后的
        原始 ADC 值，供校准算法与历史记录使用。
        """
        compensated_raw = self._read_compensated_raw()
        if compensated_raw is None:
            return {"soil_moisture": None}

        percent = ((self.VAL_AIR - compensated_raw) / (self.VAL_AIR - self.VAL_WATER)) * 100.0
        return {
            "soil_moisture": round(max(0.0, min(100.0, percent)), 1),
            "soil_adc_raw": round(compensated_raw, 1),
        }

    # ==================== 校准 ====================

    def _load_persisted_calibration(self):
        """从 data/calibration.json 加载上次校准的 VAL_WATER。

        文件不存在或损坏时静默跳过--驱动退回 hardware_config 里的原始值。
        延迟导入 soil_calibration：它只用标准库，但 import 本身也有成本，
        不需要校准的部署不必在启动时付这个代价。
        """
        if not self._data_dir:
            return
        try:
            from hardware import soil_calibration
            val = soil_calibration.load_calibration(self._data_dir, self._node_id, self._sensor_id)
            if val is not None:
                self.VAL_WATER = val
                logger.info("ADS1115 加载持久化校准基准 VAL_WATER=%.1f (节点 %s 传感器 %s)",
                            val, self._node_id, self._sensor_id)
        except Exception as e:
            logger.warning("加载校准基准失败，使用配置默认值: %s", e)

    def calibration_state(self):
        """暴露给离线 ABC 校准任务的当前状态。

        只包含传感器实例自身的状态（当前基准、出厂值），不包含 enabled /
        window_days / max_drift_ratio——那些是用户经设置页调整的全局开关
        （``data/config.json`` 的 ``soil_calibration`` 段），对所有可校准
        传感器统一生效，由 ``core/logic/soil_abc.py`` 从
        ``core.config.global_config`` 读取，不属于单个传感器实例。
        """
        return {
            "val_water": self.VAL_WATER,
            "val_air": self.VAL_AIR,
            "factory_val_water": self._factory_val_water,
        }

    def apply_calibration(self, val_water):
        """接受 ABC 任务算出的新基准：更新内存值并持久化。

        返回 True 表示已接受（内存已更新；落盘失败只记日志，不影响本次生效，
        与 ``save_calibration`` 一贯的"内存优先"语义一致）。
        """
        from hardware import soil_calibration

        old_val = self.VAL_WATER
        self.VAL_WATER = val_water
        if self._data_dir:
            soil_calibration.save_calibration(
                self._data_dir, self._node_id, self._sensor_id, val_water,
            )
        logger.info("✅ ABC 校准更新内存基准: VAL_WATER %s -> %.1f (节点 %s 传感器 %s)",
                    old_val, val_water, self._node_id, self._sensor_id)
        return True
