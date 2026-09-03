"""
BME280 / BMP280 温湿度气压传感器驱动
BME280 / BMP280 Temperature, Humidity, and Pressure Sensor

依赖 (Dependencies):
sudo pip3 install smbus2 RPi.bme280
"""
import time

try:
    import smbus2
    import bme280
except ImportError:
    smbus2 = None

class Driver:
    def __init__(self, **kwargs):
        if smbus2 is None:
            raise ImportError("Please install dependencies: sudo pip3 install smbus2 RPi.bme280")
        
        self.port = kwargs.get("i2c_port", 1)
        
        # 处理地址格式，支持配置中写入 "0x76" 或直接 118
        addr_config = kwargs.get("address", "0x76")
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

    def read(self, samples=3):
        temps = []
        hums = []
        press = []
        for i in range(samples):
            try:
                data = bme280.sample(self.bus, self.address)
                if -40.0 <= data.temperature <= 85.0 and 0.0 <= data.humidity <= 100.0 and 300.0 <= data.pressure <= 1200.0:
                    temps.append(data.temperature)
                    hums.append(data.humidity)
                    press.append(data.pressure)
            except Exception:
                pass
            if i < samples - 1:
                time.sleep(0.02)

        if not temps:
            return {}

        temps.sort()
        hums.sort()
        press.sort()
        mid = len(temps) // 2
        return {
            "temperature": round(temps[mid], 2),
            "humidity": round(hums[mid], 2),
            "pressure": round(press[mid], 2)
        }
