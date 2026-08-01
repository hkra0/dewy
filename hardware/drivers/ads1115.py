import logging
import smbus2
import time

logger = logging.getLogger(__name__)

class ADS1115_Soil:
    def __init__(self, **kwargs):
        self.bus_num = int(kwargs.get("bus", 1))
        addr = kwargs.get("address", 0x48)
        if isinstance(addr, str):
            self.address = int(addr, 16)
        else:
            self.address = addr
            
        self.VAL_AIR = int(kwargs.get("val_air", 17545))
        self.VAL_WATER = int(kwargs.get("val_water", 6883))
        
        try:
            self.bus = smbus2.SMBus(self.bus_num)
        except Exception as e:
            logger.error("ADS1115 初始化失败 (bus=%s addr=0x%02X): %s", self.bus_num, self.address, e)
            self.bus = None

    def read(self, samples=11):
        """中值平均滤波 + A3通道 VCC 比例补偿算法"""
        if not self.bus:
            return {"soil_moisture": None}
            
        try:
            # 1. 先读取 A3 通道 (0xF3) 获取此刻真实的供电电压参考值
            self.bus.write_i2c_block_data(self.address, 0x01, [0xF3, 0x83])
            time.sleep(0.05)
            data_vcc = self.bus.read_i2c_block_data(self.address, 0x00, 2)
            vcc_raw = (data_vcc[0] << 8) | data_vcc[1]
            if vcc_raw > 32767: vcc_raw -= 65536
            if vcc_raw <= 0: return {"soil_moisture": None}
            
            # 2. 读取 A0 通道 (0xC3) 连续采样土壤数据
            raw_values = []
            for _ in range(samples):
                self.bus.write_i2c_block_data(self.address, 0x01, [0xC3, 0x83])
                time.sleep(0.05)
                data = self.bus.read_i2c_block_data(self.address, 0x00, 2)
                raw_val = (data[0] << 8) | data[1]
                if raw_val > 32767: raw_val -= 65536
                
                raw_values.append(raw_val)
                time.sleep(0.01)
                
            if not raw_values: return {"soil_moisture": None}
            
            # 排序并掐头去尾
            raw_values.sort()
            trim_count = len(raw_values) // 4
            if trim_count > 0:
                valid_raws = raw_values[trim_count:-trim_count]
            else:
                valid_raws = raw_values
                
            avg_raw = sum(valid_raws) / len(valid_raws)
            
            # 比例补偿 (Ratiometric Compensation)
            VCC_BASE = 22581.0 
            compensated_raw = avg_raw * (VCC_BASE / vcc_raw)
            
            percent = ((self.VAL_AIR - compensated_raw) / (self.VAL_AIR - self.VAL_WATER)) * 100.0
            return {"soil_moisture": round(max(0.0, min(100.0, percent)), 1)}
        except (OSError, ZeroDivisionError, ValueError) as e:
            logger.warning("ADS1115 土壤湿度读取失败 (bus=%s): %s", self.bus_num, e)
            return {"soil_moisture": None}
