"""This is not a standard test file (yet), but used to simulate a multi-device environment."""

import itertools
import time
from typing import Iterable

from lifxlan import Group

from lifx_control_panel.utilities.utils import Color as DummyColor


# Dummy classes
class DummyDevice:
    _ids = itertools.count(1)

    def __init__(self, label="No label"):
        self.label = label
        self.power = False
        serial = next(self._ids)
        self.mac_addr = "00:16:3e:2a:%02x:%02x" % (serial // 256, serial % 256)
        self.product_features = {"min_kelvin": 1500, "max_kelvin": 9000}
        self.ip_addr = "63.218.207.187"
        self.build_timestamp = 1521690429000000000
        self.version = 2.75
        self.wifi_signal_mw = 32.0
        self.wifi_tx_bytes = 0
        self.wifi_rx_bytes = 0
        self.wifi_build_timestamp = 0
        self.wifi_version = 0.0
        self.vendor = 1
        self.product = 0x65
        self.location_label = "My Home"
        self.location_tuple = (
            3,
            238,
            83,
            151,
            159,
            43,
            44,
            177,
            180,
            149,
            11,
            191,
            243,
            219,
            79,
            115,
        )
        self.location_updated_at = 1516997252637000000
        self.group_label = "Room 2"
        self.group_tuple = (
            50,
            71,
            100,
            191,
            135,
            165,
            21,
            163,
            195,
            54,
            66,
            226,
            0,
            175,
            217,
            223,
        )
        self.group_updated_at = 1516997252642000000

        self._start_time = time.time()

    def is_light(self):
        return True

    def set_label(self, val: str):
        self.label = val

    def set_power(self, val: bool, rapid: bool = False):
        self.power = val
        return self.get_power()

    def get_mac_address(self):
        return self.mac_addr

    def get_ip_addr(self):
        return self.ip_addr

    def get_service(self):
        return 1  # returns in, 1 = UDP

    def get_port(self):
        return 56700

    def get_label(self):
        return self.label

    def get_power(self):
        return self.power

    def get_host_firmware_tuple(self):
        return self.build_timestamp, self.version

    def get_host_firmware_build_timestamp(self):
        return self.build_timestamp

    def get_host_firmware_version(self):
        return self.version

    def get_wifi_info_tuple(self):
        return self.wifi_signal_mw, self.wifi_tx_bytes, self.wifi_rx_bytes

    def get_wifi_signal_mw(self):
        return self.wifi_signal_mw

    def get_wifi_tx_bytes(self):
        return self.wifi_tx_bytes

    def get_wifi_rx_bytes(self):
        return self.wifi_rx_bytes

    def get_wifi_firmware_tuple(self):
        return self.wifi_build_timestamp, self.wifi_version

    def get_wifi_firmware_build_timestamp(self):
        return self.wifi_build_timestamp

    def get_wifi_firmware_version(self):
        return self.wifi_version

    def get_version_tuple(self):
        return self.vendor, self.product, self.version

    def get_location(self):
        return self.location_label

    def get_location_tuple(self):
        return self.location_tuple, self.location_label, self.location_updated_at

    def get_location_label(self):
        return self.location_label

    def get_location_updated_at(self):
        return self.location_updated_at

    def get_group(self):
        return self.group_label

    def get_group_tuple(self):
        return self.group_tuple, self.group_label, self.group_updated_at

    def get_group_label(self):
        return self.group_label

    def get_group_updated_a(self):
        return self.group_updated_at

    def get_vendor(self):
        return self.vendor

    def get_product(self):
        return self.product

    def get_version(self):
        return self.version

    def get_info_tuple(self):
        return time.time(), self.get_uptime(), self.get_downtime()

    def get_time(self):
        return time.time()

    def get_uptime(self):
        return time.time() - self._start_time

    def get_downtime(self):  # no way to make this work. Shouldn't need it
        return 0

    def supports_color(self):
        return True

    def supports_temperature(self):
        return True

    def supports_multizone(self):
        return False

    def supports_infrared(self):
        return True


class DummyBulb(DummyDevice):
    def __init__(self, color=None, label="N/A"):
        super().__init__(label)
        self.color = color or DummyColor(
            6097,
            46851,
            38791,
            3014,
        )
        self.power: int = 0

    # Official api
    @property
    def power_level(self):
        return self.power

    @power_level.setter
    def power_level(self, val):
        self.power = val

    def set_power(self, val: int, duration: int = 0, rapid: bool = False):
        self.power = val

    def set_color(self, val: DummyColor, duration: int = 0, rapid: bool = False):
        self.color = val if isinstance(val, DummyColor) else DummyColor(*val)
        return self.get_color()

    def set_waveform(self, is_transient, color, period, cycles, duty_cycle, waveform):
        pass

    def get_power(self):
        return self.power

    def get_color(self):
        return self.color

    def get_infared(self):
        return self.infared_brightness

    def set_infared(self, val: int):
        self.infared_brightness = val

    def set_hue(self, hue, duration=0, rapid=False):
        self.color.hue = hue

    def set_brightness(self, brightness, duration=0, rapid=False):
        self.color.brightness = brightness

    def set_saturation(self, saturation, duration=0, rapid=False):
        self.color.saturation = saturation

    def set_colortemp(self, kelvin, duration=0, rapid=False):
        self.color.kelvin = kelvin


class MultiZoneDummy(DummyBulb):
    def __init__(self, color=None, label="N/A", num_zones=8):
        super().__init__(color, label)
        self.zones = [tuple(self.color)] * num_zones
        self.supports_extended_multizone = False

    def supports_multizone(self):
        return True

    def get_color(self):
        return DummyColor(*self.zones[0])

    def get_color_zones(self, start=None, end=None):
        return list(self.zones if start is None else self.zones[start:end])

    def set_color(self, val, duration=0, rapid=False):
        super().set_color(val, duration, rapid)
        if hasattr(self, "zones"):
            self.zones = [tuple(val)] * len(self.zones)

    def set_zone_color(self, start, end, color, duration=0, rapid=False, apply=1):
        for index in range(start, min(end + 1, len(self.zones))):
            self.zones[index] = tuple(color)

    def set_zone_colors(self, colors, duration=0, rapid=False):
        self.zones = [tuple(color) for color in colors]


class TileDummy(DummyBulb):
    pass


class TileChainDummy(DummyBulb):
    def __init__(self, color=DummyColor(0, 0, 0, 1500), label="N/A", x=1, y=1):
        super().__init__(color, label)
        self.tiles = []
        self.cache = []
        self.x = x
        self.y = y

    def get_tile_info(self, refresh_cache=False):
        if refresh_cache:
            self.cache = self.tiles
            return self.tiles
        return self.cache

    def get_tile_count(self, refresh_cache=False):
        if refresh_cache:
            self.cache = self.tiles
            return len(self.tiles)
        return len(self.cache)

    def get_tile_colors(self, start_index, tile_count=0, x=0, y=0, width=0):
        return [
            tile.get_color()
            for tile in self.tiles[start_index : start_index + tile_count]
        ]

    def set_tile_colors(
        self,
        start_index,
        colors,
        duration=0,
        tile_count=0,
        x=0,
        y=0,
        width=0,
        rapid=False,
    ):
        for index, tile in enumerate(
            self.tiles[start_index : start_index + tile_count]
        ):
            tile.set_color(colors[index])

    def get_tilechain_colors(self):
        return [tile.get_color() for tile in self.tiles]

    def set_tilechain_colors(self, tilechain_colors, duration=0, rapid=False):
        for index, tile in enumerate(self.tiles):
            tile.set_color(tilechain_colors[index])

    def project_matrix(self, hsvk_matrix, duration, rapid):
        pass

    def get_canvas_dimensions(self, refresh_cache):
        return self.x, self.y

    def recenter_coordinates(self):
        pass

    def set_tile_coordinates(self, tile_index, x, y):
        pass

    def get_tile_map(self, refresh_cache):
        pass


class LifxLANDummy:
    def __init__(self, verbose=False):
        self.devices = {}

    # Non-offical api to manipulate for testing
    def add_dummy_light(self, light: DummyBulb):
        self.devices[light.get_label()] = light

    # Official api
    def get_devices(self):
        return tuple(self.devices.values())

    def get_lights(self):
        return self.get_devices()

    def get_color_lights(self):
        return tuple(light for light in self.devices.values() if light.supports_color())

    def get_infrared_lights(self):
        return tuple(
            light for light in self.devices.values() if light.supports_infrared()
        )

    def get_multizone_lights(self):
        return tuple(
            light for light in self.devices.values() if light.supports_multizone()
        )

    def get_tilechain_lights(self):
        return tuple(
            light for light in self.devices.values() if type(light) is TileChainDummy
        )

    def get_device_by_name(self, name: str):
        return self.devices[name]

    def get_devices_by_names(self, names: Iterable[str]):
        return Group(
            [light for light in self.devices.values() if light.get_label() in names]
        )

    def get_devices_by_group(self, group_id):
        return Group(
            [light for light in self.devices.values() if light.get_group() == group_id]
        )

    def get_devices_by_location(self, location: str):
        return Group(
            [
                light
                for light in self.devices.values()
                if light.get_location() == location
            ]
        )

    def set_power_all_lights(self, power, duration=0, rapid=False):
        for light in self.devices.values():
            light.set_power(power)

    def set_color_all_lights(self, color, duration=0, rapid=False):
        for light in self.devices.values():
            light.set_color(color)

    def set_waveform_all_lights(
        self, is_transient, color, period, cycles, duty_cycle, wavform, rapid=False
    ):
        for light in self.devices.values():
            light.set_waveform(
                is_transient, color, period, cycles, duty_cycle, wavform, rapid
            )

    def get_power_all_lights(self):
        return dict([((light, light.get_power()) for light in self.devices.values())])

    def get_color_all_lights(self):
        return dict([((light, light.get_color()) for light in self.devices.values())])


class DummyGroup:
    def __init__(self, devices: list, label: str = "N/A"):
        self.devices = devices
        self.label = label

    def __iter__(self):
        return iter(self.devices)

    def add_device(self, device: DummyDevice):
        self.devices.append(device)

    def remove_device(self, device: DummyDevice):
        self.devices.remove(device)

    def remove_device_by_name(self, device_name: str):
        for index, device in enumerate(self.devices):
            if device.get_label() == device_name:
                del self.devices[index]
                break

    def get_device_list(self):
        return self.devices

    def set_power(self, power, duration=0, rapid=False):
        for device in self.devices:
            device.set_power(power, duration, rapid)

    def set_color(self, color, duration=0, rapid=False):
        for device in self.devices:
            device.set_color(color, duration, rapid)

    def set_hue(self, hue, duration=0, rapid=False):
        for device in self.devices:
            device.set_hue(hue, duration, rapid)

    def set_brightness(self, brightness, duration=0, rapid=False):
        for device in self.devices:
            device.set_brightness(brightness, duration, rapid)

    def set_saturation(self, saturation, duration=0, rapid=False):
        for device in self.devices:
            device.set_hue(saturation, duration, rapid)

    def set_colortemp(self, kelvin, duration=0, rapid=False):
        for device in self.devices:
            device.set_hue(kelvin, duration, rapid)

    def set_infrared(self, infrared, duration=0, rapid=False):
        for device in self.devices:
            device.set_hue(infrared, duration, rapid)

    def set_zone_color(self, start, end, color, duration=0, rapid=False, apply=1):
        for device in self.devices[start:end]:
            device.set_color(color, duration, rapid)

    def set_zone_colors(self, colors, duration=0, rapid=False):
        for index, device in enumerate(self.devices):
            device.set_color(colors[index], duration, rapid)


def main():
    """Run a strictly offline demo with ten simulated lights."""
    from lifx_control_panel.__main__ import main as start_app

    lifx = LifxLANDummy()
    for label in (
        "A Light",
        "B Light",
        "C Light",
        "D Light",
        "E Light",
        "F Light",
        "G Light",
        "H Light",
        "I Light",
        "J Light",
    ):
        lifx.add_dummy_light(DummyBulb(label=label))
    lifx.add_dummy_light(MultiZoneDummy(label="Demo Strip", num_zones=16))
    start_app(lifx_instance=lifx)


if __name__ == "__main__":
    main()
