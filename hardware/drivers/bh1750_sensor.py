"""
BH1750 环境光照强度(Lux)传感器驱动
BH1750 Ambient Light Sensor Driver

依赖 (Dependencies):
sudo pip3 install smbus2
"""
try:
    import smbus2
except ImportError:
    smbus2 = None

class Driver:
    def __init__(self, **kwargs):
        if smbus2 is None:
            raise ImportError("Please install smbus2: sudo pip3 install smbus2")
            
        self.port = kwargs.get("i2c_port", 1)
        
        addr_config = kwargs.get("address", "0x23")
        if isinstance(addr_config, str) and addr_config.startswith("0x"):
            self.address = int(addr_config, 16)
        else:
            self.address = int(addr_config)
            
        self.bus = smbus2.SMBus(self.port)
        
        # 0x20: High Resolution Mode (1 lx resolution, 120ms measurement time)
        self.measure_cmd = 0x20 
        
    def read(self):
        try:
            # BH1750 返回 2 个字节的数据
            data = self.bus.read_i2c_block_data(self.address, self.measure_cmd, 2)
            
            # 换算公式： (高字节 * 256 + 低字节) / 1.2
            illuminance = ((data[0] << 8) | data[1]) / 1.2
            return {"illuminance": round(illuminance, 2)}
        except Exception:
            return {}
