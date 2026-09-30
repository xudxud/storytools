"""Run Blender --background --factory-startup --python-exit-code 1 --python this_file."""

import importlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy
from _bpy_restrict_state import RestrictBlend


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
bars = importlib.import_module(root.name + '.viewport_bars')
# A failure after classes/menu/handlers were registered must remain cleanable,
# even inside the same restricted context Blender uses for addon activation.
with RestrictBlend():
    with patch.object(bpy.app.timers, 'register', side_effect=RuntimeError('test registration failure')):
        try:
            bars.register()
        except RuntimeError as error:
            assert str(error) == 'test registration failure'
        else:
            raise AssertionError('Expected the injected registration failure')
    bars.unregister()
    bars.unregister()
    assert not hasattr(bpy.types.Screen, 'storytools_viewport_bars')
bars.register()
screen = bpy.context.window.screen
original = next(a for a in screen.areas if a.type == 'VIEW_3D')

with bpy.context.temp_override(area=original):
    assert not bars.is_enabled(bpy.context)
    bpy.ops.storytools.toggle_viewport_bars()
    assert bars.is_visible(bpy.context)
    bars.toggle_expanded(bpy.context)
    assert bars.is_enabled(bpy.context) and not bars.is_visible(bpy.context)
    bars.toggle_expanded(bpy.context)
    bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)

bars.sync_states()
viewports = [a for a in screen.areas if a.type == 'VIEW_3D']
assert len(viewports) == 2
new = next(a for a in viewports if a.as_pointer() != original.as_pointer())
with bpy.context.temp_override(area=original):
    assert bars.is_visible(bpy.context), 'Split must preserve the original viewport'
with bpy.context.temp_override(area=new):
    assert not bars.is_enabled(bpy.context), 'Split viewport must default to disabled'
    bpy.ops.storytools.toggle_viewport_bars()
    bars.toggle_expanded(bpy.context)

# Conversion to a viewport must also start disabled.
other = next(a for a in screen.areas if a.type != 'VIEW_3D')
other.type = 'VIEW_3D'
bars.sync_states()
with bpy.context.temp_override(area=other):
    assert not bars.is_enabled(bpy.context)

expected = [(r.area_index, r.space_index, r.enabled, r.expanded)
            for r in screen.storytools_viewport_bars]
with tempfile.TemporaryDirectory(prefix='storytools_bars_',
                                 dir=root) as directory:
    path = str(Path(directory) / 'viewport_states.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    screen = bpy.context.window.screen
    actual = [(r.area_index, r.space_index, r.enabled, r.expanded)
              for r in screen.storytools_viewport_bars]
    assert actual == expected, (actual, expected)
    for ai, si, enabled, expanded in expected:
        space = screen.areas[ai].spaces[si]
        assert bars._states[space.as_pointer()] == [enabled, expanded]

    # Storyboarding setup appends a workspace from its template startup file.
    workspace_name = bpy.context.window.workspace.name
    old_screens = {s.as_pointer() for s in bpy.data.screens}
    bpy.ops.workspace.append_activate(idname=workspace_name, filepath=path)
    bars.sync_states()
    imported = next(s for s in bpy.data.screens if s.as_pointer() not in old_screens)
    for ai, si, enabled, expanded in expected:
        space = imported.areas[ai].spaces[si]
        assert bars._states[space.as_pointer()] == [enabled, expanded]

# Re-enabling the addon must retain saved editor choices too.
bars.unregister()
bars.register()
bars.track_editors()
for ai, si, enabled, expanded in expected:
    space = screen.areas[ai].spaces[si]
    assert bars._states[space.as_pointer()] == [enabled, expanded]
bars.unregister()
print('Viewport bars checks passed: defaults, local collapse, split, save/load, template append, re-registration')
