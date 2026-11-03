"""
scanner.py - virus scanning of uploaded attachments with ClamAV.

Used by: routes_records.py (attachment upload).   Uses: config.py
ClamAV runs as a separate container ("clamav" in docker-compose.yml). This file talks
to it with the clamd INSTREAM protocol. When CLAMAV_HOST is empty, scanning is off.
If scanning is on and ClamAV cannot be reached, uploads are REFUSED (fail closed).
"""
import socket
import struct

import config


def enabled():
    return bool(config.CLAMAV_HOST)


def scan_stream(fileobj):
    """Returns ('clean', ''), ('infected', virus name) or ('error', reason)."""
    try:
        with socket.create_connection((config.CLAMAV_HOST, config.CLAMAV_PORT), timeout=60) as sock:
            sock.sendall(b"zINSTREAM\0")
            while True:
                chunk = fileobj.read(65536)
                if not chunk:
                    break
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))              # end of data
            reply = b""
            while not reply.endswith(b"\0"):
                part = sock.recv(4096)
                if not part:
                    break
                reply += part
    except OSError as exc:
        return "error", str(exc)
    text = reply.decode("utf-8", "replace").strip("\0\n ")
    if text.endswith("OK"):
        return "clean", ""
    if text.endswith("FOUND"):
        return "infected", text.replace("stream:", "").replace("FOUND", "").strip()
    return "error", text or "no answer from the scanner"
