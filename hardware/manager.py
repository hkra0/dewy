import importlib
import inspect
import json
import logging
import os
import pkgutil
import threading

from core.logfold import log_failure, log_recovery

logger = logging.getLogger(__name__)

# 历史配置里的驱动名与模块名对不上（小写化也推导不出来），只为这几个留别名。
# 新驱动不需要在此登记：driver 名直接写模块名或类名即可。
_LEGACY_DRIVER_ALIASES = {
    "ADS1115_Soil": "ads1115",
    "INA219_UPS": "ina219",
}

_DRIVER_PACKAGE = "hardware.drivers"

def load_config_file(data_dir):
    # Support multiple config formats, fallback to empty if none found.
    # Note: Search first in project root, then in data_dir
    search_dirs = ['.', data_dir]
    for d in search_dirs:
        for ext in ['toml', 'yaml', 'json']:
            path = os.path.join(d, f"hardware_config.{ext}")
            if os.path.exists(path):
                logger.info("从 %s 加载硬件配置", path)
                if ext == 'json':
                    with open(path, 'r') as f:
                        return json.load(f)
                elif ext == 'toml':
                    try:
                        try:
                            import tomllib as toml
                        except ImportError:
                            import tomli as toml
                        with open(path, 'rb') as f:
                            return toml.load(f)
                    except ImportError:
                        logger.error("缺少 TOML 解析器（需 Python 3.11+ 或 pip install tomli），改用 JSON 格式")
                elif ext == 'yaml':
                    try:
                        import yaml
                        with open(path, 'r') as f:
                            return yaml.safe_load(f)
                    except ImportError:
                        logger.error("未安装 PyYAML（pip install PyYAML），改用 JSON 格式")
    
    logger.warning("未找到 hardware_config.[toml|yaml|json]，将以空配置启动（无任何传感器）")
    return {}

