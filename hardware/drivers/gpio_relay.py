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
        self.on_state = GPIO.LOW if self.active_low else GPIO.HIGH
        self.off_state = GPIO.HIGH if self.active_low else GPIO.LOW
        
        if GPIO:
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
