"""Blender 5.2 foreground check for the state-driven pencil/sidebar toggle."""

import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
addon = addon_utils.enable(root.name, default_set=True)
assert addon is not None
prefs = bpy.context.preferences.addons[root.name].preferences
prefs.category = 'Storyboard'
# The pencil follows the actual addon category, independently of reset settings.
prefs.sidebar_tab_target = 'View'
prefs.show_sidebar = 'HIDE'
prefs.set_sidebar_tab = False
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.use_save_prompt = False
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
other = next(a for a in window.screen.areas if a.type != 'VIEW_3D')
other.type = 'VIEW_3D'
area.spaces.active.show_region_ui = True
other.spaces.active.show_region_ui = True
sidebar_setup = addon.setup.sidebar_setup
drawn = {}
original_active = addon.setup.ui.is_sidebar_active


def record_active(context):
    active = original_active(context)
    drawn[context.area.as_pointer()] = active
    return active


addon.setup.ui.is_sidebar_active = record_active
phase = 0


def sidebar(editor):
    return next(r for r in editor.regions if r.type == 'UI')


def select_tab(editor, name):
    with bpy.context.temp_override(window=window, area=editor, region=sidebar(editor)):
        sidebar(editor).active_panel_category = name
    editor.tag_redraw()


def active(editor):
    with bpy.context.temp_override(window=window, area=editor):
        return sidebar_setup.is_sidebar_active(bpy.context)


def click():
    header = next(r for r in area.regions if r.type == 'HEADER')
    with bpy.context.temp_override(window=window, area=area, region=header):
        assert bpy.ops.storytools.toggle_sidebar() == {'FINISHED'}


class Layout:
    def __init__(self):
        self.calls = []

    def row(self, **kwargs):
        return self

    def operator(self, identifier, **kwargs):
        self.calls.append((identifier, kwargs))

    def popover(self, panel, **kwargs):
        self.calls.append((panel, kwargs))


def check():
    global phase
    try:
        if phase == 0:
            select_tab(area, 'Item')
            select_tab(other, 'View')
            area.spaces.active.show_region_ui = False
            area.tag_redraw()
        elif phase == 1:
            assert not active(area)
            click()
            assert area.spaces.active.show_region_ui
            click()  # Cancel before Blender has time to select the tab.
            assert not sidebar_setup._pending
        elif phase == 2:
            assert not area.spaces.active.show_region_ui, 'Deferred selection must not reopen it'
            click()
        elif phase == 3:
            assert active(area) and not active(other)
            assert sidebar(area).active_panel_category == 'Storyboard'
            assert drawn[area.as_pointer()] is True, 'Real header must read the active state'
            assert drawn[other.as_pointer()] is False
            with bpy.context.temp_override(window=window, area=area):
                layout = Layout()
                addon.setup.ui.drawing_setup_ui(SimpleNamespace(layout=layout), bpy.context)
                assert layout.calls[0][0] == 'storytools.toggle_sidebar'
                assert layout.calls[0][1]['depress'] is True
                assert layout.calls[1][0] == 'STORYTOOLS_PT_viewport_setup'
                assert 'icon' not in layout.calls[1][1], 'Popover supplies its own dropdown arrow'
                inline = Layout()
                addon.setup.ui.STORYTOOLS_PT_viewport_setup.draw_header(
                    SimpleNamespace(layout=inline), bpy.context)
                assert not inline.calls, 'Popover must not draw a second pencil inline'
            click()
        elif phase == 4:
            assert not active(area) and not area.spaces.active.show_region_ui
            assert drawn[area.as_pointer()] is False
            click()
        elif phase == 5:
            select_tab(area, 'View')
            assert not active(area), 'An open non-Storyboard sidebar is inactive'
        elif phase == 6:
            assert drawn[area.as_pointer()] is False
            click()  # Switch to Storyboard, instead of hiding the View sidebar.
        elif phase == 7:
            assert active(area) and area.spaces.active.show_region_ui
            area.spaces.active.show_region_ui = False  # Same property toggled by N.
            area.tag_redraw()
        elif phase == 8:
            assert not active(area) and drawn[area.as_pointer()] is False
            area.spaces.active.show_region_ui = True
            area.tag_redraw()
        elif phase == 9:
            select_tab(area, 'Item')
            assert not active(area)
            select_tab(area, 'Storyboard')
            assert active(area), 'Manual selection must activate the icon too'
            assert not active(other) and sidebar(other).active_panel_category == 'View'
            prefs.category = 'Custom Board'
            click()
        elif phase == 10:
            assert active(area) and sidebar(area).active_panel_category == 'Custom Board'
            assert drawn[area.as_pointer()] is True
            click()
        elif phase == 11:
            assert not active(area)
            assert not sidebar_setup._closing
            if '--' in sys.argv:
                screenshot = sys.argv[sys.argv.index('--') + 1]
                with bpy.context.temp_override(window=window, area=area):
                    bpy.ops.screen.screenshot(filepath=screenshot)
            addon_utils.disable(root.name, default_set=True)
            assert not bpy.app.timers.is_registered(sidebar_setup._apply_pending)
            print('PASS: pencil open/close, live header highlight, other-tab activation, manual sidebar changes, rapid cancellation, custom category and viewport isolation', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        phase += 1
        return 0.6
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)


bpy.app.timers.register(check, first_interval=1.5)
