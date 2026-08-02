# Dewy Hardware Abstraction Layer (HAL)

This directory (`hardware/`) contains the Hardware Abstraction Layer for the Dewy project.
It decouples the application logic from the underlying hardware interfaces (I2C, 1-Wire, GPIO, HTTP, …).

## How to add your own sensor/actuator

You don't need to touch `main.py`, `core/`, `api/`, **or `manager.py`** — drivers are discovered
automatically. There is no registry to update.

1. **Create a driver file**: add a new `.py` file in `hardware/drivers/` (e.g. `my_sensor.py`).
2. **Define the class**: name it `Driver`, or give it the same name you will write in
   the `driver` field of the config.
3. **Implement the required methods**:
   - `__init__(self, **kwargs)` — `kwargs` holds every key of that device's config
     section, except `driver` itself. Raise on unrecoverable setup errors; the manager
     logs it and skips just this device.
   - `read(self)` — **sensors**: return a dict of readings, e.g. `{"temperature": 25.5}`.
     Return `{}` when a read fails; the previous value is kept.
   - `trigger(self, **kwargs)` — **actuators**: perform the action, return `True`/`False`.
4. **Declare it in your config**:
   ```toml
   [nodes.main.sensors.my_custom_device]
   driver = "my_sensor"   # module name (my_sensor.py) or class name
   my_param = 123         # arrives as kwargs["my_param"]
   ```

### How `driver` is resolved

The manager tries, in order: the exact module name, its lowercase form,
`<name>_sensor`, `<name>_relay`, and finally a package-wide scan for a class of that
name. So `"bh1750"`, `"bh1750_sensor"` and `"SHT30"` all resolve. If nothing matches,
an **error is logged naming the driver and what was tried** — the device is skipped,
never dropped silently.

### Compatibility

Older drivers written against the previous convention still work: `__init__(self, config)`
taking the whole dict is detected by signature, and an actuator exposing only
`set(state, **kwargs)` is called as `set(True, **kwargs)`. New drivers should use
`**kwargs` and `trigger()`.

### Dependencies

Guard third-party imports at module top (`try: import foo / except ImportError: foo = None`)
and raise from `__init__` if the dependency is missing. That keeps the driver package
importable on machines that don't have your sensor's library installed. Add the
dependency as a commented optional line in `requirements.txt`.

## Built-in Generic Drivers

If you don't know Python, you can still integrate external data:
- **`http_sensor.py`**: fetches JSON from any local or web URL (needs `requests`).
- **`script_sensor.py`**: runs a shell/python/node command and parses stdout as JSON.

*For a commented code example, see `drivers/dummy_sensor.py`.*

## Note on field names

Fields whose names match the `node_data` columns
(`temperature`, `humidity`, `soil_moisture`, `pressure`, `voltage`, `current`)
are stored in that table's own columns. Any other field a driver returns is stored
as a generic metric row and is available through the API, but the built-in dashboard
charts only plot the columns above.
