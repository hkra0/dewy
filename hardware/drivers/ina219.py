import logging
try:
    import smbus2
except ImportError:  # 非树莓派环境下允许导入本模块，实例化时再报错
    smbus2 = None

logger = logging.getLogger(__name__)

class INA219_UPS:
    def __init__(self, **kwargs):
        self.bus_num = int(kwargs.get("bus", 1))
        addr = kwargs.get("address", 0x43)
        if isinstance(addr, str):
            self.address = int(addr, 16)
        else:
            self.address = addr
            
        if smbus2 is None:
            logger.error("未安装 smbus2，INA219 不可用（pip install smbus2）")
            self.bus = None
            return

        try:
            self.bus = smbus2.SMBus(self.bus_num)
            self.bus.write_i2c_block_data(self.address, 0x00, [0x39, 0x9F])
            self.bus.write_i2c_block_data(self.address, 0x05, [0x1A, 0x00])
        except Exception as e:
            logger.error("INA219 初始化失败 (bus=%s addr=0x%02X): %s", self.bus_num, self.address, e)
            self.bus = None

    def read(self):
        if not self.bus:
            return {"voltage": None, "current": None}
            
        try:
            v_raw = ((self.bus.read_i2c_block_data(self.address, 0x02, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x02, 2)[1]) >> 3
            c_raw = (self.bus.read_i2c_block_data(self.address, 0x04, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x04, 2)[1]
            if c_raw > 32767: c_raw -= 65536
            voltage = v_raw * 0.004
            return {"voltage": round(voltage, 2), "current": round(c_raw * 1.0, 1)}
        except (OSError, IndexError) as e:
            logger.warning("INA219 电压/电流读取失败 (bus=%s): %s", self.bus_num, e)
            return {"voltage": None, "current": None}
