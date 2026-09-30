import bpy
from pathlib import Path

from .. import fn
from .sidebar_setup import set_workspace_sidebar

def get_storyboarding_startup_path():
    """Get the path of the startup file for storyboarding workspace"""

    ## Directly in system path:
    # Path(bpy.utils.resource_path('SYSTEM'), 'scripts', 'startup', 'bl_app_templates_system', 'Storyboarding', 'startup.blend')
    
    ## Over all valid path
    for template_root_path in bpy.utils.app_template_paths():
        template_path = Path(template_root_path, 'Storyboarding', 'startup.blend')
        if template_path.exists():
            return template_path

def activate_workspace(name='Storyboarding', filepath=None, context=None):
    """Activate workspace by workspace name
    filepath: if specified, fetch the workspace from this path
    """

    if context is None:
        context = bpy.context

    # if context.window.workspace.name == name:
    #     print(f'Already in {name} workspace')
    #     return

    if (searched_wkspace := bpy.data.workspaces.get(name)):
        context.window.workspace = searched_wkspace

    else:
        # Same name with spaces as underscore
        if filepath is None:    
            filepath = get_storyboarding_startup_path()
        
        ret = bpy.ops.workspace.append_activate(idname=name, filepath=str(filepath))
        if ret != {'FINISHED'}:
            print(f'Could not found "{name}" at {filepath}')
            message = [f'Could not found "{name}" workspace at:',
                    str(filepath)]
            fn.show_message_box(_message=message, _title='Workspace Not found', _icon='ERROR')

    return context.window.workspace

## Load directly a single workspace
class STORYTOOLS_OT_set_storyboard_workspace(bpy.types.Operator):
    bl_idname = "storytools.set_storyboard_workspace"
    bl_label = 'Set Storyboard Workspace'
    bl_description = "Set storyboarding workspace"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        # ret = bpy.ops.workspace.append_activate(idname=name, filepath=str(filepath))
        activate_workspace(context=context)

        set_workspace_sidebar(context.window, 'Storyboarding')
        return {"FINISHED"}

classes = (STORYTOOLS_OT_set_storyboard_workspace,)

def register(): 
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
