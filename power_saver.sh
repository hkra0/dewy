#!/bin/bash
# Power-Saver script for Raspberry Pi Zero 2 W
#
# Usage:
#   ./power_saver.sh enable  [--no-watchdog]   进入省电模式（默认自动挂看门狗）
#   ./power_saver.sh disable                   退出省电模式并撤销看门狗
#   ./power_saver.sh pet                       续期看门狗（由 core/logic/power.py 定期调用）
#   ./power_saver.sh status                    查看当前 rfkill 与看门狗状态
#
# ── 为什么需要看门狗 ────────────────────────────────────────────────
# enable 会 rfkill block wifi + bluetooth，这台设备没有网口，一旦断网
# 就完全失联、只能物理断电。为避免这种情况，enable 默认会挂一个
# systemd 瞬态定时器：到点自动执行 disable 把网络放回来。
#
# 想长期停留在省电模式的调用方（core/logic/power.py）必须周期性执行
# `pet` 来续期。任何异常——服务崩溃、电流传感器读不到值、恢复逻辑卡死——
# 都会导致无人续期，看门狗到点触发，网络自动恢复。
#
# 超时时间默认 30 分钟，可用环境变量 DEWY_POWERSAVE_WATCHDOG_MIN 覆盖。
# --no-watchdog 可跳过（仅限有物理访问的场合，例如接了屏幕键盘调试）。
# ────────────────────────────────────────────────────────────────

ACTION="${1:-}"
OPTION="${2:-}"

SCRIPT_PATH="$(readlink -f "$0")"
WATCHDOG_UNIT="dewy-powersave-watchdog"
WATCHDOG_MINUTES="${DEWY_POWERSAVE_WATCHDOG_MIN:-30}"

# 以 root 运行时不需要 sudo（也可能根本没装 sudo）
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

# ==============================================================================
# 看门狗
# ==============================================================================

arm_watchdog() {
    if ! command -v systemd-run >/dev/null 2>&1; then
        return 1
    fi

    # 清掉上一轮的定时器，让瞬态单元名可以复用
    $SUDO systemctl stop "${WATCHDOG_UNIT}.timer" >/dev/null 2>&1
    $SUDO systemctl reset-failed "${WATCHDOG_UNIT}.timer" "${WATCHDOG_UNIT}.service" >/dev/null 2>&1

    $SUDO systemd-run \
        --unit="$WATCHDOG_UNIT" \
        --description="dewy power-save auto-revert" \
        --on-active="${WATCHDOG_MINUTES}min" \
        --timer-property=AccuracySec=5s \
        --setenv=DEWY_WATCHDOG_FIRED=1 \
        "$SCRIPT_PATH" disable >/dev/null 2>&1
}

cancel_watchdog() {
    # 由看门狗自己触发的 disable 不去停自己的定时器，避免自锁
    if [ "${DEWY_WATCHDOG_FIRED:-}" = "1" ]; then
        return 0
    fi
    $SUDO systemctl stop "${WATCHDOG_UNIT}.timer" >/dev/null 2>&1
    $SUDO systemctl reset-failed "${WATCHDOG_UNIT}.timer" "${WATCHDOG_UNIT}.service" >/dev/null 2>&1
    return 0
}

watchdog_active() {
    systemctl is-active --quiet "${WATCHDOG_UNIT}.timer" 2>/dev/null
}

# ==============================================================================
# 省电模式开关
# ==============================================================================

