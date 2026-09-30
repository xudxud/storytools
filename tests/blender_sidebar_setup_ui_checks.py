"""Blender 5.2 foreground: one-click sidebar targeting and viewport setup UI."""

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
prefs.sidebar_tab_target = 'Storyboard'
prefs.show_sidebar = 'SHOW'
prefs.set_sidebar_tab = True
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.use_save_prompt = False
window = bpy.context.window
original_workspace = window.workspace
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
other = next(a for a in window.screen.areas if a.type != 'VIEW_3D')
other.type = 'VIEW_3D'
area.spaces.active.show_region_ui = True
other.spaces.active.show_region_ui = True
phase = 0


def region(editor):
    return next(r for r in editor.regions if r.type == 'UI')


def select_tab(editor, name):
    sidebar = region(editor)
    with bpy.context.temp_override(window=window, area=editor, region=sidebar):
        sidebar.active_panel_category = name
    editor.tag_redraw()


class Layout:
    def __init__(self):
        self.operators = []

    def column(self, **kwargs):
        return self

    row = column

    def separator(self):
        pass

    def label(self, **kwargs):
        pass

    def menu(self, *args, **kwargs):
        pass

    def operator(self, identifier, **kwargs):
        self.operators.append((identifier, kwargs))
        return SimpleNamespace()


def click_setup():
    with bpy.context.temp_override(window=window, area=area):
        assert bpy.ops.storytools.setup_drawing() == {'FINISHED'}


def check():
    global phase, area
    try:
        sidebar_setup = addon.setup.sidebar_setup
        if phase == 0:
            select_tab(area, 'Item')
            select_tab(other, 'View')
            area.spaces.active.show_region_ui = False
            area.tag_redraw()
        elif phase == 1:
            click_setup()  # Exactly one invocation from a closed sidebar.
        elif phase == 2:
            assert area.spaces.active.show_region_ui
            assert region(area).active_panel_category == 'Storyboard'
            assert region(other).active_panel_category == 'View', 'Do not retarget another viewport'
            assert not sidebar_setup._pending
            select_tab(area, 'View')
            click_setup()  # Already open, but on the wrong tab.
        elif phase == 3:
            assert region(area).active_panel_category == 'Storyboard'
            with bpy.context.temp_override(window=window, area=area):
                layout = Layout()
                addon.setup.ui.STORYTOOLS_PT_viewport_setup.draw(
                    SimpleNamespace(layout=layout), bpy.context)
                assert layout.operators[0][0] == 'storytools.toggle_viewport_bars'
                assert layout.operators[0][1]['icon'] == 'CHECKBOX_DEHLT'
                bpy.ops.storytools.toggle_viewport_bars()
                assert addon.viewport_bars.is_visible(bpy.context)
            with bpy.context.temp_override(window=window, area=other):
                assert not addon.viewport_bars.is_enabled(bpy.context)
            # Pending selection must stop if its editor changes type.
            sidebar_setup.set_sidebar(other, window)
            other.type = 'TEXT_EDITOR'
        elif phase == 4:
            assert not sidebar_setup._pending
            before = {w.as_pointer() for w in bpy.data.workspaces}
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.workspace.duplicate()
            target = next(w for w in bpy.data.workspaces if w.as_pointer() not in before)
            target.name = 'Storyboarding'
            for screen in target.screens:
                for editor in screen.areas:
                    if editor.type == 'VIEW_3D':
                        editor.spaces.active.show_region_ui = False
        elif phase == 5:
            window.workspace = original_workspace
        elif phase == 6:
            area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.storytools.set_storyboard_workspace()
        elif phase == 7:
            assert window.workspace.name == 'Storyboarding'
            area = max((a for a in window.screen.areas if a.type == 'VIEW_3D'),
                       key=lambda a: a.width * a.height)
            assert area.spaces.active.show_region_ui
            assert region(area).active_panel_category == 'Storyboard'
            assert not sidebar_setup._pending and not sidebar_setup._workspaces
            # Check that an unavailable category stops retrying, too.
            prefs.sidebar_tab_target = 'Missing Test Tab'
            click_setup()
            return advance(1.8)
        elif phase == 8:
            assert not sidebar_setup._pending
            prefs.sidebar_tab_target = 'Storyboard'
            click_setup()
            assert bpy.app.timers.is_registered(sidebar_setup._apply_pending)
            addon_utils.disable(root.name, default_set=True)
            assert not bpy.app.timers.is_registered(sidebar_setup._apply_pending)
            assert not sidebar_setup._pending
            print('PASS: one-click closed/open sidebar, captured viewport, popover toggle, workspace activation, bounded retry and cleanup', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        return advance(0.8)
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)


def advance(delay):
    global phase
    phase += 1
    return delay


bpy.app.timers.register(check, first_interval=1.5)
