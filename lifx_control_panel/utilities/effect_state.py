"""Temporary, per-light state retained while effects own a light."""

from dataclasses import dataclass
import threading

from .device_actions import capture_state, decode_state, device_key, devices_in


@dataclass(eq=False)
class _Entry:
    device: object
    owner: object
    revision: int = 0
    state: dict | None = None
    restore_owner: object = None


@dataclass(frozen=True)
class EffectLease:
    key: str
    entry: _Entry
    revision: int

    @property
    def device(self):
        return self.entry.device


class EffectMemory:
    """Retain originals through handoffs and retire only completed restores.

    Reservations happen on the UI thread before capture is queued. Network
    reads happen under the same device locks as writes, before an effect starts.
    Revisions prevent delayed capture/restore jobs from retiring a newer session.
    """

    def __init__(self, commands):
        self.commands = commands
        self._lock = threading.Lock()
        self._entries = {}

    @staticmethod
    def _lease(key, entry):
        return EffectLease(key, entry, entry.revision)

    def _release(self, key, entry):
        if entry.owner is not None:
            entry.restore_owner = entry.owner
        entry.owner = None
        entry.revision += 1
        return self._lease(key, entry)

    def begin(self, target, owner, stopped_owners):
        """Claim a new effect, retaining originals and releasing unused members."""
        devices = {device_key(device): device for device in devices_in(target)}
        claims, restores = [], []
        stopped = {id(frame) for frame in stopped_owners}
        with self._lock:
            for key, entry in self._entries.items():
                if key not in devices and id(entry.owner) in stopped:
                    restores.append(self._release(key, entry))
            for key, device in devices.items():
                entry = self._entries.setdefault(key, _Entry(device, owner))
                entry.device, entry.owner = device, owner
                entry.restore_owner = None
                entry.revision += 1
                claims.append(self._lease(key, entry))
        return tuple(claims), tuple(restores)

    def release(self, target, stopped_owners, *, discard_target=False):
        """Release stopped effects; a manual change discards its own originals."""
        keys = {device_key(device) for device in devices_in(target)}
        stopped = {id(frame) for frame in stopped_owners}
        restores = []
        with self._lock:
            for key, entry in list(self._entries.items()):
                if discard_target and key in keys:
                    del self._entries[key]
                elif (
                    key in keys
                    or id(entry.owner) in stopped
                    or (not discard_target and id(entry.restore_owner) in stopped)
                ):
                    restores.append(self._release(key, entry))
        return tuple(restores)

    def _current(self, lease):
        return (
            self._entries.get(lease.key) is lease.entry
            and lease.entry.revision == lease.revision
        )

    def current(self, lease):
        with self._lock:
            return self._current(lease)

    def capture(self, claims, ticket):
        """Read missing originals off-thread, without replacing existing ones."""
        for lease in claims:
            if not self.commands.current(ticket):
                return False

            def read(device, claim=lease):
                with self._lock:
                    if (
                        self._entries.get(claim.key) is not claim.entry
                        or claim.entry.state is not None
                    ):
                        return
                state = decode_state(capture_state(device))
                with self._lock:
                    # A handoff can reuse this reservation while the read runs.
                    # A manual override removes it, so an old read cannot re-add it.
                    if (
                        self._entries.get(claim.key) is claim.entry
                        and claim.entry.state is None
                    ):
                        claim.entry.state = state

            self.commands.write(lease.device, read, ticket)
        with self._lock:
            return all(
                self._current(lease) and lease.entry.state is not None
                for lease in claims
            )

    def snapshot(self, lease):
        with self._lock:
            return lease.entry.state if self._current(lease) else None

    def complete(self, lease):
        """Retire an original only when this exact restore is still current."""
        with self._lock:
            if self._current(lease):
                del self._entries[lease.key]
