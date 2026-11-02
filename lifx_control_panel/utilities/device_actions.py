"""Device identity, ordered writes and portable saved light states."""

import json
import threading

import lifxlan

KEYBIND_ACTIONS = ("Toggle Power", "Brightness Up", "Brightness Down")


def device_key(device):
    mac = getattr(device, "mac_addr", None)
    return mac.replace(":", "").lower() if isinstance(mac, str) else str(id(device))


def devices_in(target):
    devices = (
        target.get_device_list() if isinstance(target, lifxlan.Group) else [target]
    )
    return list({device_key(device): device for device in devices}.values())


class CommandGate:
    """Serialize writes per physical light and invalidate superseded queued work."""

    def __init__(self):
        self._mutex = threading.Lock()
        self._versions = {}
        self._locks = {}

    def ticket(self, target):
        with self._mutex:
            return {
                device_key(device): self._versions.get(device_key(device), 0)
                for device in devices_in(target)
            }

    def invalidate(self, target):
        with self._mutex:
            for device in devices_in(target):
                key = device_key(device)
                self._versions[key] = self._versions.get(key, 0) + 1

    def current(self, ticket):
        with self._mutex:
            return all(
                self._versions.get(key, 0) == version for key, version in ticket.items()
            )

    def write(self, target, function, ticket=None):
        ticket = self.ticket(target) if ticket is None else ticket
        for device in devices_in(target):
            key = device_key(device)
            with self._mutex:
                lock = self._locks.setdefault(key, threading.Lock())
            with lock:
                with self._mutex:
                    if ticket.get(key) != self._versions.get(key, 0):
                        continue
                function(device)


def valid_color(color):
    if (
        not isinstance(color, (list, tuple))
        or len(color) != 4
        or any(type(value) is not int or not 0 <= value <= 65535 for value in color)
    ):
        raise ValueError("Invalid saved HSBK colour")
    return tuple(color)


def capture_state(device):
    zones = (
        [valid_color(color) for color in device.get_color_zones()]
        if hasattr(device, "get_color_zones")
        else None
    )
    if zones is not None and not zones:
        raise ValueError("Device has no zones")
    color = zones[0] if zones else valid_color(tuple(device.get_color()))
    return json.dumps(
        {
            "version": 1,
            "label": device.label,
            "power": 65535 if device.get_power() else 0,
            "color": color,
            "zones": zones,
        }
    )


def decode_state(value):
    state = json.loads(value)
    if not isinstance(state, dict):
        raise ValueError("Invalid saved light state")
    if (
        state.get("version") != 1
        or type(state.get("power")) is not int
        or state["power"] not in (0, 65535)
    ):
        raise ValueError("Invalid saved light state")
    state["color"] = valid_color(state.get("color"))
    zones = state["zones"] = state.get("zones")
    if zones is not None:
        if not isinstance(zones, list) or not 1 <= len(zones) <= 65535:
            raise ValueError("Invalid saved zones")
        state["zones"] = [valid_color(color) for color in zones]
    return state


def restore_device(device, state, cancelled=lambda: False):
    if cancelled():
        return
    if state["zones"] and hasattr(device, "set_zone_color"):
        from .multizone import set_zone_colors

        set_zone_colors(device, state["zones"], cancelled=cancelled)
    else:
        device.set_color(state["color"], rapid=False)
    if not cancelled():
        device.set_power(state["power"], rapid=False)
