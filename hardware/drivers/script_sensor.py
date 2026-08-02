import subprocess
import json
import logging

logger = logging.getLogger(__name__)

class Driver:
    """
    通用本地脚本传感器驱动
    Generic Local Script Sensor Driver
    
    允许你运行任意本地命令或脚本，只要该脚本的**标准输出 (stdout)** 是一段 JSON 即可。
    Allows running any local command/script, as long as its stdout is a JSON string.
    
    配置示例 (Config Example):
    [nodes.main.sensors.my_script]
    driver = "script_sensor"
    command = "python3 /path/to/your/custom_reader.py"
    """
    def __init__(self, **kwargs):
        self.command = kwargs.get("command")
        
        if not self.command:
            raise ValueError("Script sensor requires a 'command' in configuration.")

    def read(self):
        try:
            result = subprocess.run(
                self.command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout.strip())
                if isinstance(data, dict):
                    return data
            else:
                logger.error(f"Script sensor error: {result.stderr}")
            return {}
        except Exception as e:
            logger.error(f"Script sensor execution error: {e}")
            return {}
