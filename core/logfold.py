"""重复失败日志的渐进式折叠。

同一个故障源持续失败时，抑制窗口逐级放大：首次立即告警，之后
1 分钟内只汇总一次，仍不恢复就放宽到 5 分钟、15 分钟、1 小时。
故障恢复后状态清零，下次再出问题仍会立即告警。

这样既保证「坏了马上看得见」，又不会让一个坏掉的传感器
以每 2 秒一条的速度刷屏、并把日志写满 SD 卡。

本模块只依赖标准库，core 与 hardware 两层都可安全导入。
"""

import logging
import threading
import time

# 连续失败时的抑制窗口（秒）：1 分钟 → 5 分钟 → 15 分钟 → 1 小时封顶
DEFAULT_WINDOWS = (60, 300, 900, 3600)


def format_duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    return f"{seconds / 3600:.1f} 小时"


class FailureFolder:
    """按 key 跟踪连续失败，决定本次是否应该输出日志。线程安全。"""

    def __init__(self, windows=DEFAULT_WINDOWS):
        if not windows:
            raise ValueError("windows 不能为空")
        self._windows = tuple(windows)
        self._lock = threading.Lock()
        self._states = {}

    def record_failure(self, key, now=None):
        """登记一次失败。

        返回 (should_log, folded_count, window_sec)：
          should_log   本次是否应输出
          folded_count 本次输出所覆盖的失败次数（首次为 1）
          window_sec   本次输出覆盖的时长（首次为 0）
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            st = self._states.get(key)
            if st is None:
                self._states[key] = {
                    "window_idx": 0,
                    "next_emit": now + self._windows[0],
                    "folded": 0,
                    "total": 1,
                    "last_emit": now,
                }
                return True, 1, 0.0

            st["total"] += 1
            if now < st["next_emit"]:
                st["folded"] += 1
                return False, 0, 0.0

            folded = st["folded"] + 1      # 含本次
            window = now - st["last_emit"]
            st["folded"] = 0
            st["last_emit"] = now
            # 每输出一次就把窗口放大一级，直到封顶
            st["window_idx"] = min(st["window_idx"] + 1, len(self._windows) - 1)
            st["next_emit"] = now + self._windows[st["window_idx"]]
            return True, folded, window

    def record_success(self, key):
        """登记一次成功并清除状态，返回此前的累计失败次数（0 表示本来就正常）。"""
        with self._lock:
            st = self._states.pop(key, None)
            return st["total"] if st else 0

    def next_window(self, key):
        """当前 key 的下一个抑制窗口秒数，仅供测试与诊断。"""
        with self._lock:
            st = self._states.get(key)
            return self._windows[st["window_idx"]] if st else 0


_default_folder = FailureFolder()


def log_failure(logger, key, msg, *args, level=logging.WARNING, folder=None):
    """记录一次失败，自动折叠重复项。返回本次是否真的输出了。

    用法与 logger.warning 一致，只是多一个用于区分故障源的 key：

        log_failure(logger, f"sensor:{node}:{sid}",
                    "传感器 %s 读取失败: %s", sid, err)
    """
    folder = _default_folder if folder is None else folder
    should_log, folded, window = folder.record_failure(key)
    if not should_log:
        return False

    if folded > 1:
        logger.log(level, msg + "（过去 %s 内第 %d 次，将降低告警频率）",
                   *args, format_duration(window), folded)
    else:
        logger.log(level, msg, *args)
    return True


def log_recovery(logger, key, msg, *args, level=logging.INFO, folder=None):
    """记录一次成功。此前若有失败被折叠，补一条恢复日志。

    返回本次是否真的输出了（此前一直正常时不输出，避免刷屏）。
    """
    folder = _default_folder if folder is None else folder
    total = folder.record_success(key)
    if total <= 0:
        return False
    logger.log(level, msg + "（此前累计失败 %d 次）", *args, total)
    return True
