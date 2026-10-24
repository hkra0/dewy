#!/usr/bin/env python3
"""Remote ESP32 update/log client. Python standard library only."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirect refused to avoid forwarding the maintenance key")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Worker base URL, e.g. https://dewy.example.com")
    parser.add_argument("--node", required=True)
    parser.add_argument("--firmware", type=Path, help="Application firmware.bin; waits for boot confirmation")
    parser.add_argument("--follow", action="store_true", help="Follow application serial output")
    parser.add_argument("--allow-http", action="store_true", help="Allow plaintext HTTP on a trusted LAN")
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("Use a base HTTP(S) URL without credentials, query or fragment")
    if parsed.scheme == "http" and not args.allow_http:
        parser.error("HTTPS is required; --allow-http is only for a trusted LAN")
    key = os.environ.get("DEWY_WATER_KEY") or getpass.getpass("Water/maintenance key: ")
    if not key:
        parser.error("A water key is required")
    endpoint = args.url.rstrip("/") + "/api/maintenance/" + quote(args.node, safe="")
    opener = build_opener(NoRedirect())

    def call(path="", body=None):
        headers = {"x-water-key": key}
        if body is not None:
            headers["Content-Type"] = "application/octet-stream"
        req = Request(endpoint + path, data=body, headers=headers)
        try:
            with opener.open(req, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read(4096).decode(errors='replace')}") from None

    job = None
    if args.firmware:
        if not 256 <= args.firmware.stat().st_size <= 4 * 1024 * 1024:
            parser.error("Application firmware size must be between 256 bytes and 4 MiB")
        job = call("/firmware", args.firmware.read_bytes())
        print(f"Started {job['id']} SHA-256 {job['sha256']}")
    cursor = 0
    deadline = time.monotonic() + 1800
    previous = None
    while True:
        report = call(f"?after={cursor}")
        for line in report["logs"]:
            print(f"[{time.strftime('%H:%M:%S', time.localtime(line['time']))}] {line['text']}")
        cursor = report["cursor"] if report["cursor"] >= cursor else 0
        current = report.get("job")
        if job:
            if not current or current["id"] != job["id"]:
                raise RuntimeError("Update state lost or replaced; inspect the node before retrying")
            progress = (current["status"], current["sent"])
            if progress != previous:
                print(f"{progress[0]} {current['sent']}/{current['size']}")
                previous = progress
            if current["status"] == "failed":
                raise RuntimeError(f"[{current.get('error_code', 'failed')}] {current['error']}"
                                   + (f" (device: {current['device_error']})" if current.get('device_error') else ""))
            if current["status"] == "succeeded":
                print("New firmware boot confirmed")
                job = None
                if not args.follow:
                    return
            if time.monotonic() > deadline:
                raise RuntimeError("Client wait timed out; update may still be running, inspect status")
        elif not args.follow:
            print(json.dumps({k: v for k, v in report.items() if k != "logs"}, ensure_ascii=False, indent=2))
            return
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
