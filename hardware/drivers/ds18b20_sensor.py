"""
DS18B20 1-Wire 温度传感器驱动
DS18B20 1-Wire Temperature Sensor

注意 (Note): 
不需要额外安装 Python 库，但必须在树莓派配置中开启 1-Wire 功能 (raspi-config -> Interfacing Options -> 1-Wire)。
通常用于防水型土壤或液体温度探头。
"""
import glob
import time
import os
import logging

class Driver:
    def __init__(self, config):
        self.device_id = config.get("device_id") # e.g., "28-00000xxxxxxx"
        
        base_dir = '/sys/bus/w1/devices/'
        
        if self.device_id:
            self.device_file = os.path.join(base_dir, self.device_id, 'w1_slave')
        else:
            # 如果没有提供 ID，则自动寻找第一个 28- 开头的设备
            try:
                device_folder = glob.glob(base_dir + '28*')[0]
                self.device_file = device_folder + '/w1_slave'
            except IndexError:
                self.device_file = None
                logging.error("No DS18B20 sensor found automatically. Make sure 1-Wire is enabled.")
                
    def _read_temp_raw(self):
        if not self.device_file or not os.path.exists(self.device_file):
            return []
        try:
            with open(self.device_file, 'r') as f:
                return f.readlines()
        except IOError:
            return []
            
    def read(self):
        lines = self._read_temp_raw()
        
        # 验证读取是否成功 (YES表示CRC校验通过)
        if not lines or len(lines) < 2 or lines[0].strip()[-3:] != 'YES':
            return {}
            
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos+2:]
            temp_c = float(temp_string) / 1000.0
            return {"temperature": round(temp_c, 2)}
            
        return {}
