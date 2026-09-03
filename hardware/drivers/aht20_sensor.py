"""
AHT20 / AHT10 工业级高精度温湿度传感器驱动
AHT20 / AHT10 Temperature and Humidity Sensor Driver

依赖 (Dependencies):
sudo pip3 install adafruit-circuitpython-ahtx0
"""
import time

try:
    import board
    import busio
    import adafruit_ahtx0
except ImportError:
    board = None

class Driver:
    def __init__(self, **kwargs):
        if board is None:
            raise ImportError("Please install dependencies: sudo pip3 install adafruit-circuitpython-ahtx0")
            
        try:
            # 默认使用树莓派标准硬件 I2C 引脚
            i2c = busio.I2C(board.SCL, board.SDA)
            self.sensor = adafruit_ahtx0.AHTx0(i2c)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize AHT20 sensor: {e}")
        
    def read(self, samples=5):
        temps = []
        hums = []
        for i in range(samples):
            try:
                t = float(self.sensor.temperature)
                h = float(self.sensor.relative_humidity)
                if -40.0 <= t <= 85.0 and 0.0 <= h <= 100.0:
                    temps.append(t)
                    hums.append(h)
            except Exception:
                pass
            if i < samples - 1:
                time.sleep(0.025)

        if not temps:
            return {}

        temps.sort()
        hums.sort()
        trim = len(temps) // 4
        if trim > 0:
            valid_t = temps[trim:-trim]
            valid_h = hums[trim:-trim]
        else:
            valid_t = temps
            valid_h = hums

        return {
            "temperature": round(sum(valid_t) / len(valid_t), 2),
            "humidity": round(sum(valid_h) / len(valid_h), 2)
        }
