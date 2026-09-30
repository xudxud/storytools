"""Blender 5.2 foreground check using the actual addon enable/disable lifecycle.

Run Blender --factory-startup --python-exit-code 1 --python this_file.
The test closes its Blender window when finished.
"""

import os
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.use_save_prompt = False
errors = []


def on_error():
    errors.append(traceback.format_exc())


def enable():
    addon = addon_utils.enable(root.name, default_set=True, handle_error=on_error)
    assert not errors, '\n'.join(errors)
    assert addon is not None
    assert addon_utils.check(root.name) == (True, True)
    bars = addon.viewport_bars
    assert 'bl_rna' in addon.setup.ui.STORYTOOLS_PT_viewport_setup.__dict__
    assert bpy.app.timers.is_registered(bars.track_editors)
    assert bpy.app.handlers.load_post.count(bars.restore_states) == 1
    assert bpy.app.handlers.save_pre.count(bars.save_states) == 1
    return addon


def disable(addon):
    addon_utils.disable(root.name, default_set=True, handle_error=on_error)
    assert not errors, '\n'.join(errors)
    bars = addon.viewport_bars
    assert not bpy.app.timers.is_registered(bars.track_editors)
    assert 'bl_rna' not in addon.setup.ui.STORYTOOLS_PT_viewport_setup.__dict__
    assert bars.restore_states not in bpy.app.handlers.load_post
    assert bars.save_states not in bpy.app.handlers.save_pre
    assert not hasattr(bpy.types.Screen, 'storytools_viewport_bars')


try:
    addon = enable()
    # Disabling before deferred initialization must be safe too.
    disable(addon)
    addon = enable()
except Exception:
    traceback.print_exc()
    sys.stderr.flush()
    os._exit(1)

phase = 0
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')


class MenuLayout:
    def separator(self):
        pass

    def operator(self, identifier, **kwargs):
        assert identifier == 'storytools.toggle_viewport_bars'
        self.icon = kwargs['icon']


def check():
    global phase, addon
    try:
        bars = addon.viewport_bars
        with bpy.context.temp_override(area=area):
            if phase == 0:
                assert bars._screens, 'The real timer must initialize editors'
                assert not bars.is_enabled(bpy.context)
                layout = MenuLayout()
                bars.draw_toggle(layout, bpy.context)
                assert layout.icon == 'CHECKBOX_DEHLT'
                bpy.ops.storytools.toggle_viewport_bars()
                assert bars.is_visible(bpy.context)
                bars.draw_toggle(layout, bpy.context)
                assert layout.icon == 'CHECKBOX_HLT'
                # Restore saved choices only after enable returns.
                disable(addon)
                addon = enable()
            elif phase == 1:
                assert bars.is_visible(bpy.context), 'Enable must restore saved opt-in'
                bpy.ops.storytools.toggle_bottom_bar()
                assert bars.is_enabled(bpy.context) and not bars.is_visible(bpy.context)
                disable(addon)
                addon = enable()
            elif phase == 2:
                assert bars.is_enabled(bpy.context) and not bars.is_visible(bpy.context)
                bpy.ops.storytools.toggle_viewport_bars()
                assert not bars.is_enabled(bpy.context)
                disable(addon)
                print('PASS: real restricted enable, setup popover, deferred restore, immediate disable and repeated re-enable', flush=True)
                bpy.ops.wm.quit_blender()
                return None
        phase += 1
        return 0.8
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)


bpy.app.timers.register(check, first_interval=1.5)
