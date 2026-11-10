#!/usr/bin/env python3
"""Dewy mDNS Unicast Responder Helper.

Listens on UDP port 5353 (mDNS).
When an mDNS query for 'robin.local' is received from the local LAN (e.g. ESP32),
it immediately replies with a UNICAST mDNS A-record response directed to the querier.
This bypasses Wi-Fi client isolation / multicast filtering on home optical modems.
"""

import logging
import socket
import struct
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mdns_helper")

MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
PI_IP = "192.168.1.5"


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass

    sock.bind(("", MDNS_PORT))

    mreq = struct.pack("4s4s", socket.inet_aton(MDNS_GROUP), socket.inet_aton(PI_IP))
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except Exception as e:
        logger.warning("Could not add multicast membership for %s: %s", PI_IP, e)
        mreq = struct.pack("4sl", socket.inet_aton(MDNS_GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    logger.info("Dewy mDNS Unicast Helper started on %s:%d for robin.local -> %s", MDNS_GROUP, MDNS_PORT, PI_IP)

    # Pre-build mDNS response:
    # Transaction ID: 0, Flags: 0x8400 (Authoritative response)
    # Questions: 0, Answers: 1, Authority: 0, Additional: 0
    # Name: \x05robin\x05local\x00
    # Type: 1 (A), Class: 0x8001 (IN + Flush), TTL: 120, Length: 4, IP: 192.168.1.5
    resp = bytearray()
    resp += struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    resp += b"\x05robin\x05local\x00"
    resp += struct.pack(">HHIH4s", 1, 0x8001, 120, 4, socket.inet_aton(PI_IP))

    while True:
        try:
            data, addr = sock.recvfrom(2048)
            sender_ip, sender_port = addr
            if sender_ip in ("127.0.0.1", PI_IP, "192.168.1.8"):
                continue
            if b"robin" in data.lower():
                sock.sendto(resp, addr)
                logger.info("Sent unicast mDNS response to %s:%d", sender_ip, sender_port)
        except Exception as e:
            logger.error("Error handling mDNS packet: %s", e)


if __name__ == "__main__":
    main()

