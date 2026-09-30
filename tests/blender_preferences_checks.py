"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""

import importlib
import sys
import unittest
from pathlib import Path

import bpy


class PreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root.parent))
        cls.addon = importlib.import_module(root.name)
        cls.addon.properties.register()
        for pref_class in cls.addon.preferences.classes:
            bpy.utils.register_class(pref_class)
        entry = bpy.context.preferences.addons.new()
        entry.module = root.name
        cls.prefs = entry.preferences

    @classmethod
    def tearDownClass(cls):
        cls.addon.ui.unregister_panels()
        cls.addon.gizmo_toolpreset_bar.unregister()
        bpy.context.preferences.addons.remove(
            bpy.context.preferences.addons[cls.addon.__name__])
        for pref_class in reversed(cls.addon.preferences.classes):
            bpy.utils.unregister_class(pref_class)
        cls.addon.properties.unregister()

    def setUp(self):
        self.scenes = [bpy.data.scenes.new('PrefsTest_' + mode)
                       for mode in ('GLOBAL', 'SCENES', 'LOCAL')]
        self.global_settings, self.scene_settings, self.local_settings = [
            scene.storytools_gp_settings for scene in self.scenes]
        for settings, mode in zip(
                (self.global_settings, self.scene_settings, self.local_settings),
                ('SYNC_GLOBAL', 'SYNC_SCENES', 'SYNC_LOCAL')):
            settings.sync_mode = mode
        with self.addon.prefs_io_core.restoring():
            for settings in (self.prefs.gp, self.global_settings,
                             self.scene_settings, self.local_settings):
                settings.frame_offset = 12
                settings.frame_target_layers = 'ACCESSIBLE'
                settings.keyframe_type = 'ALL'

    def tearDown(self):
        for scene in self.scenes:
            bpy.data.scenes.remove(scene)

    def test_preferences_only_update_global_scenes(self):
        self.prefs.gp.frame_offset = 27
        self.prefs.gp.frame_target_layers = 'VISIBLE'
        self.prefs.gp.keyframe_type = 'BREAKDOWN'
        self.assertEqual(self.global_settings.frame_offset, 27)
        self.assertEqual(self.global_settings.frame_target_layers, 'VISIBLE')
        self.assertEqual(self.global_settings.keyframe_type, 'BREAKDOWN')
        for settings in (self.scene_settings, self.local_settings):
            self.assertEqual(settings.frame_offset, 12)
            self.assertEqual(settings.frame_target_layers, 'ACCESSIBLE')
            self.assertEqual(settings.keyframe_type, 'ALL')

    def test_scene_update_uses_owner_even_when_not_current_scene(self):
        self.assertNotEqual(bpy.context.scene, self.scenes[1])
        self.scene_settings.frame_offset = 31
        self.scene_settings.frame_target_layers = 'ACTIVE'
        self.scene_settings.keyframe_type = 'EXTREME'
        self.assertEqual(self.global_settings.frame_offset, 31)
        self.assertEqual(self.global_settings.frame_target_layers, 'ACTIVE')
        self.assertEqual(self.global_settings.keyframe_type, 'EXTREME')
        self.assertEqual(self.local_settings.frame_offset, 12)
        self.assertEqual(self.prefs.gp.frame_offset, 12)

    def test_local_scene_does_not_propagate(self):
        self.local_settings.frame_offset = 40
        self.assertEqual(self.global_settings.frame_offset, 12)
        self.assertEqual(self.scene_settings.frame_offset, 12)

    def test_restore_defers_sync_and_replication_preserves_enums(self):
        with self.addon.prefs_io_core.restoring():
            self.prefs.gp.frame_offset = 42
            self.prefs.gp.frame_target_layers = 'ACTIVE'
            self.prefs.gp.keyframe_type = 'GENERATED'
        self.assertEqual(self.global_settings.frame_offset, 12)
        self.addon.preferences.replicate_preference_settings(None)
        self.assertEqual(self.global_settings.frame_offset, 42)
        self.assertEqual(self.global_settings.frame_target_layers, 'ACTIVE')
        self.assertEqual(self.global_settings.keyframe_type, 'GENERATED')
        self.assertEqual(self.scene_settings.frame_offset, 12)
        self.assertEqual(self.local_settings.frame_offset, 12)
        self.assertEqual(self.global_settings.sync_mode, 'SYNC_GLOBAL')

    def test_disabled_preset_reload_does_not_register_gizmos(self):
        self.prefs.active_presetbar = False
        self.addon.preferences.reload_toolpreset_buttons()
        self.assertFalse(self.addon.preferences.STORYTOOLS_OT_reload_toolpreset_ui.poll(bpy.context))
        for gizmo_class in self.addon.gizmo_toolpreset_bar.classes:
            self.assertFalse(self.addon.prefs_io_core.is_class_registered(gizmo_class))

    def test_enabled_preset_reload_can_repeat(self):
        self.prefs.active_presetbar = True
        for _ in range(2):
            self.addon.preferences.reload_toolpreset_buttons()
        self.assertTrue(self.addon.preferences.STORYTOOLS_OT_reload_toolpreset_ui.poll(bpy.context))
        for gizmo_class in self.addon.gizmo_toolpreset_bar.classes:
            self.assertTrue(self.addon.prefs_io_core.is_class_registered(gizmo_class))

    def test_sidebar_category_fallback_and_custom_name(self):
        self.prefs.show_sidebar_ui = True
        for name, expected in (('', 'Storytools'), ('   ', 'Storytools'),
                               ('  Drawing  ', 'Drawing')):
            self.prefs.category = name
            for panel in self.addon.ui.panel_classes:
                self.assertTrue(hasattr(bpy.types, panel.__name__))
                self.assertEqual(panel.bl_category, expected)

    def test_ui_fold_state_is_excluded_from_backup_and_restore(self):
        ui_props = self.addon.preferences.PREFERENCE_UI_PROPS
        for prop_name in ui_props:
            setattr(self.prefs, prop_name, True)
        backup = self.addon.prefs_io.prefs_to_json(self.prefs)
        self.assertTrue(ui_props.isdisjoint(backup))
        with self.addon.prefs_io_core.restoring():
            self.addon.prefs_io.json_to_prefs(
                {prop_name: False for prop_name in ui_props}, self.prefs)
        for prop_name in ui_props:
            self.assertTrue(getattr(self.prefs, prop_name))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PreferencesTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
