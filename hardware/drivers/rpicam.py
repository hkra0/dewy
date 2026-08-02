"""树莓派 CSI 摄像头驱动（rpicam-jpeg / libcamera-jpeg）。

分辨率、画质、翻转全部来自 hardware_config，装反了摄像头改配置即可。
命令名也可配：Bullseye 及更早的系统上叫 libcamera-jpeg。
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class Driver:
    def __init__(self, **kwargs):
        self.command = kwargs.get("command", "rpicam-jpeg")
        self.vflip = kwargs.get("vflip", True)
        self.hflip = kwargs.get("hflip", True)
        self.timeout = kwargs.get("timeout", 20)   # 秒，防止拍照进程挂死拖住整轮

        # 每日照片与 /api/image?hq=1 用高清档，实时预览用低清档
        self.hq = {
            "width": int(kwargs.get("hq_width", 2592)),
            "height": int(kwargs.get("hq_height", 1944)),
            "quality": int(kwargs.get("hq_quality", 90)),
            "timeout_ms": int(kwargs.get("hq_timeout_ms", 2000)),
        }
        self.preview = {
            "width": int(kwargs.get("preview_width", 648)),
            "height": int(kwargs.get("preview_height", 486)),
            "quality": int(kwargs.get("preview_quality", 60)),
            "timeout_ms": int(kwargs.get("preview_timeout_ms", 500)),
        }
        self.extra_args = list(kwargs.get("extra_args", []))

    def _build_args(self, path, profile):
        args = [
            self.command, "-o", path,
            "-t", str(profile["timeout_ms"]),
            "--width", str(profile["width"]),
            "--height", str(profile["height"]),
            "-q", str(profile["quality"]),
            "--nopreview",
        ]
        if self.vflip:
            args.append("--vflip")
        if self.hflip:
            args.append("--hflip")
        return args + self.extra_args

    def capture(self, path, hq=False):
        """拍一张存到 path，返回是否成功。"""
        args = self._build_args(path, self.hq if hq else self.preview)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=self.timeout)
        except FileNotFoundError:
            logger.error("找不到拍照命令 %s，请确认已安装或在配置里改 command", self.command)
            return False
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.error("拍照失败 (%s): %s", self.command, e)
            return False
        return os.path.exists(path)
