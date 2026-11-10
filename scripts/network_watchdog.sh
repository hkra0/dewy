#!/usr/bin/env bash
# Dewy Network & Cloudflare Tunnel Watchdog
# Checks local Wi-Fi connectivity and Cloudflare Tunnel health, recovering automatically without power-cycling.

GATEWAY="192.168.1.1"
CHECK_HOST="223.5.5.5"

# 1. Check Wi-Fi gateway
if ! ping -c 2 -W 2 "$GATEWAY" > /dev/null 2>&1; then
    logger -t dewy-watchdog "Gateway $GATEWAY unreachable, attempting Wi-Fi reconnect..."
    nmcli connection up "101" > /dev/null 2>&1 || true
    exit 0
fi

# 2. Check Internet connectivity
if ! ping -c 2 -W 2 "$CHECK_HOST" > /dev/null 2>&1; then
    # Internet is temporarily down (e.g. ISP drop), don't restart services unnecessarily
    exit 0
fi

# 3. Check cloudflared service state
if ! systemctl is-active --quiet cloudflared; then
    logger -t dewy-watchdog "cloudflared inactive, restarting service..."
    systemctl restart cloudflared
fi