do_enable() {
    echo "Enabling Power-Saving Mode..."

    # 1. Turn off HDMI
    if command -v vcgencmd >/dev/null 2>&1; then
        vcgencmd display_power 0
    elif command -v tvservice >/dev/null 2>&1; then
        tvservice -o
    fi

    # 2. Turn off ACT and PWR LEDs (requires root, but we try anyway)
    if [ -f /sys/class/leds/ACT/brightness ]; then
        echo 0 | $SUDO tee /sys/class/leds/ACT/brightness >/dev/null 2>&1
    fi
    if [ -f /sys/class/leds/PWR/brightness ]; then
        echo 0 | $SUDO tee /sys/class/leds/PWR/brightness >/dev/null 2>&1
    fi

    # 3. Block Wi-Fi and Bluetooth to save radio power
    echo "Blocking WiFi and Bluetooth..."
    if command -v rfkill >/dev/null 2>&1; then
        $SUDO rfkill block wifi bluetooth
    fi

    # 4. CPU Hotplug: Disable Core 1, 2, 3 (keep Core 0 alive)
    echo "Disabling extra CPU cores..."
    for i in 1 2 3; do
        if [ -f "/sys/devices/system/cpu/cpu$i/online" ]; then
            echo 0 | $SUDO tee "/sys/devices/system/cpu/cpu$i/online" >/dev/null 2>&1
        fi
    done

    echo "Power-Saving Mode ENABLED."
}

do_disable() {
    echo "Disabling Power-Saving Mode..."

    # 1. Turn on HDMI
    if command -v vcgencmd >/dev/null 2>&1; then
        vcgencmd display_power 1
    elif command -v tvservice >/dev/null 2>&1; then
        tvservice -p
    fi

    # 2. Turn on ACT and PWR LEDs (Restore to default triggers)
    if [ -f /sys/class/leds/ACT/trigger ]; then
        echo mmc0 | $SUDO tee /sys/class/leds/ACT/trigger >/dev/null 2>&1
    fi
    if [ -f /sys/class/leds/PWR/trigger ]; then
        echo default-on | $SUDO tee /sys/class/leds/PWR/trigger >/dev/null 2>&1
    fi

    # 3. Unblock Wi-Fi and Bluetooth
    echo "Unblocking WiFi and Bluetooth..."
    if command -v rfkill >/dev/null 2>&1; then
        $SUDO rfkill unblock wifi bluetooth
    fi

    # 4. CPU Hotplug: Enable Core 1, 2, 3
    echo "Enabling all CPU cores..."
    for i in 1 2 3; do
        if [ -f "/sys/devices/system/cpu/cpu$i/online" ]; then
            echo 1 | $SUDO tee "/sys/devices/system/cpu/cpu$i/online" >/dev/null 2>&1
        fi
    done

    echo "Power-Saving Mode DISABLED."
}

# ==============================================================================
# 入口
# ==============================================================================

case "$ACTION" in
    enable)
        if [ "$OPTION" = "--no-watchdog" ]; then
            echo "WARNING: 未挂看门狗，断网后只能物理断电恢复。"
            do_enable
        else
            # 先挂看门狗再断网：万一 arm 失败，此时网络还在，来得及拒绝
            if arm_watchdog; then
                echo "看门狗已挂载：${WATCHDOG_MINUTES} 分钟后自动恢复网络（除非期间执行 pet 续期）。"
                do_enable
            else
                echo "ERROR: 无法挂载看门狗（systemd-run 不可用或权限不足），已拒绝进入省电模式。" >&2
                echo "       如确实需要，请用: $0 enable --no-watchdog" >&2
                exit 1
            fi
        fi
        ;;

    disable)
        cancel_watchdog
        do_disable
        ;;

    pet)
        if ! arm_watchdog; then
            echo "ERROR: 看门狗续期失败。" >&2
            exit 1
        fi
        echo "看门狗已续期 ${WATCHDOG_MINUTES} 分钟。"
        ;;

    watchdog-cancel)
        cancel_watchdog
        echo "看门狗已撤销（省电状态未改变）。"
        ;;

    status)
        if command -v rfkill >/dev/null 2>&1; then
            rfkill list wifi bluetooth 2>/dev/null | grep -E "^[0-9]+:|Soft blocked"
        fi
        if watchdog_active; then
            echo "watchdog: ARMED"
            systemctl list-timers "${WATCHDOG_UNIT}.timer" --no-pager 2>/dev/null | head -2
        else
            echo "watchdog: not armed"
        fi
        ;;

    *)
        echo "Usage: $0 [enable [--no-watchdog]|disable|pet|watchdog-cancel|status]"
        exit 1
        ;;
esac
