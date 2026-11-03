"""Opt-in diagnostic files with bounded records, rotation and owned handlers."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

MAX_LOG_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 8192


class _BoundedFormatter(logging.Formatter):
    def format(self, record):
        encoded = super().format(record).encode("utf-8", errors="replace")
        if len(encoded) > MAX_RECORD_BYTES:
            encoded = encoded[: MAX_RECORD_BYTES - 20]
            return encoded.decode("utf-8", errors="ignore") + " [truncated]"
        return encoded.decode("utf-8")


class _RotatingLog(RotatingFileHandler):
    def _open(self):
        return open(self.baseFilename, self.mode, encoding="utf-8", newline="\n")

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        size = len((self.format(record) + self.terminator).encode("utf-8"))
        return self.stream.tell() + size > self.maxBytes


class _DiagnosticHandler(logging.Handler):
    _lifx_role = "diagnostics"

    def __init__(self, path):
        super().__init__(logging.DEBUG)
        self.path = Path(path)
        self.sink = None

    def enable(self, enabled):
        self.acquire()
        try:
            if self.sink is not None:
                self.sink.close()
                self.sink = None
            if enabled:
                # Apply the same retention limit to files from older versions.
                for path in (self.path, Path(str(self.path) + ".1")):
                    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
                        with path.open("rb") as source:
                            source.seek(-MAX_LOG_BYTES, 2)
                            tail = source.read()
                        path.write_bytes(tail)
                self.sink = _RotatingLog(
                    self.path,
                    maxBytes=MAX_LOG_BYTES,
                    backupCount=1,
                    encoding="utf-8",
                    delay=True,
                )
                self.sink.setFormatter(
                    _BoundedFormatter(
                        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    )
                )
        finally:
            self.release()

    def emit(self, record):
        # Handler.handle holds our lock, so disabling cannot race a pending
        # write and reopen a file after the user has switched logging off.
        if self.sink is not None:
            self.sink.handle(record)

    def close(self):
        self.enable(False)
        super().close()


def configure_logging(path, diagnostics=False, console=None, logger=None):
    """Normal windowed use creates no file; debug consoles can still show output."""
    logger = logger or logging.getLogger()
    logger.setLevel(logging.DEBUG)
    owned = [handler for handler in logger.handlers if hasattr(handler, "_lifx_role")]
    for handler in owned:
        logger.removeHandler(handler)
        handler.close()
    diagnostic = _DiagnosticHandler(path)
    logger.addHandler(diagnostic)
    if console is None:
        console = sys.stderr is not None
    if console:
        stream = logging.StreamHandler()
        stream._lifx_role = "console"
        stream.setLevel(logging.DEBUG)
        stream.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        logger.addHandler(stream)
    try:
        diagnostic.enable(diagnostics)
    except OSError:
        # An unavailable optional log destination must never prevent startup.
        logger.warning("Diagnostic file logging could not be enabled", exc_info=True)
    return logger
