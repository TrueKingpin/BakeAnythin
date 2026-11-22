bl_info = {
    "name": "BakeAnythin - Multi-Material PBR Baker",
    "author": "TrueKingpin",
    "version": (0, 2, 0),
    "doc_url": "https://github.com/TrueKingpin/BakeAnythin",
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > BakeAnythin",
    "description": "Smart UV unwrap and bake selected mesh materials into a unified texture set",
    "category": "UV",
}



# BakeAnythin is a Blender add-on, so Blender provides the bpy module for
# access to scenes, objects, materials, UV maps, images, and bake operators.
import bpy
import os
from bpy.props import IntProperty, FloatProperty, BoolProperty, StringProperty, EnumProperty



# ---------- Helpers ----------

def _selected_mesh(context):
    # Blender's context tells us what the user currently has selected. We only
    # accept mesh objects here because UV maps and texture baking are mesh-based.
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    return obj



def _ensure_uv(obj, mode, margin):
    # A UV map is a 2D layout that tells Blender which part of an image
    # should be painted onto each face of the 3D mesh. Baking needs one.
    """Choose the existing active UV map or create and Smart-UV unwrap a new one."""
    if mode == 'CURRENT':
        if not obj.data.uv_layers:
            raise RuntimeError("Current UV Islands was selected, but this mesh has no UV map. Choose Automatic UV Islands or create a UV map first.")
        uv = obj.data.uv_layers.active or obj.data.uv_layers[0]
        obj.data.uv_layers.active = uv
        return uv

    # Automatic mode always creates a fresh UV map, leaving existing maps intact.
    # This is safer than overwriting an artist's original unwrap.
    name = "BakeAnythinUV"
    index = 1
    while obj.data.uv_layers.get(name) is not None:
        name = f"BakeAnythinUV_{index}"
        index += 1
    uv = obj.data.uv_layers.new(name=name)
    obj.data.uv_layers.active = uv
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(island_margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')
    return uv



def _create_image(name, size, alpha=False):
    # Create a blank image inside Blender's data so the bake operator has a
    # destination. The image starts black; Blender writes baked pixels into it.
    img = bpy.data.images.new(name=name, width=size, height=size, alpha=alpha, float_buffer=False)
    img.generated_color = (0.0, 0.0, 0.0, 1.0)
    return img



def _active_image_nodes(materials, image):
    # Blender writes a bake into the image assigned to the active Image Texture
    # node in each material. We add temporary target nodes for that purpose.
    """Create temporary image nodes and make them active for bake. Returns node records."""
    records = []
    for mat in materials:
        if mat is None:
            continue
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        # Remember the material's previously active node so we can restore it
        # after baking instead of leaving the temporary target selected.
        old_active = nodes.active
        node = nodes.new('ShaderNodeTexImage')
        node.name = "BakeAnythin_TemporaryTarget"
        node.label = "BakeAnythin bake target (temporary)"
        node.image = image
        node.select = True
        nodes.active = node
        records.append((mat, node, old_active))
    return records



def _remove_target_nodes(records):
    # Cleanup counterpart to _active_image_nodes(): remove our temporary nodes
    # and restore each material's previous active node when possible.
    for mat, node, old_active in records:
        nodes = mat.node_tree.nodes
        if node and node.name in nodes:
            nodes.remove(node)
        if old_active and old_active.name in nodes:
            nodes.active = old_active
        else:
            nodes.active = None


def _bake(context, bake_type, image, materials, *, padding=16, color_only=False, normal_space='TANGENT'):
    # Run Blender's bake operator for a standard bake pass (Base Color or Normal).
    # We temporarily adjust bake settings, then restore them in finally so this
    # add-on does not permanently change the user's scene preferences.
    records = _active_image_nodes(materials, image)
    scene = context.scene
    bake = scene.render.bake
    old_use_clear = bake.use_clear
    old_margin = bake.margin
    old_normal_space = bake.normal_space
    old_diffuse_color = bake.use_pass_color
    old_diffuse_direct = bake.use_pass_direct
    old_diffuse_indirect = bake.use_pass_indirect
    try:
        bake.use_clear = True
        bake.margin = padding
        bake.normal_space = normal_space
        # Diffuse Color is used for an unlit Base Color bake: Color is enabled,
        # while Direct and Indirect lighting are disabled to avoid shadows/light.
        if bake_type == 'DIFFUSE':
            bake.use_pass_color = True
            bake.use_pass_direct = False
            bake.use_pass_indirect = False
        bpy.ops.object.bake(type=bake_type, pass_filter={'COLOR'} if bake_type == 'DIFFUSE' else set())
    finally:
        bake.use_clear = old_use_clear
        bake.margin = old_margin
        bake.normal_space = old_normal_space
        bake.use_pass_color = old_diffuse_color
        bake.use_pass_direct = old_diffuse_direct
        bake.use_pass_indirect = old_diffuse_indirect
        _remove_target_nodes(records)


def _bake_value_map(context, obj, materials, image, input_name, padding=16):
    # Metallic and Roughness are scalar shader inputs, not ordinary color bake
    # passes. This helper temporarily routes the chosen input through Emission,
    # which makes its raw value bake as pixels without scene lighting.
    """Bake a Principled input as emission. Temporarily swaps material surface links."""
    records = []
    for mat in materials:
        if mat is None:
            continue
        mat.use_nodes = True
        nt = mat.node_tree
        output = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        principled = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if output is None or principled is None:
            continue
        surface = output.inputs.get('Surface')
        old_links = [(link.from_socket, link.to_socket) for link in nt.links if link.to_socket == surface]
        # Capture the value feeding the requested Principled BSDF input, or its
        # default value if no node is connected. We use that value as emission.
        source_socket = principled.inputs.get(input_name)
        emission = nt.nodes.new('ShaderNodeEmission')
        emission.name = 'BakeAnythin_TemporaryEmission'
        if source_socket and source_socket.is_linked:
            nt.links.new(source_socket.links[0].from_socket, emission.inputs['Color'])
        elif source_socket:
            val = source_socket.default_value
            if isinstance(val, (float, int)):
                emission.inputs['Color'].default_value = (float(val), float(val), float(val), 1.0)
            else:
                try:
                    emission.inputs['Color'].default_value = tuple(val)
                except Exception:
                    emission.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
        for link in old_links:
            nt.links.remove(next((l for l in nt.links if l.from_socket == link[0] and l.to_socket == link[1]), None))
        nt.links.new(emission.outputs['Emission'], surface)
        records.append((mat, output, surface, old_links, emission))

    image_records = _active_image_nodes(materials, image)
    scene = context.scene
    old_clear = scene.render.bake.use_clear
    old_margin = scene.render.bake.margin
    try:
        scene.render.bake.use_clear = True
        scene.render.bake.margin = padding
        bpy.ops.object.bake(type='EMIT')
    finally:
        scene.render.bake.use_clear = old_clear
        scene.render.bake.margin = old_margin
        _remove_target_nodes(image_records)
        for mat, output, surface, old_links, emission in records:
            nt = mat.node_tree
            for link in list(nt.links):
                if link.to_socket == surface:
                    nt.links.remove(link)
            for from_socket, to_socket in old_links:
                nt.links.new(from_socket, to_socket)
            if emission.name in nt.nodes:
                nt.nodes.remove(emission)


def _save_image(image, folder, filename):
    # Ensure the output folder exists, set PNG as the file format, and write
    # the image to disk. filepath_raw is the path used for saving image data.
    os.makedirs(folder, exist_ok=True)
    image.filepath_raw = os.path.join(folder, filename)
    image.file_format = 'PNG'
    image.save()


# ---------- Operator ----------

class BAKEANYTHIN_OT_bake_selected(bpy.types.Operator):
    bl_idname = "bakeanythin.bake_selected"
    bl_label = "Bake Selected Object"
    bl_description = "Smart unwrap and bake a selected mesh's materials into a unified PBR texture set"
    bl_options = {'REGISTER', 'UNDO'}



    def execute(self, context):
        # Operator execute() is the code Blender runs when the user presses
        # the Bake button. This is the main workflow coordinator.
        obj = _selected_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select a mesh object first.")
            return {'CANCELLED'}
        if not obj.data.materials:
            self.report({'ERROR'}, "Selected mesh has no material slots.")
            return {'CANCELLED'}

        scene = context.scene
        materials = list(dict.fromkeys([m for m in obj.data.materials if m is not None]))
        if not materials:
            self.report({'ERROR'}, "No valid materials found on the selected mesh.")
            return {'CANCELLED'}

        # Snapshot scene/object state before making temporary changes. Keeping
        # these values lets us restore the user's workspace after the bake.
        old_engine = scene.render.engine
        old_cycles_samples = scene.cycles.samples if hasattr(scene, 'cycles') else None
        old_active_uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else None
        old_mode = obj.mode
        old_selection = list(context.selected_objects)
        old_active = context.view_layer.objects.active
        size = scene.bakeanythin_resolution
        output_dir = bpy.path.abspath(scene.bakeanythin_output)
        base = bpy.path.clean_name(obj.name)
        margin = scene.bakeanythin_margin
        bake_padding = scene.bakeanythin_bake_margin
        uv_mode = scene.bakeanythin_uv_mode

        created_images = []
        try:
            # Blender bake operators work on the active selected object. Make
            # that state explicit so the bake targets the object we validated.
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            _ensure_uv(obj, uv_mode, margin)
            scene.render.engine = 'CYCLES'
            scene.cycles.samples = max(1, scene.bakeanythin_samples)
            scene.render.bake.use_selected_to_active = False
            scene.render.bake.use_clear = True
            scene.render.bake.margin = bake_padding

            # Base Color: bake only the diffuse color contribution. Direct and
            # indirect lighting are disabled so this texture remains unlit/albedo.
            img = _create_image(base + "_BaseColor", size)
            created_images.append(img)
            _bake(context, 'DIFFUSE', img, materials, padding=bake_padding, color_only=True)
            _save_image(img, output_dir, base + "_BaseColor.png")

            if scene.bakeanythin_metallic:
                img = _create_image(base + "_Metallic", size)
                created_images.append(img)
                _bake_value_map(context, obj, materials, img, 'Metallic', padding=bake_padding)
                _save_image(img, output_dir, base + "_Metallic.png")

            if scene.bakeanythin_roughness:
                img = _create_image(base + "_Roughness", size)
                created_images.append(img)
                _bake_value_map(context, obj, materials, img, 'Roughness', padding=bake_padding)
                _save_image(img, output_dir, base + "_Roughness.png")

            if scene.bakeanythin_normal:
                img = _create_image(base + "_Normal", size)
                created_images.append(img)
                _bake(context, 'NORMAL', img, materials, padding=bake_padding, normal_space='TANGENT')
                _save_image(img, output_dir, base + "_Normal.png")

        except Exception as exc:
            self.report({'ERROR'}, f"BakeAnythin failed: {exc}")
            return {'CANCELLED'}
        finally:
            # Restore render engine, Cycles sample count, prior UV selection,
            # selected objects, active object, and mode to avoid side effects.
            try:
                scene.render.engine = old_engine
                if old_cycles_samples is not None and hasattr(scene, 'cycles'):
                    scene.cycles.samples = old_cycles_samples
                if old_active_uv and obj.data.uv_layers.get(old_active_uv):
                    obj.data.uv_layers.active = obj.data.uv_layers.get(old_active_uv)
                bpy.ops.object.select_all(action='DESELECT')
                for selected in old_selection:
                    if selected and selected.name in bpy.data.objects:
                        selected.select_set(True)
                context.view_layer.objects.active = old_active if old_active and old_active.name in bpy.data.objects else obj
                if old_mode != 'OBJECT' and obj.select_get():
                    bpy.ops.object.mode_set(mode=old_mode)
            except Exception:
                pass

        self.report({'INFO'}, f"Baked textures saved to: {output_dir}")
        return {'FINISHED'}



# ---------- UI ----------

class BAKEANYTHIN_PT_panel(bpy.types.Panel):
    bl_label = "BakeAnythin"
    bl_idname = "BAKEANYTHIN_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BakeAnythin"

    def draw(self, context):
        # draw() builds the sidebar UI. Blender redraws this panel as needed,
        # and each prop() displays a Scene setting that the operator reads.
        layout = self.layout
        scene = context.scene
        col = layout.column(align=True)
        col.label(text="Selected mesh → unified texture set")
        col.separator()
        col.prop(scene, "bakeanythin_uv_mode")
        if scene.bakeanythin_uv_mode == 'AUTOMATIC':
            col.prop(scene, "bakeanythin_margin")
        col.prop(scene, "bakeanythin_resolution")
        col.prop(scene, "bakeanythin_output")
        col.prop(scene, "bakeanythin_bake_margin")
        col.prop(scene, "bakeanythin_samples")
        col.separator()
        col.label(text="Bake Maps")
        col.prop(scene, "bakeanythin_metallic")
        col.prop(scene, "bakeanythin_roughness")
        col.prop(scene, "bakeanythin_normal")
        col.separator()
        col.operator("bakeanythin.bake_selected", icon='RENDER_STILL', text="BAKE SELECTED")
        col.separator()
        col.label(text="V0.2: Base Color, Metallic, Roughness, Normal")



classes = (
    BAKEANYTHIN_OT_bake_selected,
    BAKEANYTHIN_PT_panel,
)



def register():
    # Blender calls register() when enabling the add-on. Register classes first,
    # then attach settings to Scene so they appear in the panel and persist.
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bakeanythin_uv_mode = EnumProperty(
        name="UV Islands",
        description="Choose whether BakeAnythin creates a new UV map or uses the current active UV map",
        items=[
            ('AUTOMATIC', "Automatic UV Islands", "Create a new UV map using Smart UV Project"),
            ('CURRENT', "Current UV Islands", "Use the active existing UV map without modifying it"),
        ],
        default='AUTOMATIC',
    )
    bpy.types.Scene.bakeanythin_resolution = IntProperty(
        name="Resolution", default=2048, min=256, max=8192,
        description="Square resolution for each baked texture",
    )
    bpy.types.Scene.bakeanythin_output = StringProperty(
        name="Output Folder", default="//BakeAnythin/", subtype='DIR_PATH',
        description="Folder where BakeAnythin writes its texture images",
    )
    bpy.types.Scene.bakeanythin_margin = FloatProperty(
        name="UV Island Margin", default=0.04, min=0.0, max=0.25,
        description="Spacing between UV islands during Smart UV Project (UV space)",
        precision=3,
    )
    bpy.types.Scene.bakeanythin_bake_margin = IntProperty(
        name="Bake Padding (px)", default=16, min=0, max=128,
        description="Pixels Blender extends baked colors beyond UV island edges to reduce seams",
    )
    bpy.types.Scene.bakeanythin_samples = IntProperty(
        name="Cycles Samples", default=16, min=1, max=4096,
        description="Cycles samples used during baking",
    )
    bpy.types.Scene.bakeanythin_metallic = BoolProperty(name="Metallic", default=True)
    bpy.types.Scene.bakeanythin_roughness = BoolProperty(name="Roughness", default=True)
    bpy.types.Scene.bakeanythin_normal = BoolProperty(name="Normal", default=True)


def unregister():
    # Blender calls unregister() when disabling/removing the add-on. Remove the
    # Scene properties and registered classes to leave Blender cleanly.
    del bpy.types.Scene.bakeanythin_uv_mode
    del bpy.types.Scene.bakeanythin_resolution
    del bpy.types.Scene.bakeanythin_output
    del bpy.types.Scene.bakeanythin_margin
    del bpy.types.Scene.bakeanythin_bake_margin
    del bpy.types.Scene.bakeanythin_samples
    del bpy.types.Scene.bakeanythin_metallic
    del bpy.types.Scene.bakeanythin_roughness
    del bpy.types.Scene.bakeanythin_normal
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)



if __name__ == "__main__":
    register()
