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


def draw_capsule(context, center, width, height):
    shader, batch = capsule_shader_ensure()
    ui_scale = context.preferences.system.ui_scale
    half_size = (width * ui_scale / 2, height * ui_scale / 2)

    shader.uniform_float("center", center)
    shader.uniform_float("viewport_size", (context.region.width, context.region.height))
    shader.uniform_float("half_size", half_size)
    shader.uniform_float("radius", min(half_size))
    shader.uniform_float("outline_width", context.preferences.system.pixel_size)
    shader.uniform_float("fill_color", (0.0, 0.0, 0.0, 0.3))
    shader.uniform_float("outline_color", (0.0, 0.0, 0.0, 0.4))

    gpu.state.blend_set('ALPHA')
    try:
        batch.draw(shader)
    finally:
        gpu.state.blend_set('NONE')


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
            # op.mode = props.mode # Default Keymap currently limited to Paint mode
            op.tool = props.tool
            op.layer = props.layer
            op.material = props.material
            op.brush = props.brush
            op.stroke_type = props.stroke_type
            op.description = props.description
            op.shortcut = kmi.to_string() # Shortcut text for description
            self.tool_preset_gizmos.append(gz)

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
        count = len(self.gizmos)

        ## Using only direct offsetn
        self.bar_width = (count - 1) * (gap_size * px_scale) + (section_separator * 2) * px_scale
        # self.bar_width = (count - 1) * (gap_size * px_scale)
        
        ## Need to set upper margin
        vertical_pos = region.height - (prefs.presetbar_margin * px_scale) - fn.get_header_margin(context, bottom=False, overlap=False)
        left_pos = region.width / 2 - self.bar_width / 2
        next_pos = gap_size * px_scale

        for i, gz in enumerate(self.tool_preset_gizmos):
            gz.scale_basis = backdrop_size
            gz.color = (0.4, 0.4, 0.4)
            gz.color_highlight = (0.5, 0.5, 0.5)

            ## Matrix world is readonly
            gz.matrix_basis = Matrix.Translation((left_pos + (i * next_pos), vertical_pos, 0))


classes=(
    STORYTOOLS_GGT_toolpreset_bar,
)

def register():
    if not fn.get_addon_prefs().active_presetbar:
        return
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    if not fn.get_addon_prefs().active_presetbar:
        return
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
