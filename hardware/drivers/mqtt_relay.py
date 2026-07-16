import json

class MQTT_Relay:
    def __init__(self, **kwargs):
        self.topic = kwargs.get("topic")
        
    def trigger(self, mqtt_client, command="a1", duration=None, retain=False):
        if not mqtt_client: return False
        try:
            if duration is not None:
                cmd = f"c1={duration}"
                mqtt_client.publish(self.topic, json.dumps({"command": cmd}))
            else:
                mqtt_client.publish(self.topic, json.dumps({"command": command}), retain=retain)
            return True
        except Exception:
            return False
