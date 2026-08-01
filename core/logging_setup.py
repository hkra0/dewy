"""日志配置。必须在导入其它 core 模块之前调用 setup_logging()。

默认只写 stdout——树莓派上由 systemd 接管，用 journalctl -u dewy -f 查看。
需要落盘时设环境变量 DEWY_LOG_FILE=/path/to/dewy.log，会自动按 5MB 轮转保留 3 份。

环境变量：
    DEWY_LOG_LEVEL  DEBUG/INFO/WARNING/ERROR，默认 INFO
    DEWY_LOG_FILE   指定后额外写入该文件
"""

import logging
import logging.handlers
import os
import sys

_configured = False


def setup_logging():
    """配置根 logger。重复调用无副作用。"""
    global _configured
    if _configured:
        return
    _configured = True

    level_name = os.environ.get("DEWY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # 时间格式沿用原先 print 里的 [HH:MM:SS]，日志行观感不变
    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-7s %(name)-20s %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):   # 清掉 uvicorn/basicConfig 可能预置的 handler
        root.removeHandler(h)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    log_file = os.environ.get("DEWY_LOG_FILE")
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as e:
            root.warning("无法写入日志文件 %s: %s，仅输出到 stdout", log_file, e)

    # 这两个库在 DEBUG 级别下噪音极大，单独压到 WARNING
    logging.getLogger("paho").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
