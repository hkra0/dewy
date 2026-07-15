"""
AHT20 / AHT10 工业级高精度温湿度传感器驱动
AHT20 / AHT10 Temperature and Humidity Sensor Driver

依赖 (Dependencies):
sudo pip3 install adafruit-circuitpython-ahtx0
"""
try:
    import board
    import busio
    import adafruit_ahtx0
except ImportError:
    board = None

class Driver:
    def __init__(self, config):
        if board is None:
            raise ImportError("Please install dependencies: sudo pip3 install adafruit-circuitpython-ahtx0")
            
        try:
            # 默认使用树莓派标准硬件 I2C 引脚
            i2c = busio.I2C(board.SCL, board.SDA)
            self.sensor = adafruit_ahtx0.AHTx0(i2c)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize AHT20 sensor: {e}")
        
    def read(self):
        try:
            return {
                "temperature": round(self.sensor.temperature, 2),
                "humidity": round(self.sensor.relative_humidity, 2)
            }
        except Exception:
            return {}
