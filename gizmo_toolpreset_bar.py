# SPDX-License-Identifier: GPL-3.0-or-later

# Gizmo doc

import bpy
import gpu
from bpy.types import (
    Operator,
    GizmoGroup,
    Gizmo
    )

from mathutils import Matrix, Vector
from gpu_extras.batch import batch_for_shader

from . import fn


_capsule_shader = None
_capsule_batch = None
USE_CAPSULE_UI = bpy.app.version >= (5, 2, 0)
_activated_presets = {}


def preset_signature(props):
    """Identify the preset selected by either a shortcut or a bar button."""
    return (props.name, props.order, props.mode, props.tool, props.brush,
            props.layer, props.material, props.stroke_type)


def drawing_state(context, check_material=False):
    """Capture the state after a preset runs, to invalidate its highlight on later changes."""
    ob = context.object
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    layer = ob.data.layers.active if ob and ob.type == 'GREASEPENCIL' else None
    paint = context.tool_settings.gpencil_paint if context.mode == 'PAINT_GREASE_PENCIL' else None
    brush = paint.brush if paint else None
    material = ob.active_material if check_material and ob and ob.type == 'GREASEPENCIL' else None
    stroke_type = brush.gpencil_settings.stroke_type if brush and brush.gpencil_settings else None
    return (context.scene.as_pointer(), ob.as_pointer() if ob else None, context.mode,
            tool.idname if tool else '', layer.name if layer else '',
            brush.as_pointer() if brush else None, stroke_type,
            material.as_pointer() if material else None)


def activate_preset(context, props):
    """Called by the shared operator, including when invoked from a keymap."""
    set_activated_signature(context, preset_signature(props))


def set_activated_signature(context, signature):
    """Update the bar after selecting or undoing a preset."""
    if context.window is None:
        return
    window_key = context.window.as_pointer()
    if signature is None:
        _activated_presets.pop(window_key, None)
    else:
        _activated_presets[window_key] = (
            signature, drawing_state(context, check_material=bool(signature[6])))
    for area in context.window.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def active_preset_signature(context):
    activation = _activated_presets.get(context.window.as_pointer())
    if activation and activation[1] == drawing_state(context, check_material=bool(activation[0][6])):
        return activation[0]
    return None


def active_preset_button_index(signature, button_props):
    """Find the visible button even if Blender refreshed the user keymap after setup."""
    if signature is None:
        return None

    for i, props in enumerate(button_props):
        if preset_signature(props) == signature:
            return i

    # The user keyconfig may finish loading after the gizmo group's setup. Its
    # saved RNA properties can then be stale, while shortcuts use the new ones.
    current_props = [kmi.properties for _km, kmi in fn.get_tool_presets_keymap()
                     if kmi.active and kmi.properties.show]
    if len(current_props) == len(button_props):
        for i, props in enumerate(current_props):
            if preset_signature(props) == signature:
                return i
    return None


def capsule_from_gizmos(gizmos, px_scale, backdrop_size):
    positions = [gz.matrix_basis.to_translation() for gz in gizmos]
    min_x = min(pos.x for pos in positions)
    max_x = max(pos.x for pos in positions)
    min_y = min(pos.y for pos in positions)
    max_y = max(pos.y for pos in positions)
    center = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    width = ((max_x - min_x) / px_scale) + (backdrop_size * 2)
    height = ((max_y - min_y) / px_scale) + (backdrop_size * 2.4)
    return center, width, height


