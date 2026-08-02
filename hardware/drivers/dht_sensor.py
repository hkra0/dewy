"""
常见的温湿度传感器 (DHT11 / DHT22) 驱动
Common Temperature and Humidity Sensor Driver (DHT11 / DHT22)

依赖 (Dependencies):
sudo pip3 install Adafruit_DHT
"""

try:
    import Adafruit_DHT
except ImportError:
    Adafruit_DHT = None

class Driver:
    def __init__(self, **kwargs):
        if Adafruit_DHT is None:
            raise ImportError("Please install Adafruit_DHT library: sudo pip3 install Adafruit_DHT")
            
        sensor_model = kwargs.get("model", "DHT22").upper()
        if sensor_model == "DHT11":
            self.sensor = Adafruit_DHT.DHT11
        else:
            self.sensor = Adafruit_DHT.DHT22
            
        self.pin = kwargs.get("pin")
        if self.pin is None:
            raise ValueError("DHT sensor requires a 'pin' in configuration.")

    def read(self):
        # 尝试读取传感器数据 (Try to grab a sensor reading)
        humidity, temperature = Adafruit_DHT.read_retry(self.sensor, self.pin)
        
        if humidity is not None and temperature is not None:
            return {
                "temperature": round(temperature, 2),
                "humidity": round(humidity, 2)
            }
        else:
            return {}
