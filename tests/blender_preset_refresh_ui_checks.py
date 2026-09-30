"""Foreground integration check: real timer, keyconfig rebuilds and drawn gizmos.

Run Blender --factory-startup --python-exit-code 1 --python this_file.
This uses factory preferences, exercises the addon, then closes the test window.
"""
import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
addon = importlib.import_module(root.name)
entry = bpy.context.preferences.addons.new()
entry.module = addon.__name__
drawn = []
backgrounds = {}
original_prepare = addon.gizmo_toolpreset_bar.STORYTOOLS_GGT_toolpreset_bar.draw_prepare

def record_prepare(self, context):
    original_prepare(self, context)
    drawn[:] = [(props.name, props.icon, props.description) for props in self.tool_preset_props]

addon.gizmo_toolpreset_bar.STORYTOOLS_GGT_toolpreset_bar.draw_prepare = record_prepare
original_capsule = addon.gizmo_toolpreset_bar.draw_capsule

def top_background(context, center, width, height, opacity=0.3, color=(0.0, 0.0, 0.0)):
    backgrounds['top'] = (opacity, tuple(color))
    original_capsule(context, center, width, height, opacity, color)

def bottom_background(context, center, width, height, opacity=0.3, color=(0.0, 0.0, 0.0)):
    backgrounds['bottom'] = (opacity, tuple(color))
    original_capsule(context, center, width, height, opacity, color)

addon.gizmo_toolpreset_bar.draw_capsule = top_background
addon.gizmo_toolbar.draw_capsule = bottom_background
addon.register()
prefs = entry.preferences
prefs.toolbar_background_opacity = 0.34
prefs.presetbar_background_opacity = 0.85
prefs.toolbar_background_color = (0.1, 0.2, 0.3)
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.use_save_prompt = False
area = max((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(area=area, region=region):
    bpy.ops.object.grease_pencil_add(type='EMPTY')
phase = 0

def find_preset(name):
    return next((km, kmi) for km, kmi in addon.fn.get_tool_presets_keymap() if kmi.properties.name == name)

def activate(kmi):
    with bpy.context.temp_override(area=area, region=region):
        addon.gizmo_toolpreset_bar.activate_preset(bpy.context, kmi.properties)

def check():
    global phase
    try:
        if phase == 0:
            assert len(drawn) == 7, drawn
            assert abs(prefs.bar_background_opacity - 0.34) < 0.0001
            _, kmi = find_preset('Sketch Draw')
            activate(kmi)
            kmi.properties.name = 'Preset 1'
            kmi.properties.order = 100
            kmi.properties.icon = 'SHADING_SOLID'
            kmi.properties.description = 'Automatically refreshed'
            kmi.type = 'F8'
        elif phase == 1:
            assert drawn[-1] == ('Preset 1', 'SHADING_SOLID', 'Automatically refreshed'), drawn
            _, kmi = find_preset('Preset 1')
            with bpy.context.temp_override(area=area, region=region):
                assert addon.gizmo_toolpreset_bar.active_preset_signature(bpy.context) == addon.gizmo_toolpreset_bar.preset_signature(kmi.properties)
            kmi.properties.brush = 'Changed brush'
        elif phase == 2:
            with bpy.context.temp_override(area=area, region=region):
                assert addon.gizmo_toolpreset_bar.active_preset_signature(bpy.context) is None
            assert bpy.ops.storytools.add_tool_preset_shortcut() == {'FINISHED'}
        elif phase == 3:
            _, kmi = find_preset('Preset 2')
            assert kmi.type == 'NONE' and kmi.show_expanded
            assert any(name == 'Preset 2' for name, _, _ in drawn), drawn
            prefs.active_presetbar = False
            kmi.properties.name = 'Edited while off'
        elif phase == 4:
            assert not addon.prefs_io_core.is_class_registered(addon.gizmo_toolpreset_bar.STORYTOOLS_GGT_toolpreset_bar)
            prefs.active_presetbar = True
        elif phase == 5:
            assert any(name == 'Edited while off' for name, _, _ in drawn), drawn
            km, kmi = find_preset('Edited while off')
            activate(kmi)
            assert bpy.ops.storytools.remove_keymap_item(km_name=km.name, kmi_id=kmi.id) == {'FINISHED'}
        elif phase == 6:
            assert not any(name == 'Edited while off' for name, _, _ in drawn), drawn
            with bpy.context.temp_override(area=area, region=region):
                assert addon.gizmo_toolpreset_bar.active_preset_signature(bpy.context) is None
            km, kmi = find_preset('Preset 1')
            assert bpy.ops.storytools.restore_keymap_item(km_name=km.name, kmi_id=kmi.id) == {'FINISHED'}
        elif phase == 7:
            assert drawn[0][0] == 'Sketch Draw' and not any(name == 'Preset 1' for name, _, _ in drawn), drawn
            if addon.gizmo_toolpreset_bar.USE_CAPSULE_UI:
                assert abs(backgrounds['top'][0] - 0.34) < 0.0001
                assert backgrounds['top'] == backgrounds['bottom']
            prefs.bar_background_opacity = 0.6
            prefs.bar_background_color = (0.05, 0.25, 0.1)
        elif phase == 8:
            if addon.gizmo_toolpreset_bar.USE_CAPSULE_UI:
                assert abs(backgrounds['top'][0] - 0.6) < 0.0001
                assert backgrounds['top'] == backgrounds['bottom']
            addon.unregister()
            assert not bpy.app.timers.is_registered(addon.preset_refresh._watch_presets)
            print('PASS: live preset refresh, migration, shared drawing and lifecycle', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        phase += 1
        area.tag_redraw()
        return 0.8
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)

bpy.app.timers.register(check, first_interval=2.0)
