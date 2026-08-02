import smbus2
import time

address = 0x48
print("========================================")
print("  🔍 ADS1115 双通道(A0 & A3)原始数据透视测试")
print("  提示: 使用 Ctrl+C 随时停止")
print("========================================\n")

try:
    bus = smbus2.SMBus(1)
except Exception as e:
    print(f"I2C 总线打开失败: {e}")
    exit()

while True:
    try:
        # ==================================
        # 1. 读 A0 (土壤湿度通道) -> 0xC3
        # ==================================
        bus.write_i2c_block_data(address, 0x01, [0xC3, 0x83])
        time.sleep(0.05)
        data0 = bus.read_i2c_block_data(address, 0x00, 2)
        raw_a0 = (data0[0] << 8) | data0[1]
        if raw_a0 > 32767: 
            raw_a0 -= 65536
        vol_a0 = raw_a0 * 4.096 / 32767.0  

        # ==================================
        # 2. 读 A3 (3.3V 参考电压通道) -> 0xF3
        # ==================================
        bus.write_i2c_block_data(address, 0x01, [0xF3, 0x83])
        time.sleep(0.05)
        data3 = bus.read_i2c_block_data(address, 0x00, 2)
        raw_a3 = (data3[0] << 8) | data3[1]
        if raw_a3 > 32767: 
            raw_a3 -= 65536
        vol_a3 = raw_a3 * 4.096 / 32767.0  

        # ==================================
        # 3. 终极比例补偿计算
        # ==================================
        # ✨ 将基准电压更新为你系统的真实满血电压！
        VCC_BASE = 22581.0 
        ratio = (VCC_BASE / raw_a3) if raw_a3 > 0 else 1.0
        compensated_a0 = raw_a0 * ratio
        
        VAL_AIR, VAL_WATER = 17545, 6883
        percent = ((VAL_AIR - compensated_a0) / (VAL_AIR - VAL_WATER)) * 100.0
        percent = max(0.0, min(100.0, percent))

        print(f"A0(土壤): {raw_a0:5d} ({vol_a0:.3f}V) | A3(真实VCC): {raw_a3:5d} ({vol_a3:.3f}V) | 动态补偿比: {ratio:.3f} | 最终湿度: {percent:5.1f}%")
        
        time.sleep(1)

    except KeyboardInterrupt:
        print("\n⏹️ 测试结束。")
        break
    except Exception as e:
        print(f"读取失败: {e}")
        time.sleep(1)