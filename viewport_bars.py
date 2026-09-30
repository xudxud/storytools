# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-editor bars, persisted on Screen because SpaceView3D has no ID properties.

Saved area/space indices are used only on deferred initialization and file load. During
editing, space pointers identify existing editors, so splitting an area cannot
copy its opt-in state. Save handlers refresh indices before writing the file.
"""

import bpy
from bpy.app.handlers import persistent
from .prefs_io_core import set_class_registered


_states = {}
_screens = set()


class STORYTOOLS_PG_viewport_bars(bpy.types.PropertyGroup):
    area_index: bpy.props.IntProperty()
    space_index: bpy.props.IntProperty()
    enabled: bpy.props.BoolProperty(default=False)
    expanded: bpy.props.BoolProperty(default=True)


def _editors(screen):
    for area_index, area in enumerate(screen.areas):
        for space_index, space in enumerate(area.spaces):
            if space.type == 'VIEW_3D':
                yield area_index, space_index, area, space


def sync_states():
    live = set()
    live_screens = set()
    for screen in bpy.data.screens:
        screen_key = screen.as_pointer()
        new_screen = screen_key not in _screens
        live_screens.add(screen_key)
        # Appending a template workspace does not trigger load_post. Restore
        # its saved choices once; splits in existing screens never use indices.
        initial = {(r.area_index, r.space_index): [r.enabled, r.expanded]
                   for r in screen.storytools_viewport_bars} if new_screen else {}
        records = []
        for ai, si, area, space in _editors(screen):
            key = space.as_pointer()
            live.add(key)
            state = _states.setdefault(key, initial.get((ai, si), [False, True]))
            records.append((ai, si, *state))
        saved = screen.storytools_viewport_bars
        previous = [(r.area_index, r.space_index, r.enabled, r.expanded)
                    for r in saved]
        if records != previous:
            saved.clear()
            for ai, si, enabled, expanded in records:
                record = saved.add()
                record.area_index, record.space_index = ai, si
                record.enabled, record.expanded = enabled, expanded
        if records != previous or new_screen:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    for key in _states.keys() - live:
        del _states[key]
    _screens.clear()
    _screens.update(live_screens)


@persistent
def restore_states(_dummy=None):
    _states.clear()
    _screens.clear()
    for screen in bpy.data.screens:
        _screens.add(screen.as_pointer())
        saved = {(r.area_index, r.space_index): [r.enabled, r.expanded]
                 for r in screen.storytools_viewport_bars}
        for ai, si, area, space in _editors(screen):
            _states[space.as_pointer()] = saved.get((ai, si), [False, True])


@persistent
def save_states(_dummy=None):
    sync_states()


def track_editors():
    sync_states()
    return 0.2


def is_enabled(context):
    space = context.space_data
    return bool(space and space.type == 'VIEW_3D'
                and _states.get(space.as_pointer(), (False, True))[0])


def is_visible(context):
    return is_enabled(context) and _states[context.space_data.as_pointer()][1]


def toggle_expanded(context):
    sync_states()
    state = _states[context.space_data.as_pointer()]
    state[1] = not state[1]
    sync_states()
    context.area.tag_redraw()


class STORYTOOLS_OT_toggle_viewport_bars(bpy.types.Operator):
    bl_idname = 'storytools.toggle_viewport_bars'
    bl_label = 'Show Storytools Bars'
    bl_description = 'Enable or disable Storytools bars in this viewport only; saved with the blend file'

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D'

    def execute(self, context):
        sync_states()
        state = _states[context.space_data.as_pointer()]
        state[0] = not state[0]
        if state[0]:
            state[1] = True
        sync_states()
        context.area.tag_redraw()
        return {'FINISHED'}


def draw_toggle(layout, context):
    layout.operator('storytools.toggle_viewport_bars',
                    text='Show Storytools Bars',
                    icon='CHECKBOX_HLT' if is_enabled(context) else 'CHECKBOX_DEHLT')


def register():
    set_class_registered(STORYTOOLS_PG_viewport_bars, True)
    if not hasattr(bpy.types.Screen, 'storytools_viewport_bars'):
        bpy.types.Screen.storytools_viewport_bars = bpy.props.CollectionProperty(
            type=STORYTOOLS_PG_viewport_bars)
    set_class_registered(STORYTOOLS_OT_toggle_viewport_bars, True)
    # Blender enables addons inside RestrictBlend: bpy.data.screens is not
    # available until registration returns. The first tracker tick restores
    # saved editors through sync_states()'s new-screen initialization.
    _states.clear()
    _screens.clear()
    if restore_states not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(restore_states)
    if save_states not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_states)
    if not bpy.app.timers.is_registered(track_editors):
        bpy.app.timers.register(track_editors, first_interval=0.2, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(track_editors):
        bpy.app.timers.unregister(track_editors)
    if save_states in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_states)
    if restore_states in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(restore_states)
    set_class_registered(STORYTOOLS_OT_toggle_viewport_bars, False)
    if hasattr(bpy.types.Screen, 'storytools_viewport_bars'):
        del bpy.types.Screen.storytools_viewport_bars
    set_class_registered(STORYTOOLS_PG_viewport_bars, False)
    _states.clear()
    _screens.clear()
