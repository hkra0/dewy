import json

class MQTT_Relay:
    def __init__(self, **kwargs):
        self.topic = kwargs.get("topic")
        
    def trigger(self, mqtt_client, command="a1", duration=None):
        if not mqtt_client: return False
        try:
            if duration is not None:
                cmd = f"c1={duration}"
                mqtt_client.publish(self.topic, json.dumps({"command": cmd}))
            else:
                mqtt_client.publish(self.topic, json.dumps({"command": command}), retain=True)
            return True
        except Exception:
            return False