class HardwareManager:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.config = load_config_file(data_dir)
        self.nodes = self.config.get("nodes", {})
        
        self.local_sensors = {}
        self.actuators = {}
        self.cameras = {}
        self.mqtt_nodes = {}

        self.sensor_lock = threading.Lock()
        self._driver_class_cache = {}
        self._default_camera = None
        self._legacy_camera_nodes = set()
        # (node_id, sensor_id) -> 该传感器最近一次成功读取返回的字段名集合。
        # 供调用方按字段挑选要读的传感器（见 sensors_for_field）。
        # 读失败时不清空，保留上次已知的字段。
        self._sensor_fields = {}
        
        self._init_hardware()
        
    def _init_hardware(self):
        for node_id, node_info in self.nodes.items():
            node_type = node_info.get("type", "local")
            if node_type == "local":
                self.local_sensors[node_id] = {}
                self.actuators[node_id] = {}
                
                for s_id, s_conf in node_info.get("sensors", {}).items():
                    # 老配置用 [nodes.x.sensors.camera] 作为"这个节点有相机"的标记，
                    # 它从来不是真传感器（没有驱动会返回相机读数），早期实现里
                    # 也只是加载失败后被静默跳过。现在驱动能解析到了，若真把它
                    # 实例化出来，dummy 之类会开始往节点数据里灌假读数。
                    if s_id == "camera":
                        self._legacy_camera_nodes.add(node_id)
                        continue
                    obj = self._build_device(node_id, "传感器", s_id, s_conf)
                    if obj is not None:
                        self.local_sensors[node_id][s_id] = obj

                for a_id, a_conf in node_info.get("actuators", {}).items():
                    obj = self._build_device(node_id, "执行器", a_id, a_conf)
                    if obj is not None:
                        self.actuators[node_id][a_id] = obj

                # 相机一个节点至多一个，故是单个表而非字典
                cam_conf = node_info.get("camera")
                if cam_conf:
                    obj = self._build_device(node_id, "相机", "camera", cam_conf)
                    if obj is not None:
                        self.cameras[node_id] = obj
            elif node_type == "mqtt_node":
                self.mqtt_nodes[node_id] = node_info
                
    def _build_device(self, node_id, kind, dev_id, conf):
        """实例化一个传感器/执行器，失败只跳过它自己。

        驱动的 __init__ 里缺依赖、地址不通、参数写错都会抛异常，
        而 HardwareManager 是在 core.state 导入期构造的——
        任何一个驱动抛出去都会连带整个服务起不来，故在此逐个兜住。

        向驱动注入三个以 ``_`` 开头的元信息参数（``_data_dir`` /
        ``_node_id`` / ``_sensor_id``），供需要校准或持久化的驱动使用。
        它们用下划线前缀以区别于硬件配置项，驱动可选择忽略。
        """
        driver_name = conf.get("driver")
        if not driver_name:
            logger.error("%s %s (节点 %s) 未指定 driver，已跳过", kind, dev_id, node_id)
            return None

        driver_class = self._load_driver_class(driver_name)
        if driver_class is None:
            logger.error("%s %s (节点 %s) 因驱动 %s 不可用而跳过",
                         kind, dev_id, node_id, driver_name)
            return None

        # 复制一份配置，注入元信息（不污染原始 conf）
        # _data_dir / _node_id / _sensor_id 供需要校准或持久化的驱动使用
        params = dict(conf)
        params.setdefault("_data_dir", getattr(self, "data_dir", None))
        params.setdefault("_node_id", node_id)
        params.setdefault("_sensor_id", dev_id)

        try:
            return self._instantiate(driver_class, params)
        except Exception as e:
            logger.error("%s %s (节点 %s) 初始化失败，已跳过: %s",
                         kind, dev_id, node_id, e)
            return None

    def _load_driver_class(self, driver_name):
        """按名字找到驱动类，找不到返回 None（并记明原因）。

        不再维护白名单：把 .py 丢进 hardware/drivers/ 就能用。解析顺序为
        先按模块名直接 import，再退回扫描整个包找同名类，因此 driver 既可以写
        模块名（"http_sensor"）也可以写类名（"SHT30"）。
        """
        if driver_name in self._driver_class_cache:
            return self._driver_class_cache[driver_name]

        cls, reason = self._resolve_driver_class(driver_name)
        if cls is None:
            # 旧实现在这里静默返回 None，传感器会无声消失，故障现场只剩一条“没数据”
            logger.error("驱动 %s 无法加载：%s", driver_name, reason)
        self._driver_class_cache[driver_name] = cls
        return cls

    def _resolve_driver_class(self, driver_name):
        """返回 (驱动类, 失败原因)，成功时原因为 None。"""
        errors = []

        for module_name in self._module_candidates(driver_name):
            try:
                module = importlib.import_module(f"{_DRIVER_PACKAGE}.{module_name}")
            except ModuleNotFoundError:
                continue
            except Exception as e:
                # 模块存在但导入就炸（多半是缺第三方依赖），这是最该说清楚的一类失败
                errors.append(f"{module_name} 导入失败: {e}")
                continue
            cls = self._pick_driver_class(module, driver_name)
            if cls is not None:
                return cls, None
            errors.append(f"{module_name} 中找不到驱动类")

        # 模块名对不上时，扫全包找同名类，让 driver 可以直接写类名
        for module_name in self._iter_driver_modules():
            try:
                module = importlib.import_module(f"{_DRIVER_PACKAGE}.{module_name}")
            except Exception:
                continue  # 上面已经记过的失败不重复累积
            cls = getattr(module, driver_name, None)
            if inspect.isclass(cls):
                return cls, None

        if errors:
            return None, "；".join(errors)
        return None, (f"在 {_DRIVER_PACKAGE}/ 下找不到对应模块或类"
                      f"（已尝试 {', '.join(self._module_candidates(driver_name))}）")

    @staticmethod
    def _module_candidates(driver_name):
        """driver 名到模块名的若干猜测，按可能性排序、去重。"""
        lowered = driver_name.lower()
        candidates = [
            _LEGACY_DRIVER_ALIASES.get(driver_name),
            driver_name,
            lowered,
            f"{lowered}_sensor",   # bh1750 -> bh1750_sensor
            f"{lowered}_relay",
        ]
        seen = []
        for c in candidates:
            if c and c not in seen:
                seen.append(c)
        return seen

    @staticmethod
    def _iter_driver_modules():
        package = importlib.import_module(_DRIVER_PACKAGE)
        return [m.name for m in pkgutil.iter_modules(package.__path__)]

    @staticmethod
    def _pick_driver_class(module, driver_name):
        """在模块里挑出驱动类：Driver > 同名类 > 模块内唯一的驱动形状的类。"""
        for attr in ("Driver", driver_name):
            cls = getattr(module, attr, None)
            if inspect.isclass(cls):
                return cls

        found = [
            obj for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__
            and any(hasattr(obj, m) for m in ("read", "trigger", "set"))
        ]
        return found[0] if len(found) == 1 else None

    @staticmethod
    def _instantiate(driver_class, conf):
        """兼容两种构造约定实例化驱动。

        规范写法是 __init__(self, **kwargs)；早期文档写的是 __init__(self, config)
        接收整个字典，外部按老文档写的驱动仍需能用，故按签名分派。
        conf 里的 driver 键是给本类自己用的，不往下传，
        免得写死形参的驱动收到意料之外的关键字。
        """
        params = {k: v for k, v in conf.items() if k != "driver"}
        try:
            sig = inspect.signature(driver_class.__init__)
        except (TypeError, ValueError):
            return driver_class(**params)

        accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD
                             for p in sig.parameters.values())
        if accepts_kwargs:
            return driver_class(**params)

        positional = [p for name, p in sig.parameters.items()
                      if name != "self"
                      and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                     inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        if len(positional) == 1 and positional[0].name in ("config", "conf", "cfg"):
            return driver_class(params)
        return driver_class(**params)

    def read_local_node(self, node_id, sensor_ids=None):
        """读取节点上的传感器并合并结果。

        sensor_ids 为 None 时读全部；给定时只读其中存在的那些——
        调用方可以据此把高频采样（如 UPS 电流）与低频采样分开，
        不必为了一个字段把整条 I2C 总线上的器件全部唤醒一遍。
        """
        data = {}
        if node_id in self.local_sensors:
            sensors = self.local_sensors[node_id]
            if sensor_ids is not None:
                wanted = set(sensor_ids)
                sensors = {s_id: s for s_id, s in sensors.items() if s_id in wanted}
            with self.sensor_lock:
                for s_id, sensor in sensors.items():
                    # 本方法被高频轮询，坏掉的传感器若每次都打日志
                    # 一天就是十几万条，故用折叠告警
                    key = f"sensor:{node_id}:{s_id}"
                    try:
                        res = sensor.read()
                        if res:
                            data.update(res)
                            self._sensor_fields[(node_id, s_id)] = set(res.keys())
                        log_recovery(logger, key, "传感器 %s (节点 %s) 已恢复", s_id, node_id)
                    except Exception as e:
                        log_failure(logger, key, "传感器 %s (节点 %s) 读取失败: %s", s_id, node_id, e)
        return data

    def calibratable_sensors(self, node_id):
        """该节点上支持离线 ABC 校准的传感器。

        鸭子类型：同时实现了 ``calibration_state()`` 与 ``apply_calibration()``
        的（如 ADS1115_Soil）即视为可校准，不检查类型、不 import 驱动。
        供 ``core/logic/soil_abc.py`` 的每日校准任务遍历。
        """
        sensors = self.local_sensors.get(node_id, {})
        return {
            s_id: sensor for s_id, sensor in sensors.items()
            if hasattr(sensor, "calibration_state") and hasattr(sensor, "apply_calibration")
        }

    def sensors_for_field(self, node_id, field):
        """最近一次成功读取中提供了 field 的传感器 id 列表。

        字段来自实际读数而非配置声明，所以驱动返回什么就认什么，
        新增驱动无需在别处登记它提供哪些字段。节点从未成功读过时返回空列表。
        """
        return [s_id for (n_id, s_id), fields in self._sensor_fields.items()
                if n_id == node_id and field in fields]

    def fields_of(self, node_id, sensor_ids):
        """这些传感器已知会提供的字段集合。"""
        fields = set()
        for s_id in sensor_ids:
            fields |= self._sensor_fields.get((node_id, s_id), set())
        return fields

    def trigger_actuator(self, node_id, actuator_id, **kwargs):
        """驱动一个执行器。规范方法是 trigger(**kwargs)。

        早期文档写的是 set(state, **kwargs)，按老文档写的驱动仍应能用，
        故在此退回调用 set(True, ...)。
        """
        actuator = self.get_actuator(node_id, actuator_id)
        if actuator is None:
            return False

        if hasattr(actuator, "trigger"):
            return actuator.trigger(**kwargs)
        if hasattr(actuator, "set"):
            return actuator.set(True, **kwargs)

        logger.error("执行器 %s (节点 %s) 既没有 trigger() 也没有 set()",
                     actuator_id, node_id)
        return False
        
    def get_actuator(self, node_id, actuator_id):
        if node_id in self.actuators and actuator_id in self.actuators[node_id]:
            return self.actuators[node_id][actuator_id]
        return None
        
    def has_camera(self, node_id):
        """该节点是否声明了相机。

        与 get_camera() 分开：get_camera() 带默认回退（老配置不写 camera 段
        也能拍照），而"要不要给用户显示相机界面"必须看配置里到底声明了没有，
        否则一台没接摄像头的机器也会长出一个永远拍不出图的相机页。
        """
        return node_id in self.cameras or node_id in self._legacy_camera_nodes

    def get_camera(self, node_id=None):
        """取相机驱动，未配置任何相机时返回 None。

        不指定 node_id 时返回第一个配置了相机的节点上的那个：
        拍照相关的端点与每日照片都只认一个相机，没有节点维度。
        配置里没写 camera 段时退回默认的树莓派 CSI 相机，
        这样老的 hardware_config.toml 不用改也照常拍照。
        """
        if node_id is not None:
            return self.cameras.get(node_id)
        if self.cameras:
            return next(iter(self.cameras.values()))

        if self._default_camera is None:
            driver_class = self._load_driver_class("rpicam")
            if driver_class is None:
                return None
            self._default_camera = driver_class()
        return self._default_camera

    def get_mqtt_topics(self):
        topics = []
        for node_info in self.mqtt_nodes.values():
            if "topic" in node_info:
                topics.append(node_info["topic"])
            if "config_topic" in node_info:
                topics.append(f"{node_info['config_topic']}/state")
        # Add topics from MQTT actuators
        for node_id in self.actuators:
            for actuator in self.actuators[node_id].values():
                if hasattr(actuator, "topic"):
                    topics.append(actuator.topic)
        return list(set(topics))
