# SPDX-License-Identifier: GPL-3.0-or-later
"""Open the sidebar now, select its tab after Blender builds the UI region."""

import bpy
from bpy.app.handlers import persistent
from .. import fn


INTERVAL = 0.1
MAX_ATTEMPTS = 12
_pending = {}
_closing = {}
_workspaces = {}


def _start_timer():
    if not bpy.app.timers.is_registered(_apply_pending):
        bpy.app.timers.register(_apply_pending, first_interval=INTERVAL)


def sidebar_category():
    return fn.get_addon_prefs().category.strip() or 'Storytools'


def is_sidebar_active(context):
    area, space = context.area, context.space_data
    if (not area or area.type != 'VIEW_3D' or not space
            or not space.show_region_ui or not fn.get_addon_prefs().show_sidebar_ui):
        return False
    sidebar = next((r for r in area.regions if r.type == 'UI'), None)
    return bool(sidebar and sidebar.active_panel_category == sidebar_category())


def _queue_tab(window, area, tab):
    key = (window.as_pointer(), area.as_pointer())
    _closing.pop(key, None)
    _pending[key] = (area.spaces.active.as_pointer(), tab, 0)
    _start_timer()


class STORYTOOLS_OT_toggle_sidebar(bpy.types.Operator):
    bl_idname = 'storytools.toggle_sidebar'
    bl_label = 'Toggle Storytools Sidebar'
    bl_description = 'Open the Storytools sidebar tab in this viewport, or close it when already active'

    @classmethod
    def poll(cls, context):
        return (context.area and context.area.type == 'VIEW_3D'
                and fn.get_addon_prefs().show_sidebar_ui)

    def execute(self, context):
        window, area, space = context.window, context.area, context.space_data
        key = (window.as_pointer(), area.as_pointer())
        tab = sidebar_category()
        pending = _pending.pop(key, None)
        closing = _closing.pop(key, None)
        _workspaces.pop(window.as_pointer(), None)
        # A second click during deferred opening cancels that opening too.
        opening = (pending and pending[0] == space.as_pointer()
                   and pending[1] == tab and space.show_region_ui)
        if not closing and (is_sidebar_active(context) or opening):
            space.show_region_ui = False
            # Blender can ignore a hide while the region is animating open.
            if space.show_region_ui:
                _closing[key] = (space.as_pointer(), 0)
                _start_timer()
        else:
            space.show_region_ui = True
            _queue_tab(window, area, tab)
        area.tag_redraw()
        return {'FINISHED'}


def set_sidebar(area=None, window=None):
    window = window or bpy.context.window
    area = area or bpy.context.area
    if not window:
        return
    if not area or area.type != 'VIEW_3D':
        area = max((a for a in window.screen.areas if a.type == 'VIEW_3D'),
                   key=lambda a: a.width * a.height, default=None)
    if not area:
        return

    prefs = fn.get_addon_prefs()
    space = area.spaces.active
    key = (window.as_pointer(), area.as_pointer())
    _pending.pop(key, None)
    _closing.pop(key, None)
    if prefs.show_sidebar != 'NONE':
        space.show_region_ui = prefs.show_sidebar == 'SHOW'
    area.tag_redraw()
    if prefs.set_sidebar_tab and space.show_region_ui:
        tab = prefs.sidebar_tab_target.strip() or 'Storytools'
        _queue_tab(window, area, tab)


def set_workspace_sidebar(window, name):
    """Workspace activation finishes after its operator returns, too."""
    _workspaces[window.as_pointer()] = (name, 0)
    _start_timer()


def _apply_pending():
    windows = {w.as_pointer(): w for w in bpy.context.window_manager.windows}
    for key, (name, attempts) in list(_workspaces.items()):
        window = windows.get(key)
        if not window or attempts >= MAX_ATTEMPTS:
            del _workspaces[key]
        elif window.workspace.name == name:
            area = max((a for a in window.screen.areas if a.type == 'VIEW_3D'),
                       key=lambda a: a.width * a.height, default=None)
            if area:
                set_sidebar(area, window)
            del _workspaces[key]
        else:
            _workspaces[key] = (name, attempts + 1)

    for key, (space_pointer, attempts) in list(_closing.items()):
        window = windows.get(key[0])
        area = next((a for a in window.screen.areas if a.as_pointer() == key[1]), None) if window else None
        if (not area or area.type != 'VIEW_3D'
                or area.spaces.active.as_pointer() != space_pointer or attempts >= MAX_ATTEMPTS):
            del _closing[key]
            continue
        area.spaces.active.show_region_ui = False
        area.tag_redraw()
        if not area.spaces.active.show_region_ui:
            del _closing[key]
        else:
            _closing[key] = (space_pointer, attempts + 1)

    for key, (space_pointer, tab, attempts) in list(_pending.items()):
        window = windows.get(key[0])
        area = next((a for a in window.screen.areas if a.as_pointer() == key[1]), None) if window else None
        if (not area or area.type != 'VIEW_3D'
                or area.spaces.active.as_pointer() != space_pointer
                or not area.spaces.active.show_region_ui or attempts >= MAX_ATTEMPTS):
            del _pending[key]
            continue
        sidebar = next((r for r in area.regions if r.type == 'UI'), None)
        if sidebar and sidebar.width > 1:
            try:
                with bpy.context.temp_override(window=window, area=area, region=sidebar):
                    sidebar.active_panel_category = tab
                sidebar.tag_redraw()
                if sidebar.active_panel_category == tab:
                    del _pending[key]
                    continue
            except (AttributeError, RuntimeError, TypeError, ValueError):
                # A newly revealed sidebar can remain read-only until layout.
                pass
        area.tag_redraw()
        _pending[key] = (space_pointer, tab, attempts + 1)
    return INTERVAL if _pending or _closing or _workspaces else None


@persistent
def clear_pending(_dummy=None):
    if bpy.app.timers.is_registered(_apply_pending):
        bpy.app.timers.unregister(_apply_pending)
    _pending.clear()
    _closing.clear()
    _workspaces.clear()


def register():
    bpy.utils.register_class(STORYTOOLS_OT_toggle_sidebar)
    if clear_pending not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(clear_pending)


def unregister():
    clear_pending()
    if clear_pending in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(clear_pending)
    bpy.utils.unregister_class(STORYTOOLS_OT_toggle_sidebar)
