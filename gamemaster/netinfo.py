"""Find the laptop's address on the local Wi-Fi, for the join QR code."""

from __future__ import annotations

import socket


def lan_ip() -> str:
    """The IP other devices on the Wi-Fi can reach this machine at.

    Connecting a UDP socket sends nothing; it only asks the OS which
    interface it would use, which works with no internet at all.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
