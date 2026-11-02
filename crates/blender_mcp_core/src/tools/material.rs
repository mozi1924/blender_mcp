// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn manage_material(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy

def hex_to_rgba(hex_str):
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 6:
        r = int(hex_str[0:2], 16) / 255.0
        g = int(hex_str[2:4], 16) / 255.0
        b = int(hex_str[4:6], 16) / 255.0
        return [r, g, b, 1.0]
    elif len(hex_str) == 8:
        r = int(hex_str[0:2], 16) / 255.0
        g = int(hex_str[2:4], 16) / 255.0
        b = int(hex_str[4:6], 16) / 255.0
        a = int(hex_str[6:8], 16) / 255.0
        return [r, g, b, a]
    return [1.0, 1.0, 1.0, 1.0]

ALIASES = {
    'color': 'basecolor',
    'basecolor': 'basecolor',
    'transmission': 'transmissionweight',
    'coat': 'coatweight',
    'sheen': 'sheenweight',
    'subsurface': 'subsurfaceweight',
    'thinfilm': 'thinfilmthickness',
    'emission': 'emissioncolor',
    'specular': 'speculariorlevel',
}

def apply_pbr_to_bsdf(bsdf, pbr_dict):
    norm_inputs = {}
    for inp in bsdf.inputs:
        norm = inp.name.lower().replace(' ', '').replace('_', '')
        norm_inputs[norm] = inp

    updated = []
    for k, v in pbr_dict.items():
        if v is None:
            continue
        clean_k = k.lower().replace(' ', '').replace('_', '')
        clean_k = ALIASES.get(clean_k, clean_k)
        inp = norm_inputs.get(clean_k)
        if not inp:
            # Fuzzy substring matching
            for n, candidate in norm_inputs.items():
                if clean_k in n or n in clean_k:
                    inp = candidate
                    break
        if inp:
            try:
                if inp.type in ('RGBA', 'VECTOR'):
                    if isinstance(v, str):
                        c = hex_to_rgba(v)
                    elif isinstance(v, (list, tuple)):
                        c = list(v) + [1.0] if len(v) == 3 else list(v)
                    else:
                        c = [1.0, 1.0, 1.0, 1.0]
                    inp.default_value = c
                elif inp.type == 'VALUE':
                    inp.default_value = float(v)
                elif inp.type == 'INT':
                    inp.default_value = int(v)
                elif inp.type == 'BOOLEAN':
                    inp.default_value = bool(v)
                updated.append(inp.name)
            except Exception as ex:
                print(f"Warning: could not set socket {inp.name}={v}: {ex}")
    return updated

