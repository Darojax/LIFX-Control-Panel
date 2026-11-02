"""Small-frame, stateful lighting analysis for a single movie room lamp.

Hue blends supported illuminated colours; brightness retains scene
exposure and highlight area. This estimates lighting from pixels, not objects.
SDR/sRGB is the working assumption, not a claim of native HDR capture support.
"""

from dataclasses import dataclass
import colorsys
import math
import time

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ActionSettings:
    impact: float = 0.8
    response: float = 0.9
    decay_ms: float = 180


@dataclass(frozen=True)
class Lighting:
    hue: float
    saturation: float
    brightness: float


def _active_picture(rgb):
    """Crop paired, thin near-black bars only when both borders actually end."""
    for axis in (0, 1):
        length = rgb.shape[axis]
        limit = length // 4
        if limit < 3:
            continue
        dark = np.mean(np.max(rgb, axis=2) <= 3 / 255, axis=1 - axis) > 0.985
        before = after = 0
        while before < limit and dark[before]:
            before += 1
        while after < limit and dark[-after - 1]:
            after += 1
        if 2 <= before < limit and 2 <= after < limit and abs(before - after) <= 2:
            rgb = rgb[before:-after] if axis == 0 else rgb[:, before:-after]
    return rgb


def _subtitle_mask(value, saturation):
    """Discount thin, broken white text-shaped rows near the bottom of the image."""
    height, width = value.shape
    mask = np.zeros(value.shape, dtype=bool)
    neutral = (value > 0.65) & (saturation < 0.16)
    candidates = np.zeros(height, dtype=bool)
    for row in range(height * 3 // 4, height):
        pixels = neutral[row]
        fraction = float(pixels.mean())
        starts = np.count_nonzero(pixels & ~np.roll(pixels, 1))
        positions = np.flatnonzero(pixels)
        if (
            0.02 < fraction < 0.45
            and starts >= 4
            and positions[-1] - positions[0] > width * 0.15
        ):
            candidates[row] = True
    start = 0
    while start < height:
        if not candidates[start]:
            start += 1
            continue
        end = start + 1
        while end < height and candidates[end]:
            end += 1
        surround = value[max(0, start - 3) : min(height, end + 3)]
        if (
            end - start <= max(2, height // 14)
            and float((surround < 0.15).mean()) > 0.55
        ):
            mask[start:end] = neutral[start:end]
        start = end
    return mask


def _blend_hues(hues, weights, previous=None):
    """Blend along a short hue arc without cancelling saturated colours to grey."""
    weights = weights / weights.sum()
    offsets = (hues[None, :] - hues[:, None]) % 1
    candidates = (hues + offsets @ weights) % 1
    distances = (hues[None, :] - candidates[:, None] + 0.5) % 1 - 0.5
    errors = distances**2 @ weights
    if previous is None:
        return float(candidates[errors.argmin()])
    # Almost opposite hues admit two plausible paths. Keep the path nearest
    # the previous output rather than flipping across the hue wheel on a tie.
    plausible = candidates[errors <= errors.min() + 0.005]
    return float(plausible[np.abs((plausible - previous + 0.5) % 1 - 0.5).argmin()])


class ActionProcessor:
    """One independent analysis history per effect-worker run."""

    def __init__(self):
        self.previous = None
        self.previous_time = None
        self.previous_frame = None
        self.previous_light_profile = None
        self.highlight_impact = 0.0
        self.light_change = 0.0

    def _update_highlight_impact(self, profile, now):
        """Respond to new light energy and hue changes, not a source's position."""
        dt = (
            max(0.0, min(1.0, now - self.previous_time))
            if self.previous_time is not None
            else 0.0
        )
        novelty = 0.0
        if self.previous_light_profile is not None:
            added = float(np.maximum(profile - self.previous_light_profile, 0).sum())
            scale = max(
                0.01, float(profile.sum()), float(self.previous_light_profile.sum())
            )
            novelty = added / scale * min(1.0, 0.05 / max(0.05, dt))
        # Ignore small histogram fluctuations; pronounced lighting changes get
        # a short boost. An already-lit scene starts at its sustained level.
        attack = max(0.0, min(1.0, (novelty - 0.12) / 0.5))
        self.light_change = novelty
        self.highlight_impact = max(
            attack, self.highlight_impact * math.exp(-dt / 0.18)
        )
        self.previous_light_profile = profile
        return self.highlight_impact

    def analyze(self, image, settings=ActionSettings(), now=None):
        now = time.monotonic() if now is None else now
        impact = max(0.0, min(1.0, settings.impact))
        response = max(0.0, min(1.0, settings.response))
        decay = max(0.05, min(1.0, settings.decay_ms / 1000))
        if image.width < 1 or image.height < 1:
            raise ValueError("Cinema Sync requires a nonempty image")
        # A fixed work budget also prevents a full-resolution colour histogram.
        source = image if image.mode == "RGB" else image.convert("RGB")
        scale = min(1.0, 160 / source.width, 90 / source.height)
        size = (
            max(1, round(source.width * scale)),
            max(1, round(source.height * scale)),
        )
        sample = (
            source.resize(size, Image.Resampling.BOX, reducing_gap=2.0)
            if size != source.size
            else source
        )
        rgb = np.asarray(sample, dtype=np.float32) / 255
        rgb = _active_picture(rgb)
        value = rgb.max(axis=2)
        minimum = rgb.min(axis=2)
        delta = value - minimum
        saturation = np.divide(delta, value, out=np.zeros_like(value), where=value > 0)
        text = _subtitle_mask(value, saturation)
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        luminance = linear @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        energy = 0.5 * luminance + 0.5 * linear.max(axis=2)
        usable = ~text
        samples = energy[usable]
        mean_energy = float(samples.mean()) if samples.size else 0.0

        # A bright region contributes according to its area, never just because
        # it happens to be the brightest pixel in an otherwise dark picture.
        threshold = (
            max(0.04, float(np.quantile(samples, 0.95)) * 0.95) if samples.size else 1.0
        )
        highlights = usable & (energy >= threshold)
        coverage = float(highlights.sum()) / max(1, int(usable.sum()))
        highlight_energy = float(energy[highlights].mean()) if highlights.any() else 0.0
        boost = (
            highlight_energy * coverage**0.6 * (0.5 + 1.5 * impact)
            if coverage >= 0.0025
            else 0.0
        )
        hue = np.zeros_like(value)
        for channel in range(3):
            selected = (rgb[:, :, channel] == value) & (delta > 0)
            numerator = rgb[:, :, (channel + 1) % 3] - rgb[:, :, (channel + 2) % 3]
            hue[selected] = ((numerator[selected] / delta[selected]) + 2 * channel) / 6
        hue %= 1
        bins = (hue * 24).astype(np.int32) % 24
        lit = usable & (value >= 12 / 255)
        # A spatially independent light profile makes a moving headlight count
        # as sustained illumination. Mix neutral and coloured energy smoothly
        # so a slightly warm white does not become a colour-change event.
        profile = np.bincount(
            bins[lit], weights=(energy * saturation)[lit], minlength=24
        )
        profile = (
            profile * 0.5 + np.roll(profile, 1) * 0.25 + np.roll(profile, -1) * 0.25
        )
        profile = np.append(profile, (energy * (1 - saturation))[lit].sum())
        profile /= max(1, int(usable.sum()))
        transient = self._update_highlight_impact(profile, now)
        # Small steady sources keep their colour without lighting the room as
        # if they filled the screen. Broad light keeps its sustained impact;
        # flashes and strong hue changes can briefly use the full boost.
        sustained = min(1.0, coverage / 0.35) ** 1.5
        strength = sustained + (1 - sustained) * transient
        brightness = min(1.0, mean_energy + boost * strength * (1 - mean_energy)) ** 0.7
        if not usable.any() or float(value[usable].max()) < 4 / 255:
            brightness = 0.0
        chromatic = lit & (saturation >= 0.16)
        neutral = lit & ~chromatic
        weights = energy ** (0.8 - impact * 0.2) * (0.35 + 1.3 * saturation)
        counts = np.bincount(bins[chromatic], minlength=24)
        counts = counts + np.roll(counts, 1) + np.roll(counts, -1)
        minimum_support = min(value.size, max(3, int(value.size * 0.0025)))
        chromatic &= counts[bins] >= minimum_support
        scores = np.bincount(bins[chromatic], weights=weights[chromatic], minlength=24)
        neutral_weights = energy[neutral] ** 0.7 * 0.25
        colour_weight = float(scores.sum())
        neutral_weight = float(neutral_weights.sum())
        if colour_weight > 0:
            hue_totals = np.bincount(
                bins[chromatic], weights=(weights * hue)[chromatic], minlength=24
            )
            supported = scores > 0
            target_hue = _blend_hues(
                hue_totals[supported] / scores[supported],
                scores[supported],
                self.previous.hue if self.previous is not None else None,
            )
            target_saturation = float(
                (weights * saturation)[chromatic].sum()
                + (neutral_weights * saturation[neutral]).sum()
            ) / (colour_weight + neutral_weight)
        elif neutral_weight > 0:
            chosen = np.average(linear[neutral], axis=0, weights=neutral_weights)
            encoded = np.where(
                chosen <= 0.0031308, chosen * 12.92, 1.055 * chosen ** (1 / 2.4) - 0.055
            )
            target_hue, target_saturation, _ = colorsys.rgb_to_hsv(*map(float, encoded))
        else:
            target_hue, target_saturation = 0.0, 0.0

        # Fast colour response depends on a sudden image/lighting change, not
        # on the output hue moving far after a dominance threshold is crossed.
        cut = self.previous_frame is not None and (
            self.previous_frame.shape != rgb.shape
            or float(np.abs(rgb - self.previous_frame).mean()) > 0.18
        )
        if brightness == 0 and self.previous is not None:
            target_hue, target_saturation = self.previous.hue, self.previous.saturation
        target = Lighting(target_hue, min(1.0, target_saturation), brightness)

        if self.previous is not None:
            dt = max(0.0, min(1.0, now - self.previous_time))
            hue_distance = (target.hue - self.previous.hue + 0.5) % 1 - 0.5
            fast = cut or self.light_change >= 0.35
            tau = 0.06 + 0.2 * (1 - response) ** 2
            alpha = 1.0 if fast or tau < 0.0001 else -math.expm1(-dt / tau)
            hue_step = hue_distance * alpha
            if not fast:
                # Several evenly balanced colours can admit competing blends.
                # A slow source change must not become a large output jump.
                maximum_step = dt * (1 / 3 + response / 3)
                hue_step = max(-maximum_step, min(maximum_step, hue_step))
            target_hue = (self.previous.hue + hue_step) % 1
            target_saturation = (
                self.previous.saturation
                + (target.saturation - self.previous.saturation) * alpha
            )
            tau = (
                0.15 * (1 - response) ** 2
                if target.brightness >= self.previous.brightness
                else min(decay, 0.12) if target.brightness == 0 else decay
            )
            alpha = 1.0 if tau < 0.0001 else -math.expm1(-dt / tau)
            brightness = (
                self.previous.brightness
                + (target.brightness - self.previous.brightness) * alpha
            )
            if target.brightness == 0 and brightness < 0.005:
                brightness = 0.0
            target = Lighting(target_hue, target_saturation, brightness)
        self.previous = target
        self.previous_time = now
        self.previous_frame = rgb.copy()
        return target
