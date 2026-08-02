try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None
import logging
import time

logger = logging.getLogger(__name__)

class GPIO_Relay:
    def __init__(self, **kwargs):
        self.pin = int(kwargs.get("pin", 4))
        self.active_low = kwargs.get("active_low", True)

        # 没有 RPi.GPIO 的机器（开发机、非 Pi 的 Linux）上不要在构造时就炸：
        # 配置里其它器件仍应正常工作，本继电器在 trigger() 时明确报不可用
        if GPIO is None:
            logger.warning("未安装 RPi.GPIO，GPIO 继电器 pin=%s 不可用", self.pin)
            self.on_state = self.off_state = None
            return

        self.on_state = GPIO.LOW if self.active_low else GPIO.HIGH
        self.off_state = GPIO.HIGH if self.active_low else GPIO.LOW

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN)

    def trigger(self, duration=0.5):
        if not GPIO: return False
        try:
            GPIO.setup(self.pin, GPIO.OUT)
            GPIO.output(self.pin, self.on_state)
            time.sleep(duration)
            GPIO.setup(self.pin, GPIO.IN)
            return True
        except Exception as e:
            logger.error("GPIO 继电器 pin=%s 动作失败: %s", self.pin, e)
            # 无论如何把引脚拉回输入态，避免水泵卡在通电状态
            try:
                GPIO.setup(self.pin, GPIO.IN)
            except Exception:
                logger.critical("⚠️ GPIO pin=%s 无法复位为输入，水泵可能持续通电！", self.pin)
            return False
