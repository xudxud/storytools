# SPDX-License-Identifier: GPL-3.0-or-later

"""Debounced synchronization of user keymaps with the viewport preset buttons.

Keymap operator properties and shortcut events do not share a reliable RNA
update callback. Compare small, immutable snapshots rather than retaining RNA
references, which Blender may replace when rebuilding the user keyconfig.
"""

from dataclasses import dataclass
from time import monotonic

import bpy
from bpy.app.handlers import persistent

from . import fn
from .prefs_io_core import is_restoring, set_class_registered


CHECK_INTERVAL = 0.15
DEBOUNCE_SECONDS = 0.25
_snapshot = None
_pending = None
_changed_at = 0.0


@dataclass(frozen=True)
class PresetEntry:
    key: tuple
    signature: tuple
    active: bool
    show: bool
    icon: str
    description: str
    shortcut: str
    event: tuple


def capture_presets():
    from .gizmo_toolpreset_bar import preset_signature
    event_props = ('map_type', 'type', 'value', 'any', 'shift', 'ctrl', 'alt',
                   'oskey', 'key_modifier', 'direction', 'repeat')
    return tuple(PresetEntry(
        (km.name, kmi.id), preset_signature(kmi.properties), kmi.active,
        kmi.properties.show, kmi.properties.icon, kmi.properties.description,
        kmi.to_string(), tuple(getattr(kmi, name) for name in event_props))
        for km, kmi in fn.get_tool_presets_keymap())


def signature_remap(before, after):
    """Keep cosmetic edits attached to their item; invalidate changed behavior."""
    by_key = {entry.key: entry for entry in after}
    visible_signatures = {entry.signature for entry in after if entry.active and entry.show}
    candidates = {}
    for old in before:
        new = by_key.get(old.key)
        signature = None
        if new is not None:
            if new.active and new.show and new.signature[2:] == old.signature[2:]:
                signature = new.signature
        elif old.signature in visible_signatures:
            # A user-keyconfig rebuild can change item IDs without changing values.
            signature = old.signature
        candidates.setdefault(old.signature, set()).add(signature)
    return {old: next(iter(values)) if len(values) == 1 else None
            for old, values in candidates.items()}


def _apply_snapshot(current):
    global _snapshot, _pending
    from . import gizmo_toolpreset_bar, preset_undo
    if _snapshot is not None:
        remap = signature_remap(_snapshot, current)
        for window, (signature, state) in list(gizmo_toolpreset_bar._activated_presets.items()):
            updated = remap.get(signature, signature)
            if updated is None:
                gizmo_toolpreset_bar._activated_presets.pop(window, None)
            else:
                gizmo_toolpreset_bar._activated_presets[window] = (updated, state)
        preset_undo.remap_signatures(remap)

    _snapshot = _pending = current
    if fn.get_addon_prefs().active_presetbar:
        set_class_registered(gizmo_toolpreset_bar.STORYTOOLS_GGT_toolpreset_bar, False)
        for cls in gizmo_toolpreset_bar.classes:
            set_class_registered(cls, True)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def refresh_now():
    """Manual refresh and completed imports use the same activation remapping."""
    if not is_restoring():
        _apply_snapshot(capture_presets())


def check_for_changes(now=None):
    global _pending, _changed_at
    if is_restoring():
        return CHECK_INTERVAL
    now = monotonic() if now is None else now
    current = capture_presets()
    if current != _pending:
        _pending = current
        _changed_at = now
    elif current != _snapshot and now - _changed_at >= DEBOUNCE_SECONDS:
        if _snapshot is not None:
            bpy.context.preferences.is_dirty = True
        _apply_snapshot(current)
    return CHECK_INTERVAL


def _watch_presets():
    # Addon preferences may not yet be accessible during startup.
    try:
        fn.get_addon_prefs()
    except KeyError:
        return CHECK_INTERVAL
    return check_for_changes()


def request_refresh():
    if not bpy.app.timers.is_registered(_watch_presets):
        register()


@persistent
def reset_after_load(_dummy):
    global _snapshot, _pending, _changed_at
    _snapshot = _pending = None
    _changed_at = 0.0
    from .gizmo_toolpreset_bar import _activated_presets
    _activated_presets.clear()


def register():
    if not bpy.app.timers.is_registered(_watch_presets):
        bpy.app.timers.register(_watch_presets, first_interval=CHECK_INTERVAL, persistent=True)
    if reset_after_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(reset_after_load)


def unregister():
    if bpy.app.timers.is_registered(_watch_presets):
        bpy.app.timers.unregister(_watch_presets)
    if reset_after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(reset_after_load)
    reset_after_load(None)