def ensure_principled_bsdf(mat):
    if not mat.node_tree:
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf:
        bsdf = mat.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
        output = next((n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if not output:
            output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
        mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return bsdf

def run_material(args):
    obj_name = args.get("object_name")
    if not obj_name:
        return {"status": "error", "message": "Argument 'object_name' is required"}

    obj = bpy.data.objects.get(obj_name)
    if not obj:
        return {"status": "error", "message": f"Object '{obj_name}' not found"}

    if not hasattr(obj, "material_slots"):
        return {"status": "error", "message": f"Object '{obj_name}' ({obj.type}) does not support material slots"}

    action = args.get("action", "create_and_assign").lower()
    mat_name = args.get("material_name")
    slot_arg = args.get("slot_index")

    # 1. Inspect action: return detailed breakdown of material slots and Principled PBR values
    if action == "inspect":
        slots_data = []
        for idx, slot in enumerate(obj.material_slots):
            s_info = {
                "slot_index": idx,
                "material_name": slot.material.name if slot.material else None,
                "link": slot.link,
            }
            if slot.material and slot.material.node_tree:
                bsdf = next((n for n in slot.material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if bsdf:
                    pbr_map = {}
                    for inp in bsdf.inputs:
                        if not inp.is_linked:
                            if inp.type in ('VALUE', 'INT', 'BOOLEAN'):
                                pbr_map[inp.name] = round(inp.default_value, 4) if isinstance(inp.default_value, float) else inp.default_value
                            elif inp.type in ('RGBA', 'VECTOR'):
                                pbr_map[inp.name] = [round(x, 4) for x in inp.default_value]
                    s_info["principled_pbr"] = pbr_map
            slots_data.append(s_info)

        return {
            "status": "ok",
            "object_name": obj.name,
            "material_slots_count": len(slots_data),
            "material_slots": slots_data
        }

    # 2. Remove slot action
    if action == "remove_slot":
        if slot_arg is None:
            return {"status": "error", "message": "Argument 'slot_index' is required for action 'remove_slot'"}
        try:
            slot_idx = int(slot_arg)
            if 0 <= slot_idx < len(obj.material_slots):
                bpy.ops.ed.undo_push(message="MCP Remove Material Slot")
                obj.active_material_index = slot_idx
                # Select object and remove slot operator
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.material_slot_remove()
                return {"status": "ok", "message": f"Removed material slot {slot_idx} from '{obj.name}'"}
            else:
                return {"status": "error", "message": f"Slot index {slot_idx} out of range (0..{len(obj.material_slots)-1})"}
        except Exception as ex:
            return {"status": "error", "message": f"Failed to remove slot: {ex}"}

    bpy.ops.ed.undo_push(message="MCP Manage Material")

    # Helper to assign material to the requested slot on obj
    def assign_to_slot(mat_obj):
        if slot_arg in ("new", "append"):
            if hasattr(obj.data, "materials"):
                obj.data.materials.append(mat_obj)
            else:
                slot = obj.material_slots.new()
                slot.material = mat_obj
            return len(obj.material_slots) - 1

        target_idx = 0
        if slot_arg is not None:
            try:
                target_idx = int(slot_arg)
            except ValueError:
                target_idx = 0

        if hasattr(obj.data, "materials"):
            while len(obj.material_slots) <= target_idx:
                obj.data.materials.append(None)
            obj.material_slots[target_idx].material = mat_obj
        else:
            if len(obj.material_slots) <= target_idx:
                slot = obj.material_slots.new()
                slot.material = mat_obj
            else:
                obj.material_slots[target_idx].material = mat_obj
        return target_idx

    # Collect incoming PBR parameters from both 'pbr_properties' dict and top-level convenience args
    incoming_pbr = dict(args.get("pbr_properties", {}))
    for key in [
        "base_color", "color", "metallic", "roughness", "ior", "alpha",
        "transmission", "transmission_weight", "coat", "coat_weight", "coat_roughness",
        "coat_ior", "coat_tint", "sheen", "sheen_weight", "sheen_roughness", "sheen_tint",
        "subsurface", "subsurface_weight", "subsurface_radius", "subsurface_scale", "subsurface_ior",
        "thin_film", "thin_film_thickness", "thin_film_ior", "emission_color", "emission",
        "emission_strength", "specular", "specular_ior_level", "specular_tint", "diffuse_roughness",
        "thin_wall"
    ]:
        if key in args and key not in incoming_pbr:
            incoming_pbr[key] = args[key]

    # 3. Action: assign_existing
    if action == "assign_existing":
        if not mat_name or mat_name not in bpy.data.materials:
            return {"status": "error", "message": f"Material '{mat_name}' does not exist"}
        mat = bpy.data.materials[mat_name]
        slot_idx = assign_to_slot(mat)
        updated_sockets = []
        if incoming_pbr and mat.node_tree:
            bsdf = ensure_principled_bsdf(mat)
            updated_sockets = apply_pbr_to_bsdf(bsdf, incoming_pbr)
        return {
            "status": "ok",
            "message": f"Assigned material '{mat.name}' to '{obj.name}' (slot {slot_idx})",
            "material": mat.name,
            "slot_index": slot_idx,
            "updated_sockets": updated_sockets
        }

    # 4. Action: update_principled
    elif action == "update_principled":
        target_slot_idx = 0
        if slot_arg is not None and slot_arg not in ("new", "append"):
            try:
                target_slot_idx = int(slot_arg)
            except ValueError:
                target_slot_idx = 0

        mat = None
        if len(obj.material_slots) > target_slot_idx and obj.material_slots[target_slot_idx].material:
            mat = obj.material_slots[target_slot_idx].material
        elif mat_name and mat_name in bpy.data.materials:
            mat = bpy.data.materials[mat_name]

        if not mat:
            return {"status": "error", "message": f"No active material found to update on '{obj.name}' (slot {target_slot_idx})"}

        bsdf = ensure_principled_bsdf(mat)
        updated_sockets = apply_pbr_to_bsdf(bsdf, incoming_pbr)
        return {
            "status": "ok",
            "message": f"Updated Principled BSDF on material '{mat.name}' (slot {target_slot_idx})",
            "material": mat.name,
            "slot_index": target_slot_idx,
            "updated_sockets": updated_sockets
        }

    # 5. Action: create_and_assign (default)
    else:
        name = mat_name or f"{obj.name}_Mat"
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        bsdf = ensure_principled_bsdf(mat)
        updated_sockets = apply_pbr_to_bsdf(bsdf, incoming_pbr)
        slot_idx = assign_to_slot(mat)

        return {
            "status": "ok",
            "message": f"Created & assigned material '{mat.name}' to '{obj.name}' (slot {slot_idx})",
            "material": mat.name,
            "slot_index": slot_idx,
            "updated_sockets": updated_sockets
        }
"#;

    match call_python_tool(py, code, "run_material", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Material operation failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during material operation: {}", e)),
    }
}
