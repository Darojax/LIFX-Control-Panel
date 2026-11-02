# -*- coding: utf-8 -*-
"""Multi-Threaded Color Changer

Contains several basic "Color-Following" functions, as well as custom Stop/Start threads for these effects.
"""

import logging
import sys
import threading
from contextlib import ExitStack
from typing import List, Tuple
import time

import mss
import numpy as np

if sys.platform == "win32":
    import mss.windows

    # CAPTUREBLT can make the cursor flicker during repeated Windows captures.
    # Use the MSS maintainer's workaround for all screen-colour capture paths.
    # Layered/translucent overlays may be omitted from the resulting image.
    # https://github.com/BoboTiG/python-mss/issues/179
    mss.windows.CAPTUREBLT = 0

# from lib.color_functions import dominant_color
from PIL import Image
from lifxlan import utils

from .utils import str2list, Color, get_primary_monitor
from .action_sync import ActionProcessor, ActionSettings
from ..ui.settings import config, get_action_sync_value

from lifx_control_panel.utilities.utils import hsv_to_rgb


def validate_monitor_bounds(monitor):
    """Resolve a saved region and reject invalid dimensions before capture."""
    if isinstance(monitor, str):
        if "full" in monitor.lower():
            if all(
                value.strip().lower() == "full"
                for value in monitor.strip("()[]").split(",")
            ):
                return "full"
            raise ValueError("Use full for every coordinate, or enter four integers.")
        if monitor.startswith("get_primary_monitor"):
            monitor = get_primary_monitor()
        else:
            try:
                monitor = str2list(monitor, int)
            except ValueError as exc:
                raise ValueError("Screen coordinates must be integers.") from exc
    if len(monitor) != 4 or monitor[2] <= 0 or monitor[3] <= 0:
        raise ValueError(
            "Enter left, top, width and height; width and height must be positive."
        )
    return tuple(monitor)


def get_monitor_bounds(func):
    """Read current bounds; caching this used to ignore region edits."""
    return validate_monitor_bounds(func() or config["AverageColor"]["DefaultMonitor"])


def get_screen_as_image(capture=None):
    """Grab all displays, reusing the worker's capture resources when supplied."""
    if capture is None:
        with mss.mss() as capture:
            return get_screen_as_image(capture)
    screenshot = capture.grab(capture.monitors[0])
    return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def get_rect_as_image(bounds: Tuple[int, int, int, int], capture=None):
    """Grab a region, reusing the worker's capture resources when supplied."""
    if capture is None:
        with mss.mss() as capture:
            return get_rect_as_image(bounds, capture)
    monitor = dict(zip(("left", "top", "width", "height"), bounds))
    screenshot = capture.grab(monitor)
    return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def normalize_rectangles(rects: List[Tuple[int, int, int, int]]):
    """Normalize the rectangles to the monitor size"""
    x_min = min(rect[0] for rect in rects)
    y_min = min(rect[1] for rect in rects)
    return [
        (
            -x_min + left,
            -y_min + top,
            -x_min + right,
            -y_min + bottom,
        )
        for left, top, right, bottom in rects
    ]


class ColorCycle:
    def __init__(self):
        self.initial_color = Color(255, 0, 0, 0)
        self.last_change = time.time()
        self.pos = 0
        self.cycle_color = hsv_to_rgb(self.pos, 1, 1)

    def get_color(self, *args, **kwargs):
        if time.time() - self.last_change > 0.1:
            self.pos = (self.pos + 1) % 360
            self.cycle_color = hsv_to_rgb(self.pos, 1, self.initial_color[2] / 65535)
            self.last_change = time.time()
        return list(
            utils.RGBtoHSBK(self.cycle_color, temperature=self.initial_color[3])
        )

    def __call__(self, initial_color):
        self.initial_color = initial_color
        return self.get_color()

    def __name__(self):
        return "ColorCycle"


def screen_rgb_to_hsbk(rgb, temperature):
    """Keep tiny near-black RGB differences from becoming saturated colour noise."""
    color = list(utils.RGBtoHSBK(rgb, temperature=temperature))
    threshold = max(
        0, min(255, config.getint("AverageColor", "nearblackthreshold", fallback=10))
    )
    if max(rgb) < threshold:
        color[1] = 0
    return color


