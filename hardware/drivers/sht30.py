import logging
try:
    import smbus2
except ImportError:  # 非树莓派环境下允许导入本模块，实例化时再报错
    smbus2 = None
import time

logger = logging.getLogger(__name__)

class SHT30:
    def __init__(self, **kwargs):
        self.bus_num = int(kwargs.get("bus", 1))
        # Convert hex string (e.g., "0x44") or int to int
        addr = kwargs.get("address", 0x44)
        if isinstance(addr, str):
            self.address = int(addr, 16)
        else:
            self.address = addr
            
        if smbus2 is None:
            logger.error("未安装 smbus2，SHT30 不可用（pip install smbus2）")
            self.bus = None
            return

        try:
            self.bus = smbus2.SMBus(self.bus_num)
        except Exception as e:
            logger.error("SHT30 初始化失败 (bus=%s addr=0x%02X): %s", self.bus_num, self.address, e)
            self.bus = None

    def read(self, samples=7):
        if not self.bus:
            return {"temperature": None, "humidity": None}
            
        temps = []
        rhs = []
        for _ in range(samples):
            for attempt in range(3):
                try:
                    self.bus.write_i2c_block_data(self.address, 0x24, [0x00])
                    time.sleep(0.15) 
                    
                    data = self.bus.read_i2c_block_data(self.address, 0x00, 6)
                    t = -45.0 + (175.0 * float((data[0] << 8) | data[1]) / 65535.0)
                    h = 100.0 * (float((data[3] << 8) | data[4]) / 65535.0)
                    temps.append(t)
                    rhs.append(max(0.0, min(100.0, h)))
                    break
                except Exception:
                    # 软复位后重试；复位本身失败也只能继续重试
                    try:
                        self.bus.write_i2c_block_data(self.address, 0x30, [0xA2])
                    except OSError as e:
                        logger.debug("SHT30 软复位失败: %s", e)
                    if attempt < 2:
                        time.sleep(0.2)
                        
        if not temps:
            return {"temperature": None, "humidity": None}
            
        temps.sort()
        rhs.sort()
        trim = len(temps) // 4
        if trim > 0:
            valid_temps = temps[trim:-trim]
            valid_rhs = rhs[trim:-trim]
        else:
            valid_temps = temps
            valid_rhs = rhs
            
        avg_t = sum(valid_temps) / len(valid_temps)
        avg_h = sum(valid_rhs) / len(valid_rhs)
        return {"temperature": round(avg_t, 2), "humidity": round(avg_h, 1)}
