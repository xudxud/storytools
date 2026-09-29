"""Session-level regression checks for preset undo without a Blender installation."""

import importlib.util
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock


class GPData(dict):
    name = 'Drawing'

    def __init__(self):
        super().__init__()
        self.layers = types.SimpleNamespace(active=types.SimpleNamespace(name='Sketch'))


class PresetUndoTests(unittest.TestCase):
    def setUp(self):
        self.module_names = ('bpy', 'storytools_test', 'storytools_test.fn',
                             'storytools_test.gizmo_toolpreset_bar', 'storytools_test.preset_undo')
        self.previous_modules = {name: sys.modules.get(name) for name in self.module_names}
        self.gp = GPData()
        self.ob = types.SimpleNamespace(
            name='Drawing', type='GREASEPENCIL', data=self.gp,
            active_material=types.SimpleNamespace(name='Blue'))
        self.brush = types.SimpleNamespace(
            name='Pencil', gpencil_settings=types.SimpleNamespace(stroke_type='STROKE'))
        self.paint = types.SimpleNamespace(brush=self.brush)
        self.tool = types.SimpleNamespace(idname='builtin.brush')
        self.context = types.SimpleNamespace(
            object=self.ob, mode='PAINT_GREASE_PENCIL',
            tool_settings=types.SimpleNamespace(gpencil_paint=self.paint),
            workspace=types.SimpleNamespace(tools=types.SimpleNamespace(
                from_space_view3d_mode=lambda *_args, **_kwargs: self.tool)))
        self.area = types.SimpleNamespace(
            type='VIEW_3D', regions=[types.SimpleNamespace(type='WINDOW')], tag_redraw=Mock())
        self.window = types.SimpleNamespace(
            screen=types.SimpleNamespace(areas=[self.area]))
        self.context.window = self.window
        self.context.window_manager = types.SimpleNamespace(windows=[self.window])
        self.context.temp_override = lambda **_kwargs: nullcontext()

        bpy = types.ModuleType('bpy')
        bpy.context = self.context
        bpy.app = types.SimpleNamespace(version=(5, 2, 0))
        bpy.data = types.SimpleNamespace(brushes={})
        bpy.ops = types.SimpleNamespace(
            object=types.SimpleNamespace(mode_set=Mock()),
            wm=types.SimpleNamespace(tool_set_by_id=Mock(side_effect=self.set_tool)))
        fn = types.ModuleType('storytools_test.fn')
        fn.serialize_brush_reference = lambda paint: f'asset::{paint.brush.name}'
        fn.set_brush_by_reference = self.set_brush
        fn.get_active_gp_brush = lambda context: context.tool_settings.gpencil_paint.brush
        fn.set_stroke_type = lambda brush, value: setattr(brush.gpencil_settings, 'stroke_type', value)
        fn.suppress_brush_sync = Mock()
        fn.set_layer_by_name = lambda ob, name: setattr(ob.data.layers, 'active', types.SimpleNamespace(name=name))
        fn.set_material_by_name = lambda ob, name: setattr(ob, 'active_material', types.SimpleNamespace(name=name))
        gizmo_bar = types.ModuleType('storytools_test.gizmo_toolpreset_bar')
        gizmo_bar.preset_signature = lambda preset: preset
        gizmo_bar.set_activated_signature = Mock()
        self.set_active_signature = gizmo_bar.set_activated_signature

        package = types.ModuleType('storytools_test')
        package.__path__ = []
        sys.modules.update({'bpy': bpy, 'storytools_test': package,
                            'storytools_test.fn': fn, 'storytools_test.gizmo_toolpreset_bar': gizmo_bar})
        spec = importlib.util.spec_from_file_location(
            'storytools_test.preset_undo', Path(__file__).resolve().parents[1] / 'preset_undo.py')
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)

    def tearDown(self):
        for name, module in self.previous_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def set_tool(self, name):
        self.tool.idname = name

    def set_brush(self, ref):
        name = ref.split('::')[-1]
        self.paint.brush = types.SimpleNamespace(
            name=name, gpencil_settings=types.SimpleNamespace(stroke_type='STROKE'))
        return True

    def switch(self, tool, brush, layer, material):
        before = self.module.capture_state(self.context)
        self.set_tool(tool)
        self.set_brush(f'asset::{brush}')
        self.gp.layers.active = types.SimpleNamespace(name=layer)
        self.ob.active_material = types.SimpleNamespace(name=material)
        self.module.record_preset(self.context, before, 'new-preset', 'previous-preset')

    def assert_state(self, tool, brush, layer, material):
        self.assertEqual(self.tool.idname, tool)
        self.assertEqual(self.paint.brush.name, brush)
        self.assertEqual(self.gp.layers.active.name, layer)
        self.assertEqual(self.ob.active_material.name, material)

    def test_undo_stroke_keeps_preset_then_undo_switch_restores_everything(self):
        self.switch('builtin.brush', 'Marker Chisel', 'Line', 'Black')
        line_step = self.gp[self.module.PRESET_STEP_KEY]
        self.module.undo_redo_pre()
        self.assertFalse(self.module.undo_redo_post())  # A stroke was undone: marker did not change.
        self.assert_state('builtin.brush', 'Marker Chisel', 'Line', 'Black')

        self.module.undo_redo_pre()
        self.gp.pop(self.module.PRESET_STEP_KEY)
        self.assertTrue(self.module.undo_redo_post())
        self.assert_state('builtin.brush', 'Pencil', 'Sketch', 'Blue')
        self.set_active_signature.assert_called_with(self.context, 'previous-preset')

        self.module.undo_redo_pre()
        self.gp[self.module.PRESET_STEP_KEY] = line_step
        self.assertTrue(self.module.undo_redo_post())
        self.assert_state('builtin.brush', 'Marker Chisel', 'Line', 'Black')

        self.module.undo_redo_pre()
        self.assertFalse(self.module.undo_redo_post())  # Redo the stroke, not the switch.
        self.assert_state('builtin.brush', 'Marker Chisel', 'Line', 'Black')

    def test_undo_eraser_on_same_layer_then_redo_restores_eraser(self):
        self.switch('builtin_brush.Erase', 'Eraser Hard', 'Sketch', 'Blue')
        eraser_step = self.gp[self.module.PRESET_STEP_KEY]
        self.module.undo_redo_pre()
        self.gp.pop(self.module.PRESET_STEP_KEY)
        self.assertTrue(self.module.undo_redo_post())
        self.assert_state('builtin.brush', 'Pencil', 'Sketch', 'Blue')

        self.module.undo_redo_pre()
        self.gp[self.module.PRESET_STEP_KEY] = eraser_step
        self.assertTrue(self.module.undo_redo_post())
        self.assert_state('builtin_brush.Erase', 'Eraser Hard', 'Sketch', 'Blue')
        self.set_active_signature.assert_called_with(self.context, 'new-preset')

    def test_consecutive_preset_switches_undo_one_at_a_time(self):
        self.switch('builtin.brush', 'Marker Chisel', 'Line', 'Black')
        line_step = self.gp[self.module.PRESET_STEP_KEY]
        self.switch('builtin_brush.Erase', 'Eraser Hard', 'Line', 'Black')

        self.module.undo_redo_pre()
        self.gp[self.module.PRESET_STEP_KEY] = line_step
        self.assertTrue(self.module.undo_redo_post())
        self.assert_state('builtin.brush', 'Marker Chisel', 'Line', 'Black')

        self.module.undo_redo_pre()
        self.gp.pop(self.module.PRESET_STEP_KEY)
        self.assertTrue(self.module.undo_redo_post())
        self.assert_state('builtin.brush', 'Pencil', 'Sketch', 'Blue')


if __name__ == '__main__':
    unittest.main()
