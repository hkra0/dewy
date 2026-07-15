"""
BME280 / BMP280 温湿度气压传感器驱动
BME280 / BMP280 Temperature, Humidity, and Pressure Sensor

依赖 (Dependencies):
sudo pip3 install smbus2 RPi.bme280
"""
try:
    import smbus2
    import bme280
except ImportError:
    smbus2 = None

class Driver:
    def __init__(self, config):
        if smbus2 is None:
            raise ImportError("Please install dependencies: sudo pip3 install smbus2 RPi.bme280")
        
        self.port = config.get("i2c_port", 1)
        
        # 处理地址格式，支持配置中写入 "0x76" 或直接 118
        addr_config = config.get("address", "0x76")
        if isinstance(addr_config, str) and addr_config.startswith("0x"):
            self.address = int(addr_config, 16)
        else:
            self.address = int(addr_config)
            
        self.bus = smbus2.SMBus(self.port)
        
        # 加载校准参数
        try:
            bme280.load_calibration_params(self.bus, self.address)
        except Exception as e:
            raise RuntimeError(f"Failed to load BME280 calibration on address {hex(self.address)}: {e}")

    def read(self):
        try:
            data = bme280.sample(self.bus, self.address)
            return {
                "temperature": round(data.temperature, 2),
                "humidity": round(data.humidity, 2),
                "pressure": round(data.pressure, 2)
            }
        except Exception:
            # 硬件读取失败时返回空字典，系统会自动忽略并保持上一次数据
            return {}