def limit_screen_brightness(brightness):
    """Apply offset first, then the screen-only cap and dark-scene cutoff."""
    maximum = max(
        0, min(65535, config.getint("AverageColor", "maxbrightness", fallback=65535))
    )
    cutoff = max(
        0,
        min(maximum, config.getint("AverageColor", "minbrightnesscutoff", fallback=0)),
    )
    brightness = max(0, min(maximum, brightness))
    return 0 if brightness < cutoff else brightness


def avg_screen_color(initial_color, func_bounds=lambda: None, capture=None):
    """Capture an image of the monitor defined by func_bounds, then get the average color of the image in HSBK"""
    monitor = get_monitor_bounds(func_bounds)
    if monitor == "full":
        screenshot = get_screen_as_image(capture)
    else:
        screenshot = get_rect_as_image(monitor, capture)
    # Resizing the image to 1x1 pixel will give us the average for the whole image (via HAMMING interpolation)
    color = screenshot.resize((1, 1), Image.Resampling.HAMMING).getpixel((0, 0))
    return screen_rgb_to_hsbk(color, initial_color[3])


def dominant_screen_color(initial_color, func_bounds=lambda: None, capture=None):
    """
    Gets the dominant color of the screen defined by func_bounds
    https://stackoverflow.com/questions/50899692/most-dominant-color-in-rgb-image-opencv-numpy-python
    """
    monitor = get_monitor_bounds(func_bounds)
    if monitor == "full":
        screenshot = get_screen_as_image(capture)
    else:
        screenshot = get_rect_as_image(monitor, capture)

    downscale_width, downscale_height = max(1, screenshot.width // 4), max(
        1, screenshot.height // 4
    )
    screenshot = screenshot.resize(
        (downscale_width, downscale_height), Image.Resampling.HAMMING
    )

    a = np.array(screenshot)
    a2D = a.reshape(-1, a.shape[-1]).astype(np.int32)
    # Count only colours present, rather than allocating up to 16 million bins
    # (about 128 MiB) on every capture, even for a single white pixel.
    colors, counts = np.unique(a2D, axis=0, return_counts=True)
    color = tuple(int(channel) for channel in colors[counts.argmax()])

    return screen_rgb_to_hsbk(color, initial_color[3])


class ActionScreenColor:
    __name__ = "CinemaSync"

    def __call__(
        self, initial_color, func_bounds=lambda: None, capture=None, processor=None
    ):
        monitor = get_monitor_bounds(func_bounds)
        image = (
            get_screen_as_image(capture)
            if monitor == "full"
            else get_rect_as_image(monitor, capture)
        )
        settings = ActionSettings(
            get_action_sync_value("impact", 80) / 100,
            get_action_sync_value("response", 90) / 100,
            get_action_sync_value("decay_ms", 180),
        )
        signal = (processor or ActionProcessor()).analyze(image, settings)
        return [
            round(signal.hue * 65535),
            round(signal.saturation * 65535),
            round(signal.brightness * 65535),
            initial_color[3],
        ]


def is_screen_effect(function):
    return function in (avg_screen_color, dominant_screen_color) or isinstance(
        function, ActionScreenColor
    )


