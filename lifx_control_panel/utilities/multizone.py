"""Batched zone writes with bounded retries and inclusive legacy ranges.

Protocol: https://lan.developer.lifx.com/docs/changing-a-device
"""

import struct
import time

import lifxlan
from lifxlan.message import Message
from lifxlan.msgtypes import GetHostFirmware, StateHostFirmware

from .device_actions import valid_color

MAX_EXTENDED_ZONES = 82


class SetExtendedColorZones(Message):
    def __init__(
        self,
        target_addr,
        source_id,
        seq_num,
        payload,
        ack_requested=False,
        response_requested=False,
    ):
        self.fields = payload
        super().__init__(
            510, target_addr, source_id, seq_num, ack_requested, response_requested
        )

    def get_payload(self):
        colors = [valid_color(color) for color in self.fields["colors"]]
        if not 1 <= len(colors) <= MAX_EXTENDED_ZONES:
            raise ValueError("Extended zone packets require 1–82 colours")
        header = struct.pack(
            "<IBHB",
            self.fields["duration"],
            self.fields["apply"],
            self.fields["zone_index"],
            len(colors),
        )
        colors.extend([(0, 0, 0, 0)] * (MAX_EXTENDED_ZONES - len(colors)))
        return header + b"".join(struct.pack("<4H", *color) for color in colors)


def supports_extended(device):
    cached = getattr(device, "supports_extended_multizone", None)
    if cached is not None:
        return cached
    # Only actual LAN devices need a firmware probe; simulated devices use
    # their native zone setter and never open a socket.
    if not isinstance(device, lifxlan.Device):
        return False
    response = device.req_with_resp(GetHostFirmware, StateHostFirmware)
    version = (response.version >> 16, response.version & 0xFFFF)
    device.supports_extended_multizone = version >= (2, 77)
    return device.supports_extended_multizone


def _retry(function, attempts, cancelled):
    for attempt in range(attempts):
        if cancelled():
            return False
        try:
            function()
            return True
        except lifxlan.WorkflowException:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.05)


def set_zone_colors(device, colors, duration=0, attempts=3, cancelled=lambda: False):
    colors = [valid_color(color) for color in colors]
    if not colors or len(colors) > 65535 or attempts < 1:
        raise ValueError("Invalid zone write")
    if supports_extended(device):
        for offset in range(0, len(colors), MAX_EXTENDED_ZONES):
            payload = {
                "duration": duration,
                "apply": 1,
                "zone_index": offset,
                "colors": colors[offset : offset + MAX_EXTENDED_ZONES],
            }
            if not _retry(
                lambda: device.req_with_ack(SetExtendedColorZones, payload),
                attempts,
                cancelled,
            ):
                return
    else:
        if len(colors) > 256:
            raise ValueError("Legacy zone writes support at most 256 zones")
        start = 0
        while start < len(colors):
            end = start
            while end + 1 < len(colors) and colors[end + 1] == colors[start]:
                end += 1
            if not _retry(
                lambda: device.set_zone_color(
                    start, end, colors[start], duration, rapid=False
                ),
                attempts,
                cancelled,
            ):
                return
            start = end + 1
            if start < len(colors):
                time.sleep(0.05)
