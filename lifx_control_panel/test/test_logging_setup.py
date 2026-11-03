"""Diagnostic logging stays opt-in and bounded, including UTF-8 and old files."""

import logging
from pathlib import Path
import tempfile
import unittest

from lifx_control_panel.utilities.logging_setup import configure_logging, MAX_LOG_BYTES


class DiagnosticLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "lifx-control-panel.log"
        self.logger = logging.getLogger(self.id())
        self.logger.propagate = False
        self.addCleanup(self.close_handlers)

    def close_handlers(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()

    def configure(self, enabled):
        return configure_logging(
            self.path, diagnostics=enabled, console=False, logger=self.logger
        )

    def test_normal_use_does_not_create_a_log_file(self):
        configure_logging(self.path, console=False, logger=self.logger)
        self.logger.debug("Routine effect update")
        self.logger.error("An error is still not permission to write a file")
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_rotation_bounds_utf8_and_oversized_records(self):
        self.configure(True)
        for _ in range(600):
            self.logger.debug("\u00e9" * 3000)
        self.logger.error("\u2728" * 32768)
        files = list(self.path.parent.iterdir())
        self.assertEqual(
            {path.name for path in files}, {self.path.name, self.path.name + ".1"}
        )
        self.assertTrue(all(path.stat().st_size <= MAX_LOG_BYTES for path in files))
        self.assertIn("[truncated]", self.path.read_text(encoding="utf-8"))

    def test_disabling_stops_writes_and_reconfiguration_does_not_duplicate_handlers(
        self,
    ):
        self.configure(True)
        self.logger.info("Enabled")
        before = self.path.read_bytes()
        for _ in range(3):
            self.configure(False)
        self.logger.error("Disabled")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.logger.handlers), 1)

    def test_enabling_applies_the_limit_to_oversized_legacy_logs(self):
        self.path.write_bytes(b"x" * (MAX_LOG_BYTES + 100))
        backup = Path(str(self.path) + ".1")
        backup.write_bytes(b"y" * (MAX_LOG_BYTES + 200))
        self.configure(True)
        self.assertEqual(self.path.stat().st_size, MAX_LOG_BYTES)
        self.assertEqual(backup.stat().st_size, MAX_LOG_BYTES)
        self.logger.info("New diagnostic record")
        self.assertTrue(
            all(
                path.stat().st_size <= MAX_LOG_BYTES
                for path in self.path.parent.iterdir()
            )
        )
