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

    浇水后可自动触发校准：``on_watering()`` 启动后台线程，通过 EMA + 滑动窗口
    检测排水曲线的拐点，将稳定期的平滑值更新为新的 ``VAL_WATER``（100% 基准）。
    校准代码在 ``hardware/soil_calibration.py``，本驱动只负责线程生命周期与持久化。
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

        # ---- 由 HardwareManager 注入的元信息（驱动本身无依赖 core） ----
        self._data_dir = kwargs.get("_data_dir")
        self._node_id = kwargs.get("_node_id", "main")
        self._sensor_id = kwargs.get("_sensor_id", "soil")
        # 校准参数（来自 hardware_config 的 [sensors.soil.calibration] 段）
        self._calib_config = kwargs.get("calibration", {})

        # I2C 读取锁：校准线程与正常采样共用同一个 SMBus，必须互斥
        self._lock = threading.Lock()
        # 校准线程控制
        self._calib_thread = None
        self._calib_restart = threading.Event()

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

        读取失败返回 None。加锁以与校准线程互斥。
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

    def on_watering(self):
        """浇水事件通知。启动或重启校准线程。

        若校准线程已在运行（上次浇水后尚未检测到稳定），设置 restart 事件
        让当前循环退出并重新开始--新浇的水会重置排水曲线。
        """
        if not self._calib_config.get("enabled", True):
            logger.debug("校准已禁用，跳过浇水事件")
            return

        self._calib_restart.set()

        if self._calib_thread is not None and self._calib_thread.is_alive():
            logger.info("🔄 校准已在进行中，收到浇水事件，重启校准")
            return  # 当前循环检测到 restart 事件后会退出，新循环由下方启动

        self._calib_thread = threading.Thread(
            target=self._calibration_loop,
            name=f"soil-calib-{self._node_id}-{self._sensor_id}",
            daemon=True,
        )
        self._calib_thread.start()
        logger.info("🌱 启动土壤校准线程 (节点 %s 传感器 %s)", self._node_id, self._sensor_id)

    def _calibration_loop(self):
        """校准线程主循环：运行校准 -> 更新基准 -> 持久化。

        若 ``run_calibration`` 返回 None 且 restart 事件已设置，说明收到了
        新的浇水事件，重新开始一轮；否则正常退出。
        """
        from hardware import soil_calibration

        while True:
            self._calib_restart.clear()
            new_val = soil_calibration.run_calibration(
                read_func=self._read_compensated_raw,
                config=self._calib_config,
                restart_event=self._calib_restart,
            )

            if new_val is not None:
                # 校准成功：更新内存基准并持久化
                old_val = self.VAL_WATER
                self.VAL_WATER = new_val
                if self._data_dir:
                    soil_calibration.save_calibration(
                        self._data_dir, self._node_id, self._sensor_id, new_val,
                    )
                logger.info("✅ 土壤校准完成: VAL_WATER %s -> %.1f (节点 %s 传感器 %s)",
                            old_val, new_val, self._node_id, self._sensor_id)
                return
            elif self._calib_restart.is_set():
                logger.info("🔄 校准重启（收到新浇水事件）")
                continue
            else:
                # 超时或传感器故障
                logger.warning("⚠️ 校准未完成（超时或故障），基准未更新")
                return
