try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None
import time

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
        except Exception:
            try: GPIO.setup(self.pin, GPIO.IN)
            except: pass
            return False
