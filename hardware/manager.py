import os
import json
import importlib
import threading

def load_config_file(data_dir):
    # Support multiple config formats, fallback to empty if none found.
    # Note: Search first in project root, then in data_dir
    search_dirs = ['.', data_dir]
    for d in search_dirs:
        for ext in ['toml', 'yaml', 'json']:
            path = os.path.join(d, f"hardware_config.{ext}")
            if os.path.exists(path):
                print(f"Loading hardware config from: {path}")
                if ext == 'json':
                    with open(path, 'r') as f:
                        return json.load(f)
                elif ext == 'toml':
                    try:
                        try:
                            import tomllib as toml
                        except ImportError:
                            import tomli as toml
                        with open(path, 'rb') as f:
                            return toml.load(f)
                    except ImportError:
                        print("TOML parser not found (needs Python 3.11+ or tomli). Try JSON format instead.")
                elif ext == 'yaml':
                    try:
                        import yaml
                        with open(path, 'r') as f:
                            return yaml.safe_load(f)
                    except ImportError:
                        print("PyYAML not found. Try JSON format instead.")
    
    print("Warning: No hardware_config.[toml|yaml|json] found. Using empty config.")
    return {}

class HardwareManager:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.config = load_config_file(data_dir)
        self.nodes = self.config.get("nodes", {})
        
        self.local_sensors = {}
        self.actuators = {}
        self.mqtt_nodes = {}
        
        self.sensor_lock = threading.Lock()
        
        self._init_hardware()
        
    def _init_hardware(self):
        for node_id, node_info in self.nodes.items():
            node_type = node_info.get("type", "local")
            if node_type == "local":
                self.local_sensors[node_id] = {}
                self.actuators[node_id] = {}
                
                sensors = node_info.get("sensors", {})
                for s_id, s_conf in sensors.items():
                    driver_name = s_conf.get("driver")
                    if driver_name:
                        driver_class = self._load_driver_class(driver_name)
                        if driver_class:
                            self.local_sensors[node_id][s_id] = driver_class(**s_conf)
                            
                actuators = node_info.get("actuators", {})
                for a_id, a_conf in actuators.items():
                    driver_name = a_conf.get("driver")
                    if driver_name:
                        driver_class = self._load_driver_class(driver_name)
                        if driver_class:
                            self.actuators[node_id][a_id] = driver_class(**a_conf)
            elif node_type == "mqtt_node":
                self.mqtt_nodes[node_id] = node_info
                
    def _load_driver_class(self, driver_name):
        driver_map = {
            "SHT30": ("hardware.drivers.sht30", "SHT30"),
            "ADS1115_Soil": ("hardware.drivers.ads1115", "ADS1115_Soil"),
            "INA219_UPS": ("hardware.drivers.ina219", "INA219_UPS"),
            "GPIO_Relay": ("hardware.drivers.gpio_relay", "GPIO_Relay"),
            "MQTT_Relay": ("hardware.drivers.mqtt_relay", "MQTT_Relay")
        }
        
        if driver_name in driver_map:
            module_name, class_name = driver_map[driver_name]
            try:
                module = importlib.import_module(module_name)
                return getattr(module, class_name)
            except Exception as e:
                print(f"Failed to load driver {driver_name}: {e}")
                return None
        return None

    def read_local_node(self, node_id):
        data = {}
        if node_id in self.local_sensors:
            with self.sensor_lock:
                for s_id, sensor in self.local_sensors[node_id].items():
                    try:
                        res = sensor.read()
                        if res:
                            data.update(res)
                    except Exception as e:
                        print(f"Sensor {s_id} read failed: {e}")
        return data

    def trigger_actuator(self, node_id, actuator_id, **kwargs):
        if node_id in self.actuators and actuator_id in self.actuators[node_id]:
            actuator = self.actuators[node_id][actuator_id]
            return actuator.trigger(**kwargs)
        return False
        
    def get_actuator(self, node_id, actuator_id):
        if node_id in self.actuators and actuator_id in self.actuators[node_id]:
            return self.actuators[node_id][actuator_id]
        return None
        
    def get_mqtt_topics(self):
        topics = []
        for node_info in self.mqtt_nodes.values():
            if "topic" in node_info:
                topics.append(node_info["topic"])
        # Add topics from MQTT actuators
        for node_id in self.actuators:
            for actuator in self.actuators[node_id].values():
                if hasattr(actuator, "topic"):
                    topics.append(actuator.topic)
        return list(set(topics))
