import smbus2
import time
import sys
from datetime import datetime

# ==========================================
# 终端 UI 与日志助手
# ==========================================
def log(msg):
    sys.stdout.write("\r\033[K")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def print_live(msg):
    sys.stdout.write(f"\r\033[K{msg}")
    sys.stdout.flush()

# ==========================================
# 初始化全局 I2C 总线，避免文件描述符耗尽
# ==========================================
try:
    global_bus = smbus2.SMBus(1)
except Exception as e:
    print(f"初始化 I2C 失败: {e}")
    sys.exit(1)

# ==========================================
# 传感器读取逻辑
# ==========================================
def read_sht30():
    temps = []
    rhs = []
    for _ in range(7):  # 采样7次
        for attempt in range(3):
            try:
                # 关闭时钟拉伸 (0x24, 0x00)
                global_bus.write_i2c_block_data(0x44, 0x24, [0x00])
                time.sleep(0.15)
                data = global_bus.read_i2c_block_data(0x44, 0x00, 6)
                t = -45.0 + (175.0 * float((data[0] << 8) | data[1]) / 65535.0)
                h = 100.0 * (float((data[3] << 8) | data[4]) / 65535.0)
                temps.append(t)
                rhs.append(max(0.0, min(100.0, h)))
                break
            except Exception as e:
                # 遇到错误尝试软复位
                try:
                    global_bus.write_i2c_block_data(0x44, 0x30, [0xA2])
                except:
                    pass
                if attempt < 2:
                    time.sleep(0.2)
    
    if not temps:
        raise Exception("SHT30 read failed after multiple retries")
        
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
    return avg_t, avg_h

def read_ads1115():
    # 1. 读 A3 拿参考电压
    global_bus.write_i2c_block_data(0x48, 0x01, [0xF3, 0x83])
    time.sleep(0.05)
    data_vcc = global_bus.read_i2c_block_data(0x48, 0x00, 2)
    vcc_raw = (data_vcc[0] << 8) | data_vcc[1]
    if vcc_raw > 32767: vcc_raw -= 65536
    if vcc_raw <= 0: raise ValueError("VCC reading error")
    
    # 2. 连续读取 A0 通道 11 次
    raw_values = []
    for _ in range(11):
        global_bus.write_i2c_block_data(0x48, 0x01, [0xC3, 0x83])
        time.sleep(0.05)
        data = global_bus.read_i2c_block_data(0x48, 0x00, 2)
        raw_val = (data[0] << 8) | data[1]
        if raw_val > 32767: raw_val -= 65536
        raw_values.append(raw_val)
        time.sleep(0.01)
        
    # 3. 排序并掐头去尾滤波
    raw_values.sort()
    valid_raws = raw_values[2:-2]
    avg_raw = sum(valid_raws) / len(valid_raws)
    
    # 4. 比例补偿计算 (使用之前测试的真实满血基准)
    VCC_BASE = 22581.0
    compensated_raw = avg_raw * (VCC_BASE / vcc_raw)
    
    # 5. 计算湿度
    VAL_AIR, VAL_WATER = 17545, 6883
    percent = ((VAL_AIR - compensated_raw) / (VAL_AIR - VAL_WATER)) * 100.0
    return max(0.0, min(100.0, percent))

def read_ups():
    try:
        global_bus.write_i2c_block_data(0x43, 0x00, [0x39, 0x9F])
        global_bus.write_i2c_block_data(0x43, 0x05, [0x1A, 0x00])
    except: pass
    
    v_raw_data = global_bus.read_i2c_block_data(0x43, 0x02, 2)
    v_raw = ((v_raw_data[0] << 8) | v_raw_data[1]) >> 3
    voltage = v_raw * 0.004
    
    c_raw_data = global_bus.read_i2c_block_data(0x43, 0x04, 2)
    c_raw = (c_raw_data[0] << 8) | c_raw_data[1]
    if c_raw > 32767: 
        c_raw -= 65536
    current = c_raw * 1.0
    return voltage, current

# ==========================================
# 主监测循环
# ==========================================
def main():
    print("==================================================")
    print("  🌱 Dewy 硬件连通性实时监测 (持续半小时)")
    print("  提示: 使用 Ctrl+C 随时停止测试")
    print("==================================================\n")

    status = {'SHT30': None, 'ADS1115': None, 'UPS': None}

    def update_state(name, is_ok, error_msg=""):
        if status[name] is None:
            if is_ok: log(f"✅ {name} 初始连接成功。")
            else: log(f"❌ {name} 初始连接失败: {error_msg}")
            status[name] = is_ok
        elif status[name] != is_ok:
            if is_ok: log(f"🟢 {name} 重新恢复连接！")
            else: log(f"🔴 {name} 突然掉线无响应: {error_msg}")
            status[name] = is_ok

    start_time = time.time()
    DURATION = 30 * 60  # 半小时 (1800秒)

    try:
        while True:
            elapsed = int(time.time() - start_time)
            if elapsed > DURATION:
                log("⏹️ 测试结束，已达到 30 分钟。")
                break
            
            remain_min = (DURATION - elapsed) // 60
            remain_sec = (DURATION - elapsed) % 60

            try:
                t, h = read_sht30()
                update_state('SHT30', True)
                str_sht = f"空气: {t:.1f}℃ {h:.1f}%"
            except Exception as e:
                update_state('SHT30', False, str(e))
                str_sht = "空气: -- ℃ -- %"

            try:
                soil_pct = read_ads1115()
                update_state('ADS1115', True)
                str_soil = f"土壤: {soil_pct:.1f}%"
            except Exception as e:
                update_state('ADS1115', False, str(e))
                str_soil = "土壤: -- %"

            try:
                v, c = read_ups()
                update_state('UPS', True)
                str_ups = f"电源: {v:.2f}V {c:.0f}mA"
            except Exception as e:
                update_state('UPS', False, str(e))
                str_ups = "电源: -- V -- mA"

            live_str = f"⏳ 倒计时 {remain_min:02d}:{remain_sec:02d} | {str_sht} | {str_soil} | {str_ups}"
            print_live(live_str)

            time.sleep(2)

    except KeyboardInterrupt:
        log("⏹️ 用户手动终止 (Ctrl+C)。")
        print("\n测试安全结束，拜拜！")

if __name__ == "__main__":
    main()