"""自动化单元测试。

这里是可以在任意机器上离线跑的纯逻辑测试。需要接真实传感器的手动
硬件排查脚本在 `scripts/hardware_check/`，不由这里收集。

运行：
    python3 -m unittest discover -s tests -t .

**为什么这里要在导入被测模块之前打桩**：`core.logic.*` 都会
`import core.state`，而 `core/state.py` 在导入期就会实例化
`HardwareManager` —— 读 hardware_config.toml、加载 smbus2 / RPi.GPIO 驱动、
生成密钥文件。非树莓派机器上这一步直接抛异常。所以本包在 __init__ 里
先把 `core.state` / `core.config` / `core.database` 替换成空壳模块，
测试模块随后 import `core.logic.*` 时拿到的就是桩。

被测的三个函数（compute_next_boundary / _select_photos_to_delete /
clean_soil_anomalies 的判定逻辑）都不碰这些桩的真实行为，只有
clean_soil_anomalies 会调 db 的两个函数，由各测试自行替换。
"""

import sys
import types
from unittest.mock import MagicMock


class _StubModule(types.ModuleType):
    """任何属性都返回一个 MagicMock，且同名属性每次返回同一个对象。

    这样 `from core.database import init_db` 这类导入期取属性也能成立，
    测试里替换某个属性时又不会影响其他属性。
    """

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def _install_stub(name):
    if not isinstance(sys.modules.get(name), _StubModule):
        sys.modules[name] = _StubModule(name)
    return sys.modules[name]


state_stub = _install_stub("core.state")
config_stub = _install_stub("core.config")
db_stub = _install_stub("core.database")

# 少数几个被当作普通值（而非可调用对象）使用的属性，给一个像样的默认值
state_stub.PHOTO_DIR = "/nonexistent/photos"
state_stub.THUMB_DIR = "/nonexistent/photos/thumbs"
config_stub.global_config = {}
