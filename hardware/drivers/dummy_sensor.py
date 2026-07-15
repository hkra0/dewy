import random

class Driver:
    """
    这是一个用于演示和测试的虚拟传感器驱动。
    This is a dummy sensor driver for demonstration and testing.
    
    如何编写你自己的驱动？
    How to write your own driver?
    
    1. 确保类名为 `Driver` (Must be named 'Driver')
    2. 实现 `__init__(self, config)` 方法接收字典配置 (Implement __init__ accepting a dict config)
    3. 如果是传感器，实现 `read(self)` 方法，返回一个包含数据的字典 (Implement read() returning a dict for sensors)
    4. 如果是执行器，实现 `set(self, state, **kwargs)` 方法 (Implement set() for actuators)
    """
    def __init__(self, config):
        # 你可以从 hardware_config.toml 中读取参数
        # You can read parameters from hardware_config.toml
        self.base_temp = config.get("base_temp", 25.0)
        self.base_hum = config.get("base_hum", 50.0)

    def read(self):
        # 返回的数据键名应该与前端或你的预期一致（如 temperature, humidity, soil_moisture, pressure）
        return {
            "temperature": round(self.base_temp + random.uniform(-1, 1), 2),
            "humidity": round(self.base_hum + random.uniform(-5, 5), 2),
            "pressure": round(1013.25 + random.uniform(-2, 2), 2)
        }
