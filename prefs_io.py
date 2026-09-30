# SPDX-License-Identifier: GPL-3.0-or-later

"""Backup / restore of the Storytools preferences and tool preset shortcuts as JSON

List which properties to skip, which keymap items are "tool presets", side effects to replay after a restore.
Generic RNA <-> json and keymap lives in `prefs_io_core`.

A restore must not trigger the `update=` callbacks. They should all return early while
`prefs_io_core.is_restoring()` is true, and `apply_restored_prefs()` replays the side
effects once afterwards
"""

import json
import bpy

from pathlib import Path

from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import prefs_io_core as core
from .prefs_io_core import restoring, set_class_registered
from .fn import get_addon_prefs
from .preferences import PREFERENCE_UI_PROPS, LEGACY_BAR_PROPS

## Shown in console messages
ADDON_LABEL = 'Storytools'

## Bump for non backward compatible json layout
FORMAT_VERSION = 2

## Pure UI state on top of the generic exclusions, not meaningful to transfer
SKIP_PROPS = core.DEFAULT_SKIP | {'pref_tab'} | PREFERENCE_UI_PROPS | LEGACY_BAR_PROPS

## Tool preset shortcuts are the keymap items running this operator
PRESET_IDNAME = 'storytools.set_draw_tool'

## Draw mode keymap got renamed in 5.1, accept both when restoring
GP_DRAW_KM_ALIASES = ('Grease Pencil Draw Mode', 'Grease Pencil Paint Mode')


# region storytools bindings

def shared_bar_appearance_data(data):
    """Convert old per-bar fields; bottom-bar values win when both were stored."""
    if not isinstance(data, dict):
        return data
    data = dict(data)
    for suffix in ('color', 'opacity'):
        shared = 'bar_background_' + suffix
        bottom = 'toolbar_background_' + suffix
        top = 'presetbar_background_' + suffix
        if shared not in data:
            if bottom in data:
                data[shared] = data[bottom]
            elif top in data:
                data[shared] = data[top]
        data.pop(bottom, None)
        data.pop(top, None)
    return data


def migrate_bar_appearance(prefs):
    """Migrate saved Blender preferences without overwriting new shared values."""
    legacy = {name: getattr(prefs, name) for name in LEGACY_BAR_PROPS
              if prefs.is_property_set(name)}
    migrated = False
    with restoring():
        for name, value in shared_bar_appearance_data(legacy).items():
            if not prefs.is_property_set(name):
                setattr(prefs, name, value)
                migrated = True
        for name in legacy:
            prefs.property_unset(name)
            migrated = True
    if migrated:
        bpy.context.preferences.is_dirty = True


def prefs_to_json(prefs=None):
    """Dump the addon preferences to a json compatible dict"""
    prefs = prefs if prefs is not None else get_addon_prefs()
    migrate_bar_appearance(prefs)
    return core.prop_to_json(prefs, skip=SKIP_PROPS)


def json_to_prefs(data, prefs=None, log=None):
    """Apply a preferences dict, must run inside `restoring()`"""
    prefs = prefs if prefs is not None else get_addon_prefs()
    return core.json_to_prop(prefs, shared_bar_appearance_data(data),
                             path='preferences', log=log, skip=SKIP_PROPS)


def tool_presets_to_json():
    """Dump the tool preset shortcuts of the user keyconfig"""
    return core.keymap_items_to_json(PRESET_IDNAME, km_aliases=GP_DRAW_KM_ALIASES)


def reset_tool_presets():
    """Bring tool preset shortcuts back to the addon defaults"""
    core.reset_keymap_items(PRESET_IDNAME, label=ADDON_LABEL)


def json_to_tool_presets(data, log=None):
    """Replace all tool preset shortcuts with the ones stored in `data`"""
    return core.json_to_keymap_items(data, PRESET_IDNAME, km_aliases=GP_DRAW_KM_ALIASES,
                                     log=log, label=ADDON_LABEL)


# region side effects

def sync_gizmo_registration(prefs):
    """Register/unregister the gizmo groups to match the preference booleans"""
    from . import gizmo_toolbar, gizmo_toolpreset_bar

    toolbar_classes = (
        gizmo_toolbar.classes
        if bpy.app.version >= (5, 2, 0)
        else (gizmo_toolbar.STORYTOOLS_GGT_toolbar,
              gizmo_toolbar.STORYTOOLS_GGT_toolbar_switch)
    )
    targets = (
        (prefs.active_toolbar, toolbar_classes),
        (prefs.active_presetbar, gizmo_toolpreset_bar.classes),
    )

    for enabled, classes in targets:
        ordered_classes = classes if enabled else reversed(classes)
        for cls in ordered_classes:
            set_class_registered(cls, enabled)


