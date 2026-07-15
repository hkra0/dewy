import smbus2

class INA219_UPS:
    def __init__(self, **kwargs):
        self.bus_num = int(kwargs.get("bus", 1))
        addr = kwargs.get("address", 0x43)
        if isinstance(addr, str):
            self.address = int(addr, 16)
        else:
            self.address = addr
            
        try:
            self.bus = smbus2.SMBus(self.bus_num)
            self.bus.write_i2c_block_data(self.address, 0x00, [0x39, 0x9F])
            self.bus.write_i2c_block_data(self.address, 0x05, [0x1A, 0x00])
        except Exception as e:
            print(f"Warning: Failed to initialize INA219 on bus {self.bus_num}: {e}")
            self.bus = None

    def read(self):
        if not self.bus:
            return {"voltage": None, "current": None}
            
        try:
            v_raw = ((self.bus.read_i2c_block_data(self.address, 0x02, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x02, 2)[1]) >> 3
            c_raw = (self.bus.read_i2c_block_data(self.address, 0x04, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x04, 2)[1]
            if c_raw > 32767: c_raw -= 65536
            voltage = v_raw * 0.004
            return {"voltage": round(voltage, 2), "current": round(c_raw * 1.0, 1)}
        except: 
            return {"voltage": None, "current": None}
