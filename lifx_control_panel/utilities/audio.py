# -*- coding: utf-8 -*-
"""Audio Processing Tools

Tools for real-time audio processing and color-following. For co-use with color_threads.py

Notes
-----
    Not really complete yet; still need to integrate with other screen averaging functions.
"""

from array import array
import sys
import threading
from collections import deque
from math import ceil, isqrt
from tkinter import messagebox

try:
    import pyaudio
except ImportError:
    pyaudio = None


def pcm_rms(data):
    """RMS of little-endian signed 16-bit audio without the removed audioop module."""
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return (
        isqrt(sum(sample * sample for sample in samples) // len(samples))
        if samples
        else 0
    )


# Audio processing constants
CHUNK = 1024
FORMAT = pyaudio.paInt16 if pyaudio is not None else None
CHANNELS = 2
RATE = 44100

# RMS -> Brightness control constants
SCALE = 8  # Change if too dim/bright
EXPONENT = 2  # Change if too little/too much difference between loud and quiet sounds
N_POINTS = 15  # Length of sliding average window for smoothing


class AudioInterface:
    """Instantiate a connection to audio device (selected in Settings). Also provides a color-following function for
    music intensity."""

    def __init__(self):
        self._lock = threading.RLock()
        self.interface = pyaudio.PyAudio() if pyaudio is not None else None
        self.num_devices = 0
        self.device_names = {}
        self.stream = None
        self.initialized = False
        self.window = deque([0] * N_POINTS)

    def init_audio(self, config):
        """Attempt to make a connection to the audio device given in config.ini or Stereo Mix. Will attempt
        to automatically find a Stereo Mix"""
        with self._lock:
            was_initialized = self.initialized
            self._close_stream()
            self.window = deque([0] * N_POINTS)
            try:
                self.init_configured_device(config)
            except (ValueError, OSError) as exc:
                if was_initialized:
                    messagebox.showerror("Invalid Sound Input", exc)
                self.initialized = False

    def _close_stream(self):
        self.initialized = False
        if self.stream is not None:
            try:
                self.stream.stop_stream()
            finally:
                self.stream.close()
                self.stream = None

    def close(self):
        with self._lock:
            self._close_stream()
            if self.interface is not None:
                self.interface.terminate()

    def init_configured_device(self, config):
        if self.interface is None:
            raise OSError("PyAudio is unavailable. Music Color is disabled.")
        # Find input device index
        self.num_devices = self.interface.get_device_count()
        self._refresh_device_names()
        # If a setting is found, use it. Otherwise, try and find Stereo Mix
        if config.has_option("Audio", "InputIndex"):
            input_device_index = int(config["Audio"]["InputIndex"])
        else:
            input_device_index = self.get_stereo_mix_index()
            if input_device_index is not None:
                from ..ui.settings import save_config

                config["Audio"]["InputIndex"] = str(input_device_index)
                save_config()
        if input_device_index is None:
            raise OSError("No Input channel found. Disabling Sound Integration.")
        device_info = self.interface.get_device_info_by_index(input_device_index)
        channels = min(CHANNELS, int(device_info["maxInputChannels"]))
        if channels <= 0:
            raise OSError("Selected device does not support audio input.")
        self.stream = self.interface.open(
            format=FORMAT,
            channels=channels,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
            input_device_index=input_device_index,
        )
        self.initialized = True

    def get_stereo_mix_index(self):
        """Naively get stereo mix, as it's probably the best input"""
        device_index = None
        for index, name in self.get_device_names().items():
            if "stereo mix" in name.lower():
                device_index = index
        return device_index

    def get_device_names(self):
        """Get names of all audio devices"""
        if not self.device_names:
            self._refresh_device_names()
        return dict(self.device_names)

    def _refresh_device_names(self):
        """Cache names of all audio devices to avoid repeated probing."""
        devices = {}
        for i in range(self.num_devices):
            info = self.interface.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices[i] = info["name"]
        self.device_names = devices

    def get_music_color(self, initial_color, alpha=0.99):
        """Calculate the RMS power of the waveform, and return that as the initial_color with the calculated brightness"""
        with self._lock:
            if not self.initialized or self.stream is None:
                raise OSError("Audio input is unavailable.")
            # Drain buffered input so the 20 Hz light updates follow current
            # audio instead of gradually falling behind the input sample rate.
            samples = max(CHUNK, self.stream.get_read_available())
            data = self.stream.read(samples, exception_on_overflow=False)
        frame_rms = pcm_rms(data)
        level = min(frame_rms / (2.0**16) * SCALE, 1.0)
        level = level**EXPONENT
        level = int(level * 65535)
        self.window.rotate(1)  # FILO Queue
        # window = deque([a*x for x in window])  # exp decay
        self.window[0] = level
        brightness = ceil(sum(self.window) / N_POINTS)
        return initial_color[0], initial_color[1], brightness, initial_color[3]