def capsule_shader_ensure():
    global _capsule_shader, _capsule_batch
    if _capsule_shader is not None:
        return _capsule_shader, _capsule_batch

    interface = gpu.types.GPUStageInterfaceInfo("storytools_capsule_interface")
    interface.smooth('VEC2', "local_pos")

    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.push_constant('VEC2', "center")
    shader_info.push_constant('VEC2', "viewport_size")
    shader_info.push_constant('VEC2', "half_size")
    shader_info.push_constant('FLOAT', "radius")
    shader_info.push_constant('FLOAT', "outline_width")
    shader_info.push_constant('VEC4', "fill_color")
    shader_info.push_constant('VEC4', "outline_color")
    shader_info.vertex_in(0, 'VEC2', "position")
    shader_info.vertex_out(interface)
    shader_info.fragment_out(0, 'VEC4', "frag_color")
    shader_info.vertex_source(
        """
        void main()
        {
          vec2 draw_half_size = half_size + vec2(2.0);
          local_pos = position * draw_half_size;
          vec2 pixel_pos = center + local_pos;
          vec2 ndc = (pixel_pos / viewport_size) * 2.0 - 1.0;
          gl_Position = vec4(ndc, 0.0, 1.0);
        }
        """
    )
    shader_info.fragment_source(
        """
        void main()
        {
          vec2 inner_size = half_size - vec2(radius);
          vec2 q = abs(local_pos) - inner_size;
          float distance = length(max(q, vec2(0.0)))
                         + min(max(q.x, q.y), 0.0) - radius;

          float outer_aa = max(fwidth(distance), 0.5);
          float inner_aa = max(fwidth(distance) * 0.5, 0.25);
          float outer_coverage = 1.0 - smoothstep(
              -outer_aa, outer_aa, distance);
          float fill_coverage = 1.0 - smoothstep(
              -inner_aa, inner_aa, distance + outline_width);

          vec4 color = mix(outline_color, fill_color, fill_coverage);
          frag_color = vec4(color.rgb, color.a * outer_coverage);
        }
        """
    )

    _capsule_shader = gpu.shader.create_from_info(shader_info)
    _capsule_batch = batch_for_shader(
        _capsule_shader,
        'TRI_STRIP',
        {"position": ((-1, -1), (1, -1), (-1, 1), (1, 1))},
    )
    return _capsule_shader, _capsule_batch


def draw_capsule(context, center, width, height, opacity=0.3, color=(0.0, 0.0, 0.0)):
    shader, batch = capsule_shader_ensure()
    ui_scale = context.preferences.system.ui_scale
    half_size = (width * ui_scale / 2, height * ui_scale / 2)

    shader.uniform_float("center", center)
    shader.uniform_float("viewport_size", (context.region.width, context.region.height))
    shader.uniform_float("half_size", half_size)
    shader.uniform_float("radius", min(half_size))
    shader.uniform_float("outline_width", context.preferences.system.pixel_size)
    shader.uniform_float("fill_color", (*color, opacity))
    shader.uniform_float("outline_color", (*color, min(opacity * 4 / 3, 1.0)))

    gpu.state.blend_set('ALPHA')
    try:
        batch.draw(shader)
    finally:
        gpu.state.blend_set('NONE')


class STORYTOOLS_GT_presetbar_background(Gizmo):
    bl_idname = "STORYTOOLS_GT_presetbar_background"

    __slots__ = ("capsule",)

    def draw(self, context):
        prefs = fn.get_addon_prefs()
        if self.capsule and prefs.presetbar_background_opacity:
            draw_capsule(context, *self.capsule,
                         prefs.presetbar_background_opacity,
                         prefs.presetbar_background_color)

    def test_select(self, context, location):
        return -1


