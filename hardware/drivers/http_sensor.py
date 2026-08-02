import requests
import logging

logger = logging.getLogger(__name__)

class Driver:
    """
    通用 HTTP 传感器驱动
    Generic HTTP Sensor Driver
    
    允许你从任何返回 JSON 的局域网或公网 URL 获取数据。
    Allows you to fetch JSON data from any LAN or WAN URL.
    
    配置示例 (Config Example):
    [nodes.main.sensors.my_http_sensor]
    driver = "http_sensor"
    url = "http://192.168.1.100/data"
    timeout = 3
    """
    def __init__(self, config):
        self.url = config.get("url")
        self.timeout = config.get("timeout", 5)
        
        if not self.url:
            raise ValueError("HTTP sensor requires a 'url' in configuration.")

    def read(self):
        try:
            response = requests.get(self.url, timeout=self.timeout)
            response.raise_for_status()
            
            # 假设该接口直接返回类似 {"temperature": 25, "humidity": 60} 的 JSON
            # Assumes the endpoint returns a JSON dict directly.
            data = response.json()
            if isinstance(data, dict):
                return data
            return {}
        except Exception as e:
            logger.error(f"HTTP sensor error from {self.url}: {e}")
            return {}
