"""Movie-lighting regressions use synthetic frames and never control real lights."""

import logging
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from lifx_control_panel.utilities.action_sync import ActionProcessor, ActionSettings
from lifx_control_panel.utilities import color_thread as effects
from lifx_control_panel.ui import settings
from lifx_control_panel.test.test_maintenance import TkFixture


def night_sign():
    image = Image.new("RGB", (160, 90), (5, 5, 5))
    ImageDraw.Draw(image).rectangle((65, 35, 94, 49), fill=(255, 20, 5))
    return image


def subtitles(image):
    image = image.copy()
    draw = ImageDraw.Draw(image)
    for x in range(30, 126, 7):
        draw.rectangle((x, 76, x + 2, 79), fill="white")
    return image


def small_light(colour, left=65):
    image = Image.new("RGB", (160, 90), (5, 5, 5))
    ImageDraw.Draw(image).rectangle((left, 35, left + 29, 49), fill=colour)
    return image


class ActionAnalysisTests(unittest.TestCase):
    def analyze(self, image):
        return ActionProcessor().analyze(image, now=0)

    def test_neon_sign_survives_dark_majority_without_daylight_brightness(self):
        result = self.analyze(night_sign())
        self.assertLess(result.hue, 0.04)
        self.assertGreater(result.saturation, 0.8)
        self.assertGreater(result.brightness, 0.04)
        self.assertLess(result.brightness, 0.15)

    def test_opposing_saturated_colours_do_not_blend_to_grey(self):
        image = Image.new("RGB", (160, 90), "red")
        ImageDraw.Draw(image).rectangle((80, 0, 159, 89), fill="blue")
        self.assertGreater(self.analyze(image).saturation, 0.95)

    def test_blue_to_red_reveal_moves_progressively_through_colour(self):
        processor = ActionProcessor()
        results = []
        for index, width in enumerate(range(0, 161, 4)):
            image = Image.new("RGB", (160, 90), (90, 160, 240))
            if width:
                ImageDraw.Draw(image).rectangle((160 - width, 0, 159, 89), fill="red")
            results.append(processor.analyze(image, now=index * 0.05))
        changes = [
            (b.hue - a.hue + 0.5) % 1 - 0.5 for a, b in zip(results, results[1:])
        ]
        self.assertLess(max(abs(change) for change in changes), 0.04)
        self.assertGreater(min(changes), -0.002)
        self.assertGreater(sum(changes), 0.35)
        self.assertGreater(len({round(result.hue, 2) for result in results}), 15)
        self.assertLess(min(results[-1].hue, 1 - results[-1].hue), 0.02)

    def test_complementary_reveal_and_reverse_stay_smooth_and_saturated(self):
        processor = ActionProcessor()
        results = []
        widths = list(range(0, 161, 4)) + list(range(160, -1, -4))
        for index, width in enumerate(widths):
            image = Image.new("RGB", (160, 90), "cyan")
            if width:
                ImageDraw.Draw(image).rectangle((160 - width, 0, 159, 89), fill="red")
            results.append(processor.analyze(image, now=index * 0.05))
        changes = [
            (b.hue - a.hue + 0.5) % 1 - 0.5 for a, b in zip(results, results[1:])
        ]
        self.assertLess(max(abs(change) for change in changes), 0.04)
        self.assertTrue(all(result.saturation > 0.95 for result in results))
        self.assertLess(abs(results[-1].hue - 0.5), 0.02)

    def test_white_reveal_desaturates_progressively(self):
        processor = ActionProcessor()
        saturations = []
        for index, width in enumerate(range(0, 161, 4)):
            image = Image.new("RGB", (160, 90), "blue")
            if width:
                ImageDraw.Draw(image).rectangle((160 - width, 0, 159, 89), fill="white")
            saturations.append(processor.analyze(image, now=index * 0.05).saturation)
        self.assertLess(
            max(abs(b - a) for a, b in zip(saturations, saturations[1:])), 0.25
        )
        self.assertGreater(len({round(value, 2) for value in saturations}), 12)
        self.assertLess(saturations[-1], 0.1)

    def test_three_colour_reveal_does_not_create_large_output_jumps(self):
        processor = ActionProcessor()
        results = []
        for index, width in enumerate(range(0, 129, 2)):
            image = Image.new("RGB", (160, 90), "blue")
            draw = ImageDraw.Draw(image)
            draw.rectangle((128, 0, 159, 89), fill="lime")
            if width:
                draw.rectangle((0, 0, width - 1, 89), fill="red")
            results.append(processor.analyze(image, now=index * 0.05))
        changes = [
            (b.hue - a.hue + 0.5) % 1 - 0.5 for a, b in zip(results, results[1:])
        ]
        self.assertLess(max(abs(change) for change in changes), 0.04)

    def test_nearly_complementary_colours_do_not_flip_between_hue_paths(self):
        processor = ActionProcessor()
        results = []
        for index in range(40):
            image = Image.new("RGB", (160, 90), (0, 255, 250 if index % 2 else 255))
            ImageDraw.Draw(image).rectangle((80, 0, 159, 89), fill="red")
            results.append(processor.analyze(image, now=index * 0.05))
        changes = [
            (b.hue - a.hue + 0.5) % 1 - 0.5 for a, b in zip(results, results[1:])
        ]
        self.assertLess(max(abs(change) for change in changes), 0.01)
        self.assertTrue(all(result.saturation > 0.95 for result in results))

    def test_neutral_scenes_stay_neutral_and_exposure_is_not_normalized(self):
        bright = self.analyze(Image.new("RGB", (160, 90), "white"))
        dim = self.analyze(Image.new("RGB", (160, 90), (25, 25, 25)))
        self.assertGreater(bright.brightness, 0.95)
        self.assertLess(dim.brightness, 0.1)
        self.assertLess(bright.saturation, 0.02)
        self.assertLess(dim.saturation, 0.02)

    def test_subtitle_shaped_highlights_do_not_wash_out_neon(self):
        original, text = self.analyze(night_sign()), self.analyze(
            subtitles(night_sign())
        )
        self.assertLess(abs(original.hue - text.hue), 0.01)
        self.assertLess(abs(original.brightness - text.brightness), 0.02)
        self.assertGreater(text.saturation, 0.8)

    def test_small_sustained_headlights_keep_the_room_dim(self):
        processor = ActionProcessor()
        values = [
            processor.analyze(small_light("white"), now=index * 0.05)
            for index in range(60)
        ]
        self.assertTrue(all(0.02 < value.brightness < 0.13 for value in values))
        self.assertTrue(all(value.saturation < 0.02 for value in values))

    def test_moving_headlights_do_not_retrigger_the_flash_boost(self):
        processor = ActionProcessor()
        levels = [
            processor.analyze(
                small_light("white", left=30 + index), now=index * 0.05
            ).brightness
            for index in range(60)
        ]
        self.assertLess(max(levels), 0.13)
        self.assertLess(max(levels) - min(levels), 0.001)

    def test_headlights_appearing_get_a_brief_impact_then_settle(self):
        processor = ActionProcessor()
        processor.analyze(Image.new("RGB", (160, 90), "black"), now=0)
        levels = [
            processor.analyze(small_light("white"), now=(index + 1) * 0.05).brightness
            for index in range(60)
        ]
        self.assertGreater(levels[0], 0.3)
        self.assertLess(levels[-1], 0.13)

    def test_slowly_brightening_headlights_stay_subdued(self):
        processor = ActionProcessor()
        levels = [
            processor.analyze(
                small_light((level, level, level)), now=index * 0.05
            ).brightness
            for index, level in enumerate(range(20, 256, 3))
        ]
        self.assertLess(max(levels), 0.13)

    def test_small_alternating_police_lights_keep_repeated_impacts(self):
        processor = ActionProcessor()
        levels = []
        for index in range(60):
            colour = "red" if (index // 3) % 2 == 0 else "blue"
            result = processor.analyze(small_light(colour), now=index * 0.05)
            self.assertGreater(result.saturation, 0.95)
            self.assertLess(abs(result.hue - (0 if colour == "red" else 2 / 3)), 0.02)
            levels.append(result.brightness)
        steady_headlights = self.analyze(small_light("white")).brightness
        self.assertGreater(max(levels[-12:]), 0.23)
        self.assertGreater(sum(levels[-12:]) / 12, steady_headlights * 1.7)

    def test_small_repeated_white_flashes_keep_their_impact(self):
        processor = ActionProcessor()
        peaks = []
        for index in range(60):
            flashing = index % 6 < 2
            image = (
                small_light("white")
                if flashing
                else Image.new("RGB", (160, 90), "black")
            )
            result = processor.analyze(image, now=index * 0.05)
            if index >= 6 and index % 6 == 0:
                peaks.append(result.brightness)
        self.assertTrue(all(peak > 0.3 for peak in peaks))

    def test_isolated_hot_pixel_does_not_light_the_room(self):
        image = Image.new("RGB", (160, 90), "black")
        image.putpixel((80, 45), (255, 255, 255))
        self.assertLess(self.analyze(image).brightness, 0.01)

    def test_paired_black_bars_do_not_change_solid_scene_output(self):
        plain = Image.new("RGB", (160, 70), (5, 60, 220))
        bars = Image.new("RGB", (160, 90), "black")
        bars.paste(plain, (0, 10))
        a, b = self.analyze(plain), self.analyze(bars)
        self.assertAlmostEqual(a.hue, b.hue, places=5)
        self.assertAlmostEqual(a.brightness, b.brightness, places=5)

    def test_full_black_is_off_and_small_regions_are_supported(self):
        self.assertEqual(self.analyze(Image.new("RGB", (1, 1), "black")).brightness, 0)
        self.assertGreater(
            self.analyze(Image.new("RGB", (1, 1), "white")).brightness, 0.95
        )
        red = self.analyze(Image.new("RGB", (1, 1), "red"))
        self.assertLess(red.hue, 0.02)
        self.assertGreater(red.saturation, 0.95)

    def test_repeated_frame_is_stable(self):
        processor = ActionProcessor()
        results = [
            processor.analyze(night_sign(), now=index * 0.05) for index in range(8)
        ]
        self.assertLess(
            max(result.hue for result in results)
            - min(result.hue for result in results),
            0.0001,
        )
        self.assertLess(
            max(result.brightness for result in results)
            - min(result.brightness for result in results),
            0.0001,
        )

    def test_police_colours_follow_abrupt_changes_on_the_next_frame(self):
        processor = ActionProcessor()
        for index, color in enumerate(("red", "blue", "red", "blue")):
            result = processor.analyze(
                Image.new("RGB", (160, 90), color), now=index * 0.05
            )
            self.assertLess(abs(result.hue - (0 if color == "red" else 2 / 3)), 0.02)
            self.assertGreater(result.saturation, 0.95)

    def test_flash_attacks_fast_and_decay_is_adjustable(self):
        tails = []
        for decay in (50, 600):
            processor = ActionProcessor()
            options = ActionSettings(decay_ms=decay)
            processor.analyze(night_sign(), options, now=0)
            flash = processor.analyze(
                Image.new("RGB", (160, 90), "white"), options, now=0.05
            )
            tails.append(processor.analyze(night_sign(), options, now=0.1).brightness)
            self.assertGreater(flash.brightness, 0.95)
        self.assertGreater(tails[1], tails[0] + 0.2)

    def test_fade_to_black_keeps_the_afterglow_colour_then_turns_off(self):
        processor = ActionProcessor()
        blue = processor.analyze(Image.new("RGB", (160, 90), "blue"), now=0)
        fading = processor.analyze(Image.new("RGB", (160, 90), "black"), now=0.05)
        dark = processor.analyze(Image.new("RGB", (160, 90), "black"), now=0.85)
        self.assertAlmostEqual(fading.hue, blue.hue, places=4)
        self.assertGreater(fading.saturation, 0.9)
        self.assertEqual(dark.brightness, 0)

    def test_impact_changes_highlight_strength(self):
        levels = []
        for impact in (0, 1):
            processor = ActionProcessor()
            options = ActionSettings(impact=impact)
            processor.analyze(Image.new("RGB", (160, 90), "black"), options, now=0)
            levels.append(processor.analyze(night_sign(), options, now=0.05).brightness)
        self.assertGreater(levels[1], levels[0] + 0.05)

    def test_response_changes_rise_time_without_delaying_hard_colour_cuts(self):
        levels = []
        for response in (0, 1):
            processor = ActionProcessor()
            options = ActionSettings(response=response)
            processor.analyze(Image.new("RGB", (160, 90), (20, 20, 20)), options, now=0)
            levels.append(
                processor.analyze(
                    Image.new("RGB", (160, 90), "white"), options, now=0.05
                ).brightness
            )
        self.assertGreater(levels[1], levels[0] + 0.3)


class ActionWorkerTests(unittest.TestCase):
    def setUp(self):
        saved = {
            section: dict(settings.config[section])
            for section in ("AverageColor", "ActionSync")
        }

        def restore():
            for section, values in saved.items():
                settings.config[section].clear()
                settings.config[section].update(values)

        self.addCleanup(restore)
        settings.config["ActionSync"].update(brightness="100", response="90")

    def runner(self, bulb):
        parent = SimpleNamespace(
            logger=logging.getLogger("action-test"),
            get_color_values_hsbk=lambda: [0, 0, 30000, 3500],
        )
        return effects.ColorThreadRunner(
            bulb,
            effects.ActionScreenColor(),
            parent,
            continuous=False,
            func_bounds=lambda: "[0,0,160,90]",
        )

    def test_restart_has_fresh_history_and_short_interpolated_transitions(self):
        settings.config["AverageColor"].update(
            maxbrightness="65535", minbrightnesscutoff="0", brightnessoffset="0"
        )
        bulb = Mock()
        runner = self.runner(bulb)
        with patch.object(
            effects,
            "get_rect_as_image",
            side_effect=[
                Image.new("RGB", (160, 90), "white"),
                Image.new("RGB", (160, 90), "black"),
            ],
        ), patch.object(effects.mss, "mss") as capture:
            for _ in range(2):
                runner.start()
                runner.thread.join(3)
            self.assertEqual(capture.call_count, 2)
        calls = bulb.set_color.call_args_list
        self.assertGreater(calls[0].args[0][2], 60000)
        self.assertEqual(calls[1].args[0][2], 0)
        self.assertEqual(calls[0].kwargs["duration"], 70)
        self.assertEqual(calls[0].args[0][3], 3500)

    def test_existing_cap_and_cutoff_apply_and_offset_does_not_defeat_black(self):
        settings.config["AverageColor"].update(
            maxbrightness="12000", minbrightnesscutoff="0", brightnessoffset="20000"
        )
        for image, expected in (
            (Image.new("RGB", (160, 90), "white"), 12000),
            (Image.new("RGB", (160, 90), "black"), 0),
        ):
            bulb = Mock()
            runner = self.runner(bulb)
            with patch.object(
                effects, "get_rect_as_image", return_value=image
            ), patch.object(effects.mss, "mss"):
                runner.start()
                runner.thread.join(3)
            self.assertEqual(bulb.set_color.call_args.args[0][2], expected)
        settings.config["AverageColor"].update(
            maxbrightness="65535", minbrightnesscutoff="8000", brightnessoffset="0"
        )
        bulb = Mock()
        runner = self.runner(bulb)
        with patch.object(
            effects,
            "get_rect_as_image",
            return_value=Image.new("RGB", (160, 90), (25, 25, 25)),
        ), patch.object(effects.mss, "mss"):
            runner.start()
            runner.thread.join(3)
        self.assertEqual(bulb.set_color.call_args.args[0][2], 0)

    def test_brightness_scales_after_offset_cap_and_cutoff_without_changing_colour(
        self,
    ):
        settings.config["AverageColor"].update(
            maxbrightness="12000", minbrightnesscutoff="8000", brightnessoffset="20000"
        )
        colours = []
        for level, expected in ((100, 12000), (50, 6000), (25, 3000), (0, 0)):
            settings.config["ActionSync"]["brightness"] = str(level)
            bulb = Mock()
            runner = self.runner(bulb)
            with patch.object(
                effects, "get_rect_as_image", return_value=night_sign()
            ), patch.object(effects.mss, "mss"):
                runner.start()
                runner.thread.join(3)
            colour = bulb.set_color.call_args.args[0]
            self.assertEqual(colour[2], expected)
            colours.append((colour[0], colour[1], colour[3]))
        self.assertTrue(all(colour == colours[0] for colour in colours))

    def test_response_keeps_lamp_interpolation_at_every_speed(self):
        settings.config["AverageColor"].update(
            maxbrightness="65535", minbrightnesscutoff="0", brightnessoffset="0"
        )
        for response, duration in ((0, 160), (90, 70), (100, 60)):
            with self.subTest(response=response):
                settings.config["ActionSync"]["response"] = str(response)
                bulb = Mock()
                runner = self.runner(bulb)
                with patch.object(
                    effects,
                    "get_rect_as_image",
                    return_value=Image.new("RGB", (160, 90), "white"),
                ), patch.object(effects.mss, "mss"):
                    runner.start()
                    runner.thread.join(3)
                self.assertEqual(bulb.set_color.call_args.kwargs["duration"], duration)
                # Bright flashes still target full output; interpolation must
                # bridge the update interval rather than send discrete steps.
                self.assertGreater(duration, 50)
                self.assertGreater(bulb.set_color.call_args.args[0][2], 60000)

    def test_running_effect_uses_new_brightness_without_restarting(self):
        settings.config["AverageColor"].update(
            maxbrightness="65535", minbrightnesscutoff="0", brightnessoffset="0"
        )
        first_sent, resume = threading.Event(), threading.Event()
        colours = []

        def send(colour, **kwargs):
            colours.append(tuple(colour))
            if len(colours) == 1:
                first_sent.set()
                if not resume.wait(3):
                    raise TimeoutError("Brightness test did not resume")
            else:
                threading.current_thread().stop()

        bulb = Mock(set_color=send)
        runner = self.runner(bulb)
        runner.continuous = True
        self.addCleanup(runner.stop)
        self.addCleanup(resume.set)
        with patch.object(
            effects,
            "get_rect_as_image",
            return_value=Image.new("RGB", (160, 90), "blue"),
        ), patch.object(effects.mss, "mss") as capture:
            runner.start()
            self.assertTrue(first_sent.wait(3))
            worker = runner.thread
            settings.config["ActionSync"]["brightness"] = "25"
            resume.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertIs(runner.thread, worker)
            capture.assert_called_once()
        self.assertEqual(len(colours), 2)
        self.assertEqual(colours[1][2], round(colours[0][2] * 0.25))
        self.assertEqual(colours[1][:2], colours[0][:2])


class ActionUiTests(TkFixture):
    def setUp(self):
        super().setUp()
        saved = {
            section: dict(settings.config[section])
            for section in settings.config.sections()
        }

        def restore():
            settings.config.clear()
            settings.config.read_dict(saved)

        self.addCleanup(restore)
        settings.config["ActionSync"].update(
            impact="80", response="90", decay_ms="180", brightness="100"
        )

    def make_dialog(self):
        import tkinter

        dialog = settings.SettingsDisplay.__new__(settings.SettingsDisplay)
        tkinter.Toplevel.__init__(dialog, self.master)
        dialog.withdraw()
        dialog.parent = self.master
        body = tkinter.Frame(dialog)
        dialog.body(body)
        return dialog

    def test_action_settings_are_persisted(self):
        dialog = self.make_dialog()
        for key, value in (
            ("impact", 70),
            ("response", 100),
            ("decay_ms", 250),
            ("brightness", 45),
        ):
            dialog.action_controls[key].set(value)
        with patch.object(settings, "save_config") as save:
            self.assertEqual(dialog.validate(), 1)
            save.assert_called_once()
        self.assertEqual(settings.config.getint("ActionSync", "decay_ms"), 250)
        self.assertEqual(settings.config.getint("ActionSync", "impact"), 70)
        self.assertEqual(settings.config.getint("ActionSync", "response"), 100)
        self.assertEqual(settings.config.getint("ActionSync", "brightness"), 45)
        dialog.cancel()
        self.assertEqual(settings.get_action_sync_value("brightness", 100), 45)

    def test_cancel_and_window_destruction_restore_saved_values(self):
        original = dict(settings.config["ActionSync"])
        for close in (lambda dialog: dialog.cancel(), lambda dialog: dialog.destroy()):
            dialog = self.make_dialog()
            dialog.action_controls["brightness"].set(15)
            dialog.action_controls["response"].set(20)
            self.assertEqual(settings.get_action_sync_value("brightness", 100), 15)
            self.assertEqual(settings.get_action_sync_value("response", 90), 20)
            self.assertEqual(dict(settings.config["ActionSync"]), original)
            close(dialog)
            self.assertEqual(settings.get_action_sync_value("brightness", 100), 100)
            self.assertEqual(settings.get_action_sync_value("response", 90), 90)
            self.assertEqual(dict(settings.config["ActionSync"]), original)

    def test_all_sliders_reach_a_running_worker_without_ok_or_restart(self):
        dialog = self.make_dialog()
        settings.config["AverageColor"].update(
            maxbrightness="65535", minbrightnesscutoff="0", brightnessoffset="0"
        )
        original = dict(settings.config["ActionSync"])
        first_sent, resume = threading.Event(), threading.Event()
        colours, durations, analyses = [], [], []

        def send(colour, duration, **kwargs):
            colours.append(tuple(colour))
            durations.append(duration)
            if len(colours) == 1:
                first_sent.set()
                if not resume.wait(3):
                    raise TimeoutError("Slider test did not resume")
            else:
                threading.current_thread().stop()

        original_analyze = ActionProcessor.analyze

        def analyze(processor, image, options, **kwargs):
            analyses.append(options)
            return original_analyze(processor, image, options, **kwargs)

        bulb = Mock(set_color=send)
        parent = SimpleNamespace(
            logger=logging.getLogger("preview-test"),
            get_color_values_hsbk=lambda: [0, 0, 30000, 3500],
        )
        runner = effects.ColorThreadRunner(
            bulb,
            effects.ActionScreenColor(),
            parent,
            func_bounds=lambda: "[0,0,160,90]",
        )
        self.addCleanup(runner.stop)
        self.addCleanup(resume.set)
        with patch.object(
            effects,
            "get_rect_as_image",
            return_value=Image.new("RGB", (160, 90), "white"),
        ), patch.object(effects.mss, "mss") as capture, patch.object(
            ActionProcessor, "analyze", analyze
        ), patch.object(
            settings, "save_config"
        ) as save:
            runner.start()
            self.assertTrue(first_sent.wait(3))
            worker = runner.thread
            for key, value in (
                ("impact", 70),
                ("response", 100),
                ("decay_ms", 250),
                ("brightness", 25),
            ):
                dialog.action_controls[key].set(value)
            resume.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertIs(runner.thread, worker)
            self.assertTrue(dialog.winfo_exists())
            capture.assert_called_once()
            save.assert_not_called()
        self.assertEqual(
            analyses[1], ActionSettings(impact=0.7, response=1, decay_ms=250)
        )
        self.assertEqual(durations, [70, 60])
        self.assertEqual(colours[1][2], round(colours[0][2] * 0.25))
        self.assertEqual(dict(settings.config["ActionSync"]), original)


if __name__ == "__main__":
    unittest.main()
