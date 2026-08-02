import RPi.GPIO as GPIO
import time
import subprocess
import smbus2

# ==========================================
# 1. 硬件引脚与类定义
# ==========================================
GPIO.setmode(GPIO.BCM)
PIN_IN1 = 4 

class INA219_UPS:
    def __init__(self, address=0x43):
        self.bus = smbus2.SMBus(1)
        self.address = address
        try:
            # 初始化 INA219 寄存器
            self.bus.write_i2c_block_data(self.address, 0x00, [0x39, 0x9F])
            self.bus.write_i2c_block_data(self.address, 0x05, [0x1A, 0x00])
        except Exception as e: 
            print(f"UPS 初始化失败，请检查 I2C 连接: {e}")

    def read_status(self):
        try:
            v_raw = ((self.bus.read_i2c_block_data(self.address, 0x02, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x02, 2)[1]) >> 3
            c_raw = (self.bus.read_i2c_block_data(self.address, 0x04, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x04, 2)[1]
            if c_raw > 32767: 
                c_raw -= 65536
            voltage = v_raw * 0.004
            return round(voltage, 2), round(c_raw * 1.0, 1)
        except: 
            return 0.0, 0.0

def check_power_status():
    """获取树莓派底层欠压标志"""
    try:
        output = subprocess.check_output(["vcgencmd", "get_throttled"]).decode('utf-8')
        return output.strip().split('=')[1]
    except:
        return "N/A"

# ==========================================
# 2. 压力测试主逻辑
# ==========================================
try:
    print("==============================================")
    print("      水泵连续高负载压力测试 (带 UPS 监测)    ")
    print("==============================================")
    
    ups = INA219_UPS()
    time.sleep(0.5) # 给传感器一点准备时间
    
    # 获取静息状态数据
    v_idle, c_idle = ups.read_status()
    print(f"[*] 静息状态 (未启动) - 电压: {v_idle}V, 电流: {c_idle}mA")
    print(f"[*] 树莓派底层状态码: {check_power_status()}")
    print("-" * 46)
    
    # 测试参数设置
    test_duration = 3.0  # 连续抽水秒
    sample_rate = 0.2     # 每 0.2 秒采样一次数据
    
    # 确保继电器初始为关闭状态 (输入模式)
    GPIO.setup(PIN_IN1, GPIO.IN)
    time.sleep(1)

    print(f"\n🚀 警告：即将开始 {test_duration} 秒连续抽水！")
    print("时间(s) | 电压 (V) | 电流 (mA) | 底层状态")
    print("-" * 46)

    # 启动水泵！
    start_time = time.time()
    GPIO.setup(PIN_IN1, GPIO.OUT)
    GPIO.output(PIN_IN1, GPIO.LOW)
    
    # 开启高频采样循环
    while (time.time() - start_time) < test_duration:
        current_time = time.time() - start_time
        
        # 抓取 UPS 数据与底层状态
        v, c = ups.read_status()
        pi_status = check_power_status()
        
        # 格式化输出，方便观察对齐
        print(f"{current_time:04.1f}s  |  {v:05.2f}V  | {c:7.1f}mA |  {pi_status}")
        
        # 简单的欠压警告视觉提示
        if pi_status != "0x0":
            print("  ⚠️ [警告] 树莓派底层触发欠压标志！")
            
        time.sleep(sample_rate)

    print("-" * 46)
    print("✅ 压力测试完成，正在关闭水泵...")

finally:
    # 无论程序是否报错，甚至你按 Ctrl+C 强退，都会执行这里！
    # 这是防止水泵一直开着把家里淹了的最后防线
    GPIO.setup(PIN_IN1, GPIO.IN)
    GPIO.cleanup()
    print("[*] 继电器已安全切断，GPIO 已重置。")
