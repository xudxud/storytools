"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
        bpy.utils.register_class(cls.addon.keymaps.STORYTOOLS_OT_set_draw_tool)

    @classmethod
    def tearDownClass(cls):
        cls.addon.preset_refresh.unregister()
        cls.addon.ui.unregister_panels()
        cls.addon.gizmo_toolpreset_bar.unregister()
        bpy.context.preferences.addons.remove(
            bpy.context.preferences.addons[cls.addon.__name__])
        for pref_class in reversed(cls.addon.preferences.classes):
            bpy.utils.unregister_class(pref_class)
        cls.addon.properties.unregister()
        bpy.utils.unregister_class(cls.addon.keymaps.STORYTOOLS_OT_set_draw_tool)

    def setUp(self):
        self.addon.preset_refresh.unregister()
        self.addon.preset_undo.clear()
        for suffix in ('color', 'opacity'):
            self.prefs.property_unset('bar_background_' + suffix)
            for prefix in ('toolbar', 'presetbar'):
                name = prefix + '_background_' + suffix
                self.prefs.property_unset(name)
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
        self.addon.preset_refresh.unregister()
        for km in bpy.context.window_manager.keyconfigs.user.keymaps:
            for kmi in list(km.keymap_items):
                if kmi.idname == 'storytools.set_draw_tool':
                    km.keymap_items.remove(kmi)
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

    def add_preset(self, name='Example'):
        km = bpy.context.window_manager.keyconfigs.user.keymaps.new(
            name='Grease Pencil Draw Mode', space_type='EMPTY')
        kmi = km.keymap_items.new('storytools.set_draw_tool', type='F6', value='PRESS')
        kmi.properties.name = name
        return km, kmi

    def test_old_json_backgrounds_merge_and_export_only_shared_fields(self):
        old = {'toolbar_background_color': [0.2, 0.3, 0.4],
               'toolbar_background_opacity': 0.42,
               'presetbar_background_color': [0.7, 0.8, 0.9],
               'presetbar_background_opacity': 0.9}
        with self.addon.prefs_io_core.restoring():
            log = self.addon.prefs_io.json_to_prefs(old, self.prefs)
        self.assertEqual(log, [])
        self.assertAlmostEqual(self.prefs.bar_background_opacity, 0.42)
        for actual, expected in zip(self.prefs.bar_background_color, (0.2, 0.3, 0.4)):
            self.assertAlmostEqual(actual, expected)
        backup = self.addon.prefs_io.prefs_to_json(self.prefs)
        self.assertTrue(set(old).isdisjoint(backup))
        self.assertIn('bar_background_color', backup)
        self.assertIn('bar_background_opacity', backup)

    def test_shared_json_values_take_precedence_and_top_only_backups_work(self):
        with self.addon.prefs_io_core.restoring():
            self.addon.prefs_io.json_to_prefs(
                {'presetbar_background_opacity': 0.8}, self.prefs)
        self.assertAlmostEqual(self.prefs.bar_background_opacity, 0.8)
        with self.addon.prefs_io_core.restoring():
            self.addon.prefs_io.json_to_prefs(
                {'bar_background_opacity': 0.5, 'toolbar_background_opacity': 0.2}, self.prefs)
        self.assertAlmostEqual(self.prefs.bar_background_opacity, 0.5)

    def test_saved_blender_backgrounds_migrate_once(self):
        self.prefs.toolbar_background_opacity = 0.3
        self.prefs.presetbar_background_opacity = 0.8
        self.prefs.toolbar_background_color = [0.2, 0.3, 0.4]
        self.addon.prefs_io.migrate_bar_appearance(self.prefs)
        self.assertAlmostEqual(self.prefs.bar_background_opacity, 0.3)
        self.assertFalse(self.prefs.is_property_set('toolbar_background_opacity'))
        self.assertFalse(self.prefs.is_property_set('presetbar_background_opacity'))
        self.prefs.bar_background_opacity = 0.6
        self.addon.prefs_io.migrate_bar_appearance(self.prefs)
        self.assertAlmostEqual(self.prefs.bar_background_opacity, 0.6)
        self.prefs.property_unset('bar_background_opacity')
        self.addon.prefs_io.migrate_bar_appearance(self.prefs)
        self.assertAlmostEqual(self.prefs.bar_background_opacity, 0.77)

    def test_new_presets_have_unique_names_no_shortcut_and_expand(self):
        self.add_preset('Preset 1')
        self.add_preset('Preset 3')
        self.assertEqual(bpy.ops.storytools.add_tool_preset_shortcut(), {'FINISHED'})
        presets = self.addon.fn.get_tool_presets_keymap()
        added = next(kmi for _km, kmi in presets if kmi.properties.name == 'Preset 2')
        self.assertEqual(added.type, 'NONE')
        self.assertTrue(added.show_expanded)
        self.assertTrue(bpy.context.preferences.is_dirty)

    def test_auto_refresh_debounces_and_updates_shortcut_and_metadata(self):
        _km, kmi = self.add_preset()
        self.prefs.active_presetbar = True
        watcher = self.addon.preset_refresh
        watcher.refresh_now()
        old_signature = self.addon.gizmo_toolpreset_bar.preset_signature(kmi.properties)
        state = ('unchanged drawing state',)
        self.addon.gizmo_toolpreset_bar._activated_presets[123] = (old_signature, state)
        self.addon.preset_undo._transitions['step'] = ('', {}, {}, None, old_signature)
        with patch.object(watcher, '_apply_snapshot', wraps=watcher._apply_snapshot) as refresh:
            kmi.properties.name = 'Renamed'
            watcher.check_for_changes(now=1.0)
            kmi.properties.order = 20
            kmi.properties.icon = 'SHADING_SOLID'
            kmi.type = 'F7'
            watcher.check_for_changes(now=1.1)
            watcher.check_for_changes(now=1.2)
            refresh.assert_not_called()
            watcher.check_for_changes(now=1.4)
            self.assertEqual(refresh.call_count, 1)
            watcher.check_for_changes(now=2.0)
            self.assertEqual(refresh.call_count, 1)
        new_signature = self.addon.gizmo_toolpreset_bar.preset_signature(kmi.properties)
        self.assertEqual(self.addon.gizmo_toolpreset_bar._activated_presets[123], (new_signature, state))
        self.assertEqual(self.addon.preset_undo._transitions['step'][4], new_signature)
        self.assertEqual(watcher._snapshot[0].shortcut, kmi.to_string())
        self.assertEqual(watcher._snapshot[0].icon, 'SHADING_SOLID')

    def test_behavior_edits_clear_active_and_undo_highlights(self):
        _km, kmi = self.add_preset()
        watcher = self.addon.preset_refresh
        watcher.refresh_now()
        signature = self.addon.gizmo_toolpreset_bar.preset_signature(kmi.properties)
        self.addon.gizmo_toolpreset_bar._activated_presets[123] = (signature, ())
        self.addon.preset_undo._transitions['step'] = ('', {}, {}, None, signature)
        kmi.properties.brush = 'Changed brush'
        watcher.check_for_changes(now=1.0)
        watcher.check_for_changes(now=1.3)
        self.assertNotIn(123, self.addon.gizmo_toolpreset_bar._activated_presets)
        self.assertIsNone(self.addon.preset_undo._transitions['step'][4])

    def test_hide_disable_and_remove_clear_highlight(self):
        watcher = self.addon.preset_refresh
        for action in ('hide', 'disable', 'remove'):
            km, kmi = self.add_preset(action)
            watcher.refresh_now()
            signature = self.addon.gizmo_toolpreset_bar.preset_signature(kmi.properties)
            self.addon.gizmo_toolpreset_bar._activated_presets[123] = (signature, ())
            if action == 'hide':
                kmi.properties.show = False
            elif action == 'disable':
                kmi.active = False
            else:
                km.keymap_items.remove(kmi)
            watcher.check_for_changes(now=1.0)
            watcher.check_for_changes(now=1.3)
            self.assertNotIn(123, self.addon.gizmo_toolpreset_bar._activated_presets)

    def test_refresh_while_bar_disabled_does_not_register_gizmos(self):
        _km, kmi = self.add_preset()
        self.prefs.active_presetbar = False
        watcher = self.addon.preset_refresh
        watcher.refresh_now()
        kmi.properties.name = 'Updated while closed'
        watcher.check_for_changes(now=1.0)
        watcher.check_for_changes(now=1.3)
        for cls in self.addon.gizmo_toolpreset_bar.classes:
            self.assertFalse(self.addon.prefs_io_core.is_class_registered(cls))
        self.prefs.active_presetbar = True
        self.assertEqual(watcher._snapshot[0].signature[0], 'Updated while closed')

    def test_watcher_cleanup_and_restore_guard(self):
        watcher = self.addon.preset_refresh
        watcher.register()
        self.assertTrue(bpy.app.timers.is_registered(watcher._watch_presets))
        with self.addon.prefs_io_core.restoring():
            watcher.check_for_changes(now=1.0)
        self.assertIsNone(watcher._pending)
        watcher.unregister()
        self.assertFalse(bpy.app.timers.is_registered(watcher._watch_presets))
        self.assertNotIn(watcher.reset_after_load, bpy.app.handlers.load_post)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PreferencesTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
