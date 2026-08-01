#!/bin/bash
# Power-Saver script for Raspberry Pi Zero 2 W
# Usage: ./power_saver.sh [enable|disable]

ACTION=$1

if [ "$ACTION" = "enable" ]; then
    echo "Enabling Power-Saving Mode..."
    
    # 1. Turn off HDMI
    if command -v vcgencmd >/dev/null 2>&1; then
        vcgencmd display_power 0
    elif command -v tvservice >/dev/null 2>&1; then
        tvservice -o
    fi

    # 2. Turn off ACT and PWR LEDs (requires root, but we try anyway)
    if [ -f /sys/class/leds/ACT/brightness ]; then
        echo 0 | sudo tee /sys/class/leds/ACT/brightness >/dev/null 2>&1
    fi
    if [ -f /sys/class/leds/PWR/brightness ]; then
        echo 0 | sudo tee /sys/class/leds/PWR/brightness >/dev/null 2>&1
    fi

    # 3. Block Wi-Fi and Bluetooth to save radio power
    echo "Blocking WiFi and Bluetooth..."
    if command -v rfkill >/dev/null 2>&1; then
        sudo rfkill block wifi bluetooth
    fi

    # 4. CPU Hotplug: Disable Core 1, 2, 3 (keep Core 0 alive)
    echo "Disabling extra CPU cores..."
    for i in 1 2 3; do
        if [ -f "/sys/devices/system/cpu/cpu$i/online" ]; then
            echo 0 | sudo tee "/sys/devices/system/cpu/cpu$i/online" >/dev/null 2>&1
        fi
    done

    echo "Power-Saving Mode ENABLED."

elif [ "$ACTION" = "disable" ]; then
    echo "Disabling Power-Saving Mode..."
    
    # 1. Turn on HDMI
    if command -v vcgencmd >/dev/null 2>&1; then
        vcgencmd display_power 1
    elif command -v tvservice >/dev/null 2>&1; then
        tvservice -p
    fi

    # 2. Turn on ACT and PWR LEDs (Restore to default triggers)
    if [ -f /sys/class/leds/ACT/trigger ]; then
        echo mmc0 | sudo tee /sys/class/leds/ACT/trigger >/dev/null 2>&1
    fi
    if [ -f /sys/class/leds/PWR/trigger ]; then
        echo default-on | sudo tee /sys/class/leds/PWR/trigger >/dev/null 2>&1
    fi

    # 3. Unblock Wi-Fi and Bluetooth
    echo "Unblocking WiFi and Bluetooth..."
    if command -v rfkill >/dev/null 2>&1; then
        sudo rfkill unblock wifi bluetooth
    fi

    # 4. CPU Hotplug: Enable Core 1, 2, 3
    echo "Enabling all CPU cores..."
    for i in 1 2 3; do
        if [ -f "/sys/devices/system/cpu/cpu$i/online" ]; then
            echo 1 | sudo tee "/sys/devices/system/cpu/cpu$i/online" >/dev/null 2>&1
        fi
    done

    echo "Power-Saving Mode DISABLED."
else
    echo "Usage: $0 [enable|disable]"
    exit 1
fi