class ColorThread(threading.Thread):
    """A Simple Thread which runs when the _stop event isn't set"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, daemon=True, **kwargs)
        self._stop_event = threading.Event()

    def stop(self):
        """Stop thread by setting event"""
        self._stop_event.set()

    def stopped(self):
        """Check if thread has been stopped"""
        return self._stop_event.is_set()


class ColorThreadRunner:
    """Manages an asynchronous color-change with a Device. Can be run continuously, stopped and started."""

    def __init__(self, bulb, color_function, parent, continuous=True, **kwargs):
        self.bulb = bulb
        self.color_function = color_function
        self.kwargs = kwargs
        self.parent = parent  # couple to parent frame
        self.logger = logging.getLogger(
            parent.logger.name + f".Thread({color_function.__name__})"
        )
        self.prev_color = parent.get_color_values_hsbk()
        self.continuous = continuous
        self._state_lock = threading.Lock()
        self.thread = ColorThread(target=self.match_color, args=(self.bulb,))
        label = getattr(parent, "label", None) or "<LABEL-ERR>"
        self.logger.info(
            "Initialized Thread: Bulb: %s // Continuous: %s", label, self.continuous
        )

    def match_color(self, bulb, initial_color, effect_kwargs, ticket=None):
        """Calculate off-thread; Tk values are snapshotted by start()."""
        worker = threading.current_thread()
        prev_color = initial_color
        self.logger.debug("Starting color match.")
        try:
            with ExitStack() as resources:
                if is_screen_effect(self.color_function):
                    effect_kwargs["capture"] = resources.enter_context(mss.mss())
                while not worker.stopped():
                    started = time.monotonic()
                    try:
                        color = list(
                            self.color_function(
                                initial_color=prev_color, **effect_kwargs
                            )
                        )
                        action = isinstance(self.color_function, ActionScreenColor)
                        offset = (
                            0
                            if action and color[2] == 0
                            else self.get_brightness_offset()
                        )
                        color[2] = max(0, min(color[2] + offset, 65535))
                        if is_screen_effect(self.color_function):
                            color[2] = limit_screen_brightness(color[2])
                        if action:
                            # Scale the final output rather than clip highlights;
                            # the screen cutoff still refers to scene brightness.
                            level = max(
                                0.0,
                                min(
                                    1.0,
                                    get_action_sync_value("brightness", 100) / 100,
                                ),
                            )
                            color[2] = round(color[2] * level)
                        with self._state_lock:
                            if worker is not self.thread or worker.stopped():
                                break
                            gate = getattr(
                                getattr(self.parent, "master", None), "commands", None
                            )

                            def send(device):
                                device.set_color(
                                    color,
                                    duration=(
                                        self.get_action_transition_ms()
                                        if action
                                        else self.get_duration() * 1000
                                    ),
                                    rapid=self.continuous,
                                )

                            if gate is None:
                                send(bulb)
                            else:
                                gate.write(bulb, send, ticket)
                            prev_color = self.prev_color = color
                    except OSError:
                        self.logger.warning("Device/capture temporarily unavailable")
                        worker._stop_event.wait(0.25)
                        continue
                    if not self.continuous:
                        break
                    # LIFX supports about 20 commands/sec. Transition duration
                    # controls bulb interpolation, not how often this loop runs.
                    worker._stop_event.wait(max(0, 0.05 - (time.monotonic() - started)))
        except Exception:
            self.logger.exception("Effect stopped after an error")
        finally:
            worker.stop()
            post_ui = getattr(getattr(self.parent, "master", None), "post_ui", None)
            if post_ui is not None:
                post_ui(lambda: self.parent.effect_finished(self))
            self.logger.debug("Color match finished.")

    def is_running(self):
        return self.thread.is_alive() and not self.thread.stopped()

    def start(self):
        """Snapshot GUI inputs and start one worker; repeated starts are harmless."""
        initial_color = list(self.parent.get_color_values_hsbk())
        effect_kwargs = dict(self.kwargs)
        if "func_bounds" in effect_kwargs:
            bounds = get_monitor_bounds(effect_kwargs["func_bounds"])
            effect_kwargs["func_bounds"] = lambda: bounds
        if isinstance(self.color_function, ActionScreenColor):
            effect_kwargs["processor"] = ActionProcessor()
        with self._state_lock:
            if self.is_running():
                return
            self.thread = ColorThread(
                target=self.match_color,
                args=(
                    self.bulb,
                    initial_color,
                    effect_kwargs,
                    (
                        getattr(
                            getattr(self.parent, "master", None), "commands", None
                        ).ticket(self.bulb)
                        if getattr(
                            getattr(self.parent, "master", None), "commands", None
                        )
                        is not None
                        else None
                    ),
                ),
            )
            self.thread.start()
            self.logger.debug("Thread started.")

    def stop(self):
        """Invalidate pending calculations before allowing another effect to send."""
        with self._state_lock:
            self.thread.stop()

    @staticmethod
    def get_action_transition_ms():
        """Bridge 50 ms target updates with short, responsive lamp-side fades."""
        response = max(0.0, min(1.0, get_action_sync_value("response", 90) / 100))
        # Even the fastest response must interpolate between packets. Longer
        # fades at lower Response soften motion without slowing frame capture.
        return round(60 + 100 * (1 - response))

    @staticmethod
    def get_duration():
        """Read the transition duration from the config file."""
        return float(config["AverageColor"]["duration"])

    @staticmethod
    def get_brightness_offset():
        """Read the brightness offset from the config file."""
        return int(config["AverageColor"]["brightnessoffset"])


# Python's native hook also covers device and zone workers.
threading.excepthook = lambda args: sys.excepthook(
    args.exc_type, args.exc_value, args.exc_traceback
)
