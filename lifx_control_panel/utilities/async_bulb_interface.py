# -*- coding: utf-8 -*-
import concurrent.futures
import logging
import queue
import threading
from typing import List, Sequence, Union, cast

import lifxlan


class AsyncBulbInterface(threading.Thread):
    """Asynchronous networking layer between LIFX devices and the GUI."""

    def __init__(self, event, heartbeat_ms):
        threading.Thread.__init__(self)

        self.stopped = event

        self.hb_rate = heartbeat_ms

        self.device_list: List[lifxlan.Device] = []
        self.color_queue = {}
        self.color_cache = {}
        self.power_queue = {}
        self.power_cache = {}

        self.logger = logging.getLogger("root")

    def set_device_list(
        self,
        device_list: Sequence[
            Union[lifxlan.Device, lifxlan.Light, lifxlan.MultiZoneLight]
        ],
        states=None,
    ):
        """Set internet device list to passed list of LIFX devices."""
        prefetched = {id(state.device): state for state in states or []}
        for dev in device_list:
            try:
                state = prefetched.get(id(dev))
                label = (
                    state.label if state is not None else getattr(dev, "label", None)
                )
                if label is None:
                    label = dev.get_label()
                self.color_queue[label] = queue.Queue(maxsize=1)
                try:
                    color = (
                        state.color
                        if state is not None
                        else getattr(dev, "color", None)
                    )
                    if (
                        color is not None
                        and len(color)
                        and isinstance(color[0], (list, tuple))
                    ):
                        color = color[0]
                except Exception as e:
                    self.logger.error(e)
                    color = None
                self.color_cache[label] = tuple(color) if color is not None else None
                self.power_queue[label] = queue.Queue(maxsize=1)
                try:
                    power = (
                        state.power
                        if state is not None
                        else getattr(dev, "power_level", None)
                    )
                    self.power_cache[label] = (
                        dev.get_power() if power is None else power
                    )
                except Exception as e:
                    self.logger.error(e)
                    self.power_cache[label] = 0
                self.device_list.append(cast(lifxlan.Device, dev))
            except lifxlan.WorkflowException as exc:
                self.logger.warning(
                    "Error when communicating with LIFX device: %s", exc
                )

    def query_device(self, target):
        """Check if target has new state. If it does, push it to the queue and cache the value."""
        try:
            label = target.label
            pwr = target.get_power()
            if pwr != self.power_cache[label]:
                self._publish_latest(self.power_queue[label], pwr)
                self.power_cache[label] = pwr
            # Poll only the representative colour; full strip palettes are
            # fetched explicitly by discovery, Read zones and saved-state jobs.
            clr = tuple(target.get_color())
            if clr != self.color_cache[label]:
                self._publish_latest(self.color_queue[label], clr)
                self.color_cache[label] = clr
        except lifxlan.WorkflowException:
            pass

    @staticmethod
    def _publish_latest(target_queue, value):
        """Keep the newest state when the GUI is slower than device polling."""
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put_nowait(value)

    def run(self):
        """Continuous loop that has a thread query each device every HEARTBEAT ms."""
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(self.device_list))
        ) as executor:
            while not self.stopped.wait(self.hb_rate / 1000):
                # Consume the batch before scheduling another: slow/offline lights
                # must not accumulate overlapping queries in the executor queue.
                list(executor.map(self.query_device, self.device_list))
