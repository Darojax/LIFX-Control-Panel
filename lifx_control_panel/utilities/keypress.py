# -*- coding: utf-8 -*-
"""Keyboard shortcut interface

Contains single class for interfacing with user IO and binding to functions
"""

import logging

import keyboard


class KeybindManager:
    """Interface with Mouse/Keyboard and register functions to keyboard shortcuts."""

    def __init__(self, master, sticky=False):
        self.logger = logging.getLogger(master.logger.name + ".Keystroke_Watcher")
        self.keys_held = set()
        self.sticky = sticky
        self.hooks = {}
        self._active_hooks = {}
        self._key_hooks = []
        self._running = False
        self.restart()

    @property
    def key_combo_code(self) -> str:
        """Converts the keys currently being held into a string representing the combination"""
        return "+".join(sorted(self.keys_held))

    def register_function(self, key_combo, function):
        """Register function callback to key_combo"""
        keyboard.parse_hotkey(key_combo)
        self.unregister_function(key_combo)
        if self._running:
            self._active_hooks[key_combo] = keyboard.add_hotkey(key_combo, function)
        self.hooks[key_combo] = function
        self.logger.info(
            "Registered function <%s> to keycombo <%s>.",
            function.__name__,
            key_combo.lower(),
        )

    def unregister_function(self, key_combo):
        """Stop tracking function at key_combo"""
        handle = self._active_hooks.pop(key_combo, None)
        if handle is not None:
            keyboard.remove_hotkey(handle)
        self.hooks.pop(key_combo, None)
        self.logger.info(
            "Unregistered function at keycombo <%s>",
            key_combo.lower(),
        )

    def _on_key_down(self, event: keyboard.KeyboardEvent):
        """Simply adds the key to keys held."""
        try:
            self.keys_held.add(event.name)
        except Exception as exc:
            self.logger.error("Error in _on_key_down, %s", exc)
        return True

    def _on_key_up(self, event: keyboard.KeyboardEvent):
        """If a function for the given key_combo is found, call it"""
        if not self.sticky and event.name in self.keys_held:
            self.keys_held.discard(event.name)

    def shutdown(self):
        """Suspend only this manager's hooks, retaining the original callbacks."""
        self._running = False
        for handle in self._active_hooks.values():
            keyboard.remove_hotkey(handle)
        self._active_hooks.clear()
        for handle in self._key_hooks:
            keyboard.unhook(handle)
        self._key_hooks.clear()
        self.keys_held.clear()

    def restart(self):
        """Restore callbacks rather than registering their old removal functions."""
        self.shutdown()
        self._running = True
        self._key_hooks = [
            keyboard.on_press(self._on_key_down),
            keyboard.on_release(self._on_key_up),
        ]
        for keycombo, callback in self.hooks.items():
            self._active_hooks[keycombo] = keyboard.add_hotkey(keycombo, callback)
