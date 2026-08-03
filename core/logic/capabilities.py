"""节点能力：某个节点上"界面该显示什么"的唯一判据。

单独成模块是为了让这条规则**只存在一处**。它同时取决于硬件（有没有相机）
与用户配置（水泵/灯的执行器 id 可配、每日照片可关），过去这些判断散在五个
前端模块里各写一份，改一次配置就要同步五处，漏一处就是"接了硬件但界面上没有"。
`/api/nodes` 把它算好下发，前端一律用 `state.js` 的 `nodeCaps()` 读。

放在 logic 而不是 api：它是业务判断，不是响应组装；也因此不依赖 fastapi，
能被离线单元测试直接调用。
"""

import core.config as config
import core.state as state


def node_capabilities(node_id):
    """返回 {camera, daily_photo, pump, light}，值都是 bool。

    `camera` 与 `daily_photo` 是两件事，**不要合并**：
    前者是"这个节点有没有相机"，管实时预览与高清抓拍；后者还叠加了
    `daily_photo.enabled`，管照片时间轴与"照片"子页签——同一个开关既管拍、
    也管看。关掉每日照片不该把实时画面一起关掉。
    """
    hm = state.hardware_manager
    actuators = hm.actuators.get(node_id, {})
    has_camera = bool(hm.has_camera(node_id))

    return {
        "camera": has_camera,
        "daily_photo": has_camera and config.global_config["daily_photo"].get("enabled", True),
        "pump": config.global_config["auto_water"].get("actuator_id", "pump") in actuators,
        "light": config.global_config["auto_light"].get("actuator_id", "light") in actuators,
    }
