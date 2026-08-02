import asyncio
from bleak import BleakScanner
import datetime

TARGET_MAC = "A4:C1:38:4C:A0:58"

def parse_bthome_v2(data: bytes, rssi: int):
    # 检查是否是 BTHome v2 的标准未加密开头 (0x40)
    if len(data) < 2 or data[0] != 0x40:
        return
    
    i = 1 # 从第2个字节开始，依次严谨解析
    print(datetime.datetime.now())
    while i < len(data):
        obj_id = data[i]
        try:
            if obj_id == 0x00: # 序号 (1个字节)
                i += 2
            elif obj_id == 0x01: # 电量 (1个字节)
                batt = data[i+1]
                print(f"🔋 电量: {batt} %")
                i += 2
            elif obj_id == 0x02: # 温度 (2个字节)
                temp = int.from_bytes(data[i+1:i+3], byteorder='little', signed=True) / 100.0
                print(f"🌡️ 温度: {temp} °C")
                i += 3
            elif obj_id == 0x03: # 湿度 (2个字节)
                hum = int.from_bytes(data[i+1:i+3], byteorder='little', signed=False) / 100.0
                print(f"💧 湿度: {hum} %")
                i += 3
            elif obj_id == 0x0C: # 电池电压 (2个字节) - 拦截状态包
                volt = int.from_bytes(data[i+1:i+3], byteorder='little', signed=False) / 1000.0
                print(f"⚡ 电压: {volt} V")
                i += 3
            else:
                # 遇到不认识的附加数据，直接跳出，保护程序不崩溃
                break
        except IndexError:
            # 捕获任何意外的截断错误
            break

def detection_callback(device, advertisement_data):
    # 精准狙击我们的目标 MAC
    if device.address.upper() == TARGET_MAC:
        service_data = advertisement_data.service_data
        for uuid, data in service_data.items():
            if "fcd2" in uuid.lower():
                print("-" * 30)
                print(f"📡 收到广播! 📶 信号: {advertisement_data.rssi} dBm")
                parse_bthome_v2(data, advertisement_data.rssi)

async def main():
    print(datetime.datetime.now())
    print(f"持续监听 {TARGET_MAC} ... (按 Ctrl+C 停止)")
    
    # 【关键修改】显式指定主动扫描模式 (scanning_mode="active")
    # 这样树莓派的蓝牙芯片就会转入高频工作状态
    scanner = BleakScanner(
        detection_callback,
        scanning_mode="active"
    )
    
    await scanner.start()
    
    # 持续运行
    try:
        await asyncio.sleep(86400)
    except asyncio.CancelledError:
        pass
    finally:
        await scanner.stop()

if __name__ == "__main__":
    asyncio.run(main())
