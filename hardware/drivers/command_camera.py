"""通用命令行摄像头驱动：任何能把一张图写到指定路径的命令都能接。

USB 摄像头（fswebcam、ffmpeg）、网络摄像头快照（curl）都用这个。
命令里的 {path} 会被替换成目标文件路径。

配置示例：
    [nodes.main.camera]
    driver = "command_camera"
    command = "fswebcam -r 640x480 --no-banner {path}"
    hq_command = "fswebcam -r 1920x1080 --no-banner {path}"
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class Driver:
    def __init__(self, **kwargs):
        self.command = kwargs.get("command")
        if not self.command:
            raise ValueError("command_camera 需要在配置里给出 command（含 {path} 占位符）")
        # 不单独给高清命令时两档共用一条，只是文件大小没有区别
        self.hq_command = kwargs.get("hq_command", self.command)
        self.timeout = kwargs.get("timeout", 30)

    def capture(self, path, hq=False):
        template = self.hq_command if hq else self.command
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            subprocess.run(template.format(path=path), shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=self.timeout)
        except KeyError:
            logger.error("拍照命令模板里有无法识别的占位符（只支持 {path}）: %s", template)
            return False
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.error("拍照失败: %s", e)
            return False
        return os.path.exists(path)
