import importlib
import json
import logging
import os
import threading

from core.logfold import log_failure, log_recovery

logger = logging.getLogger(__name__)

def load_config_file(data_dir):
    # Support multiple config formats, fallback to empty if none found.
    # Note: Search first in project root, then in data_dir
    search_dirs = ['.', data_dir]
    for d in search_dirs:
        for ext in ['toml', 'yaml', 'json']:
            path = os.path.join(d, f"hardware_config.{ext}")
            if os.path.exists(path):
                logger.info("从 %s 加载硬件配置", path)
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
                        logger.error("缺少 TOML 解析器（需 Python 3.11+ 或 pip install tomli），改用 JSON 格式")
                elif ext == 'yaml':
                    try:
                        import yaml
                        with open(path, 'r') as f:
                            return yaml.safe_load(f)
                    except ImportError:
                        logger.error("未安装 PyYAML（pip install PyYAML），改用 JSON 格式")
    
    logger.warning("未找到 hardware_config.[toml|yaml|json]，将以空配置启动（无任何传感器）")
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
                logger.error("驱动 %s 加载失败: %s", driver_name, e)
                return None
        return None

    def read_local_node(self, node_id):
        data = {}
        if node_id in self.local_sensors:
            with self.sensor_lock:
                for s_id, sensor in self.local_sensors[node_id].items():
                    # 本方法每 2 秒被轮询一次，坏掉的传感器若每次都打日志
                    # 一天就是十几万条，故用折叠告警
                    key = f"sensor:{node_id}:{s_id}"
                    try:
                        res = sensor.read()
                        if res:
                            data.update(res)
                        log_recovery(logger, key, "传感器 %s (节点 %s) 已恢复", s_id, node_id)
                    except Exception as e:
                        log_failure(logger, key, "传感器 %s (节点 %s) 读取失败: %s", s_id, node_id, e)
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
