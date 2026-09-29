# SPDX-License-Identifier: GPL-3.0-or-later

"""Restore workspace tool and brush when a tool preset is undone or redone.

Blender's GP undo restores the drawing/layer but not the active workspace tool
or brush asset. A marker on the GP datablock follows the preset's undo step;
the corresponding non-undoable UI state is kept in memory for this session.
"""

from uuid import uuid4

import bpy

from . import fn


PRESET_STEP_KEY = '_storytools_preset_undo_step'
_transitions = {}
_step_before_undo = None


def capture_state(context):
    ob = context.object
    paint = context.tool_settings.gpencil_paint
    brush = paint.brush if paint else None
    layer = ob.data.layers.active
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    return {
        'mode': context.mode,
        'tool': tool.idname if tool else '',
        'layer': layer.name if layer else '',
        'material': ob.active_material.name if ob.active_material else '',
        'brush_ref': fn.serialize_brush_reference(paint) if paint else '',
        'brush_name': brush.name if brush else '',
        'stroke_type': brush.gpencil_settings.stroke_type if brush and brush.gpencil_settings else '',
    }


def record_preset(context, before, preset, previous_signature):
    """Called after a successful preset switch, inside its UNDO-enabled operator."""
    from .gizmo_toolpreset_bar import preset_signature
    gp = context.object.data
    previous_step = gp.get(PRESET_STEP_KEY, '')
    step = uuid4().hex
    _transitions[step] = (previous_step, before, capture_state(context),
                          previous_signature, preset_signature(preset))
    gp[PRESET_STEP_KEY] = step


def undo_redo_pre():
    global _step_before_undo
    ob = bpy.context.object
    _step_before_undo = (
        (ob.name, ob.data.name, ob.data.get(PRESET_STEP_KEY, ''))
        if ob and ob.type == 'GREASEPENCIL' else None
    )


def _restore_state(context, state):
    restored = True
    if state['mode'] != context.mode:
        mode = 'EDIT' if state['mode'] == 'EDIT_GREASE_PENCIL' else state['mode']
        try:
            bpy.ops.object.mode_set(mode=mode)
        except RuntimeError as exc:
            print(f'Storytools: Could not restore preset mode {mode}: {exc}')
            restored = False
    if state['tool']:
        try:
            bpy.ops.wm.tool_set_by_id(name=state['tool'])
        except RuntimeError as exc:
            print(f'Storytools: Could not restore preset tool {state["tool"]}: {exc}')
            restored = False
    brush_restored = state['brush_ref'] and fn.set_brush_by_reference(state['brush_ref'])
    if not brush_restored and state['brush_name']:
        brush = bpy.data.brushes.get(state['brush_name'])
        if brush and context.tool_settings.gpencil_paint:
            context.tool_settings.gpencil_paint.brush = brush
        else:
            restored = False
    if state['stroke_type'] and bpy.app.version >= (5, 1, 0):
        fn.set_stroke_type(fn.get_active_gp_brush(context), state['stroke_type'])
    if state['layer']:
        layer = context.object.data.layers.active
        if not layer or layer.name != state['layer']:
            fn.suppress_brush_sync()
        fn.set_layer_by_name(context.object, state['layer'])
        layer = context.object.data.layers.active
        restored &= bool(layer and layer.name == state['layer'])
    if state['material']:
        fn.set_material_by_name(context.object, state['material'])
        material = context.object.active_material
        restored &= bool(material and material.name == state['material'])
    return restored


def undo_redo_post():
    """Return True if a preset step changed and its saved state was restored."""
    global _step_before_undo
    previous = _step_before_undo
    _step_before_undo = None
    ob = bpy.context.object
    if not previous or not ob or ob.type != 'GREASEPENCIL':
        return False
    if (ob.name, ob.data.name) != previous[:2]:
        return False

    old_step = previous[2]
    new_step = ob.data.get(PRESET_STEP_KEY, '')
    if old_step == new_step:
        return False  # A stroke was undone; leave the selected tool/brush alone.

    if old_step in _transitions and _transitions[old_step][0] == new_step:
        state = _transitions[old_step][1]  # Undo the preset switch.
        signature = _transitions[old_step][3]
    elif new_step in _transitions and _transitions[new_step][0] == old_step:
        state = _transitions[new_step][2]  # Redo the preset switch.
        signature = _transitions[new_step][4]
    else:
        return False

    window = bpy.context.window
    if not window:
        window = next((win for win in bpy.context.window_manager.windows
                       if win.view_layer.objects.active == ob), None)
    area = next((area for area in window.screen.areas if area.type == 'VIEW_3D'), None) if window else None
    if not area:
        return False
    region = next((region for region in area.regions if region.type == 'WINDOW'), None)
    if not region:
        return False
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            restored = _restore_state(bpy.context, state)
            from .gizmo_toolpreset_bar import set_activated_signature
            set_activated_signature(bpy.context, signature if restored else None)
    except RuntimeError as exc:
        print(f'Storytools: Could not restore preset after undo/redo: {exc}')
        return False
    area.tag_redraw()
    return restored


def clear():
    global _step_before_undo
    _step_before_undo = None
    _transitions.clear()
