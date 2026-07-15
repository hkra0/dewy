# Dewy Hardware Abstraction Layer (HAL)

This directory (`hardware/`) contains the Hardware Abstraction Layer for the Dewy project. 
It allows you to completely decouple the main application logic from the underlying hardware interfaces (I2C, SPI, GPIO, etc.).

## How to add your own sensor/actuator

You don't need to touch `main.py` to add new hardware! 

1. **Create a driver file**: Add a new `.py` file in `hardware/drivers/` (e.g., `my_sensor.py`).
2. **Define a `Driver` class**: Your file MUST contain a class named `Driver`.
3. **Implement required methods**:
   - `__init__(self, config)`: Receives a dictionary containing parameters from `hardware_config.toml`.
   - `read(self)`: (For sensors) Return a dictionary of data (e.g., `{"temperature": 25.5}`).
   - `set(self, state, **kwargs)`: (For actuators) Accept boolean `state` and execute action.
4. **Update Configuration**: Open `hardware_config.toml` and declare your sensor:
   ```toml
   [nodes.main.sensors.my_custom_device]
   driver = "my_sensor"  # matches my_sensor.py
   # any extra configs will be passed to __init__
   my_param = 123
   ```

## Built-in Generic Drivers
If you don't know Python, you can still easily integrate external data:
- **`http_sensor.py`**: Fetches JSON from any local or web URL.
- **`script_sensor.py`**: Executes a bash/python/node command and parses the standard output as JSON.

*For a code example, see `drivers/dummy_sensor.py`.*
