"""Bounded discovery retries and reusable device state, adapted from upstream."""

from dataclasses import dataclass
import concurrent.futures
import logging
import socket
import sys
import time

import lifxlan

SCAN_ATTEMPTS = 3
SCAN_WORKERS = 8


def receive_with_resets(sock, receive, *args, **kwargs):
    """Ignore stale UDP resets without extending the original receive timeout."""
    timeout = sock.gettimeout()
    deadline = time.monotonic() + timeout if timeout is not None else None
    try:
        for _ in range(8):
            try:
                return receive(*args, **kwargs)
            except ConnectionResetError:
                if timeout == 0:
                    raise
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise socket.timeout("Discovery receive timed out")
                    sock.settimeout(remaining)
        raise socket.timeout("Too many discovery connection resets")
    finally:
        sock.settimeout(timeout)


class ResetTolerantSocket(socket.socket):
    def recvfrom(self, *args, **kwargs):
        if self.type != socket.SOCK_DGRAM:
            return super().recvfrom(*args, **kwargs)
        return receive_with_resets(self, super().recvfrom, *args, **kwargs)


def install_socket_workaround():
    """Limit the Windows workaround to the socket factories bound by lifxlan."""
    if sys.platform == "win32":
        lifxlan.lifxlan.socket = ResetTolerantSocket
        lifxlan.device.socket = ResetTolerantSocket


@dataclass
class DeviceState:
    device: object
    label: str
    power: int
    color: tuple
    features: dict
    group_label: str
    zones: tuple = None


def prefetch_device(device, attempts=SCAN_ATTEMPTS, logger=None):
    """Read each device once per scan, tolerating transient failures independently."""
    logger = logger or logging.getLogger(__name__)
    for attempt in range(attempts):
        try:
            multizone = device.supports_multizone()
            # A timed-out GetVersion makes lifxlan fall back to Light. Recover
            # its proper API before trying to read zones; leave test devices alone.
            if (
                multizone
                and isinstance(device, lifxlan.Light)
                and not isinstance(device, lifxlan.MultiZoneLight)
            ):
                device = lifxlan.MultiZoneLight(
                    device.mac_addr,
                    device.ip_addr,
                    device.service,
                    device.port,
                    device.source_id,
                    device.verbose,
                )
            zones = (
                tuple(tuple(color) for color in device.get_color_zones())
                if multizone
                else None
            )
            color = zones[0] if zones else device.get_color()
            color = tuple(color)
            if len(color) != 4:
                raise ValueError("Device returned an invalid colour")
            label = getattr(device, "label", None)
            if label is None:
                label = device.get_label()
            power = getattr(device, "power_level", None)
            if power is None:
                power = device.get_power()
            features = getattr(device, "product_features", None)
            if not isinstance(features, dict):
                get_features = getattr(device, "get_product_features", None)
                features = get_features() if callable(get_features) else {}
            return DeviceState(
                device,
                label,
                power,
                color,
                features or {},
                device.get_group_label(),
                zones,
            )
        except (lifxlan.WorkflowException, OSError, ValueError, IndexError) as exc:
            logger.warning(
                "Device state unavailable (attempt %d/%d): %s",
                attempt + 1,
                attempts,
                exc,
            )
    return None


def group_state(label, states):
    """Build a group from prefetched members without another LAN discovery."""
    group = lifxlan.Group([state.device for state in states])
    group.label = label
    features = {
        "min_kelvin": min(state.features.get("min_kelvin") or 1500 for state in states),
        "max_kelvin": max(state.features.get("max_kelvin") or 9000 for state in states),
    }
    return DeviceState(group, label, states[0].power, states[0].color, features, label)


def prefetch_devices(devices, logger=None):
    """Overlap independent reads while bounding network and thread pressure."""

    def read(device):
        return prefetch_device(device, logger=logger)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(SCAN_WORKERS, len(devices)))
    ) as pool:
        return [state for state in pool.map(read, devices) if state is not None]