class STORYTOOLS_GGT_toolpreset_bar(GizmoGroup):
    # bl_idname = "STORYTOOLS_GGT_toolbar"
    bl_label = "Story Tool Preset Bar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        if not context.space_data.show_gizmo:
            return False
        # return 'GREASEPENCIL' in context.mode and not fn.is_minimap_viewport(context)
        return context.object and context.object.type == 'GREASEPENCIL' and not fn.is_minimap_viewport(context)

    def setup(self, context):

        self.tool_preset_gizmos = []
        self.tool_preset_props = []

        ## Object Pan
        user_keymaps = bpy.context.window_manager.keyconfigs.user.keymaps
        
        ## List available icons to use fallback
        # available_icons = [i.identifier for i in bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items]

        ## List all set_draw_tools keymap
        toolpreset_kmis = fn.get_tool_presets_keymap()

        # for km in user_keymaps:
        #     for kmi in reversed(km.keymap_items):
        #         if kmi.idname == 'storytools.set_draw_tool':

        for _km, kmi in toolpreset_kmis:
            props = kmi.properties
            if not kmi.active or not props.show:
                continue
            gz = self.gizmos.new("GIZMO_GT_button_2d")
            fn.set_gizmo_settings(gz, icon=props.icon, alpha=0, alpha_highlight=0.6) # , alpha=0.4, alpha_highlight=0.5

            op = gz.target_set_operator("storytools.set_draw_tool")
            op.name = props.name
            op.order = props.order
            op.mode = props.mode
            op.tool = props.tool
            op.layer = props.layer
            op.material = props.material
            op.brush = props.brush
            op.stroke_type = props.stroke_type
            op.description = props.description
            op.shortcut = kmi.to_string() # Shortcut text for description
            self.tool_preset_gizmos.append(gz)
            self.tool_preset_props.append(props)

        if USE_CAPSULE_UI:
            for gz in self.tool_preset_gizmos:
                gz.draw_options = set()
            # Gizmos draw in reverse creation order, so the capsule goes behind the icons.
            self.background_gizmo = self.gizmos.new("STORYTOOLS_GT_presetbar_background")
            self.background_gizmo.capsule = None

    def draw_prepare(self, context):
        prefs = fn.get_addon_prefs()
        settings = context.scene.storytools_settings
        
        # icon_size = prefs.toolbar_icon_bounds
        gap_size = prefs.presetbar_gap_size
        backdrop_size = prefs.presetbar_backdrop_size
        
        section_separator = 20
        px_scale = context.preferences.system.ui_scale

        ## Toggle on/off with same session as bottom control bar
        for gz in self.gizmos:
            gz.hide = not settings.show_session_toolbar
        if not settings.show_session_toolbar:
            return
        
        region = context.region
        count = len(self.tool_preset_gizmos)

        ## Using only direct offsetn
        self.bar_width = (count - 1) * (gap_size * px_scale) + (section_separator * 2) * px_scale
        # self.bar_width = (count - 1) * (gap_size * px_scale)
        
        ## Need to set upper margin
        vertical_pos = region.height - (prefs.presetbar_margin * px_scale) - fn.get_header_margin(context, bottom=False, overlap=False)
        left_pos = region.width / 2 - self.bar_width / 2
        next_pos = gap_size * px_scale

        selected_preset = active_preset_signature(context)
        selected_index = active_preset_button_index(selected_preset, self.tool_preset_props)
        active_blue = prefs.active_blue_gz_color if USE_CAPSULE_UI else prefs.active_gz_color
        # Blender's 16px SVG icons truncate their bottom-left position to integers,
        # while the backdrop uses the floating-point gizmo center. Snap the icon
        # origin, accounting for UI scale, so both keep the same rendered center.
        icon_half_size = 8.0 * px_scale

        for i, gz in enumerate(self.tool_preset_gizmos):
            gz.scale_basis = backdrop_size
            active = i == selected_index
            gz.draw_options = ({'BACKDROP'} if active else set()) if USE_CAPSULE_UI else {'BACKDROP', 'OUTLINE'}
            gz.alpha = 1.0 if active or USE_CAPSULE_UI else prefs.presetbar_background_opacity
            gz.alpha_highlight = 1.0 if active else 0.6
            gz.color = active_blue if active else (0.4, 0.4, 0.4)
            gz.color_highlight = active_blue if active else (0.5, 0.5, 0.5)

            ## Matrix world is readonly
            button_x = left_pos + (i * next_pos)
            button_y = vertical_pos
            if USE_CAPSULE_UI:
                button_x = round(button_x - icon_half_size) + icon_half_size
                button_y = round(button_y - icon_half_size) + icon_half_size
            gz.matrix_basis = Matrix.Translation((button_x, button_y, 0))

        if USE_CAPSULE_UI:
            self.background_gizmo.capsule = (
                capsule_from_gizmos(self.tool_preset_gizmos, px_scale, backdrop_size)
                if self.tool_preset_gizmos else None
            )


classes=(
    (STORYTOOLS_GT_presetbar_background, STORYTOOLS_GGT_toolpreset_bar)
    if USE_CAPSULE_UI else (STORYTOOLS_GGT_toolpreset_bar,)
)

def register():
    if not fn.get_addon_prefs().active_presetbar:
        return
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    from .prefs_io_core import is_class_registered
    for cls in reversed(classes):
        if is_class_registered(cls):
            bpy.utils.unregister_class(cls)
