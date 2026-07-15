import smbus2
import time

class SHT30:
    def __init__(self, **kwargs):
        self.bus_num = int(kwargs.get("bus", 1))
        # Convert hex string (e.g., "0x44") or int to int
        addr = kwargs.get("address", 0x44)
        if isinstance(addr, str):
            self.address = int(addr, 16)
        else:
            self.address = addr
            
        try:
            self.bus = smbus2.SMBus(self.bus_num)
        except Exception as e:
            print(f"Warning: Failed to initialize SHT30 on bus {self.bus_num}: {e}")
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
                    try:
                        self.bus.write_i2c_block_data(self.address, 0x30, [0xA2])
                    except:
                        pass
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