def apply_restored_prefs(prefs):
    """Re-apply everything the suppressed `update=` callbacks would have done
    Must be called after the `restoring()` context has exited"""
    from .ui import register_panels, unregister_panels
    from .preferences import replicate_preference_settings

    ## Sidebar panels (visibility + category name)
    unregister_panels()
    if prefs.show_sidebar_ui:
        register_panels(prefs.category.strip())

    ## Viewport gizmo bars
    sync_gizmo_registration(prefs)

    ## Rebuild from the final keymap, including activation / undo remapping
    from .preset_refresh import refresh_now
    refresh_now()

    ## Push gp settings to the scenes set on global sync
    replicate_preference_settings(None)


# region operators

class STORYTOOLS_OT_export_preferences(bpy.types.Operator, ExportHelper):
    bl_idname = "storytools.export_preferences"
    bl_label = "Backup Preferences"
    bl_description = "Save all Storytools preferences (including layer/material stacks\
                    \nand Tool preset shortcuts) to a json file"
    bl_options = {"REGISTER", "INTERNAL"}

    filename_ext = '.json'

    filter_glob : StringProperty(default='*.json', options={'HIDDEN'})

    use_tool_presets : BoolProperty(
        name='Include Tool Presets',
        description="Also store the tool preset shortcuts (keymap items)",
        default=True)

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = 'storytools_preferences.json'
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        data = {
            'format_version': FORMAT_VERSION,
            'addon_version': core.get_addon_version(__package__),
            'blender_version': list(bpy.app.version),
            'preferences': prefs_to_json(),
        }

        if self.use_tool_presets:
            data['tool_presets'] = tool_presets_to_json()

        filepath = Path(self.filepath)
        if filepath.suffix.lower() != '.json':
            filepath = filepath.with_suffix('.json')

        try:
            filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        except OSError as e:
            self.report({'ERROR'}, f'Could not write file: {e}')
            return {'CANCELLED'}

        self.report({'INFO'}, f'Preferences saved: {filepath.name}')
        return {'FINISHED'}


class STORYTOOLS_OT_import_preferences(bpy.types.Operator, ImportHelper):
    bl_idname = "storytools.import_preferences"
    bl_label = "Restore Preferences"
    bl_description = "Replace all Storytools preferences with the content of a json backup\
                    \nCurrent preferences are overwritten"
    bl_options = {"REGISTER", "INTERNAL"}

    filename_ext = '.json'

    filter_glob : StringProperty(default='*.json', options={'HIDDEN'})

    use_tool_presets : BoolProperty(
        name='Restore Tool Presets',
        description="Also replace the tool preset shortcuts stored in the backup\
            \nExisting custom presets are removed, modified default ones are reset",
        default=True)

    def execute(self, context):
        filepath = Path(self.filepath)
        if not filepath.is_file():
            self.report({'ERROR'}, f'File not found: {filepath}')
            return {'CANCELLED'}

        try:
            data = json.loads(filepath.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as e:
            self.report({'ERROR'}, f'Could not read json: {e}')
            return {'CANCELLED'}

        if not isinstance(data, dict) or 'preferences' not in data:
            self.report({'ERROR'}, 'Not a Storytools preferences backup')
            return {'CANCELLED'}

        version = data.get('format_version', 0)
        if version > FORMAT_VERSION:
            self.report({'WARNING'},
                        f'Backup was made with a newer format (v{version}), some settings may be skipped')

        prefs = get_addon_prefs()

        ## Suppress every `update=` callback while writing, replayed once below
        with restoring():
            log = json_to_prefs(data['preferences'], prefs=prefs)

            if self.use_tool_presets and 'tool_presets' in data:
                json_to_tool_presets(data['tool_presets'], log=log)

            ## Stacks must never end up empty (they would be re-seeded on next load)
            from .preferences import seed_default_stacks
            seed_default_stacks(prefs)

        apply_restored_prefs(prefs)

        context.preferences.is_dirty = True

        skipped = core.log_report(log, f'Restore from {filepath.name}', label=ADDON_LABEL)
        if skipped:
            self.report({'WARNING'},
                        f'Preferences restored, {skipped} entrie(s) skipped (see console)')
        else:
            self.report({'INFO'}, f'Preferences restored from {filepath.name}')
        return {'FINISHED'}


# region register

classes = (
    STORYTOOLS_OT_export_preferences,
    STORYTOOLS_OT_import_preferences,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
