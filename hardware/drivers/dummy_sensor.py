import random

class Driver:
    """
    这是一个用于演示和测试的虚拟传感器驱动。
    This is a dummy sensor driver for demonstration and testing.
    
    如何编写你自己的驱动？
    How to write your own driver?

    1. 在 hardware/drivers/ 下新建一个 .py 文件，无需在别处登记
       (Drop a .py file in hardware/drivers/ — no registration needed)
    2. 类名用 `Driver`，或与配置里的 driver 名一致
       (Name the class `Driver`, or match the `driver` value in the config)
    3. `__init__(self, **kwargs)` 接收 hardware_config 里该设备的全部键
       （driver 键本身不会传进来）
       (kwargs holds every key of that device's config section, minus `driver`)
    4. 传感器实现 `read(self)`，返回数据字典；读失败返回 {} 即可
       (Sensors implement read() -> dict; return {} on failure)
    5. 执行器实现 `trigger(self, **kwargs)`，返回 bool 表示是否成功
       (Actuators implement trigger(**kwargs) -> bool)
    """
    def __init__(self, **kwargs):
        # 你可以从 hardware_config.toml 中读取参数
        # You can read parameters from hardware_config.toml
        self.base_temp = kwargs.get("base_temp", 25.0)
        self.base_hum = kwargs.get("base_hum", 50.0)

    def read(self):
        # 返回的数据键名应该与前端或你的预期一致（如 temperature, humidity, soil_moisture, pressure）
        return {
            "temperature": round(self.base_temp + random.uniform(-1, 1), 2),
            "humidity": round(self.base_hum + random.uniform(-5, 5), 2),
            "pressure": round(1013.25 + random.uniform(-2, 2), 2)
        }
