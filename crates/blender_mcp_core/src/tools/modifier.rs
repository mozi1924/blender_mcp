// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn manage_modifier(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy

def run_modifier(args):
    action = args.get("action", "add").lower()
    mod_type = args.get("modifier_type", "")
    if isinstance(mod_type, str):
        mod_type = mod_type.upper().strip()

    # 1. Search action: query catalog of all available Blender modifiers
    if action == "search":
        query = (args.get("query") or "").lower().strip()
        enum_prop = bpy.types.Modifier.bl_rna.properties.get("type")
        items = []
        if enum_prop:
            for it in enum_prop.enum_items:
                if not it.identifier:
                    continue
                score = 0
                id_l = it.identifier.lower()
                name_l = it.name.lower()
                desc_l = it.description.lower() if it.description else ""
                if not query:
                    score = 1
                elif query in id_l:
                    score += 10
                elif query in name_l:
                    score += 5
                elif query in desc_l:
                    score += 1

                if score > 0:
                    items.append({
                        "identifier": it.identifier,
                        "name": it.name,
                        "description": it.description,
                        "score": score
                    })
        items.sort(key=lambda x: x["score"], reverse=True)
        return {
            "status": "ok",
            "count": len(items),
            "modifiers": [{"identifier": x["identifier"], "name": x["name"], "description": x["description"]} for x in items]
        }

    # 2. Query type: introspect RNA properties, enum options, and pointer types
    if action == "query_type":
        if not mod_type:
            return {"status": "error", "message": "Argument 'modifier_type' is required for action 'query_type'"}

        enum_prop = bpy.types.Modifier.bl_rna.properties.get("type")
        valid_items = {it.identifier: it for it in enum_prop.enum_items if it.identifier} if enum_prop else {}
        
        # Match by identifier or name
        if mod_type not in valid_items:
            for it in valid_items.values():
                if it.name.lower() == mod_type.lower():
                    mod_type = it.identifier
                    break

        if mod_type not in valid_items:
            return {"status": "error", "message": f"Unknown modifier type '{mod_type}'. Use action 'search' to list available types."}

        # Introspect properties by instantiating a temporary modifier
        temp_mesh = bpy.data.meshes.new("__mcp_tmp_mesh__")
        temp_obj = bpy.data.objects.new("__mcp_tmp_obj__", temp_mesh)
        try:
            mod = temp_obj.modifiers.new("temp", mod_type)
            base_props = set(p.identifier for p in bpy.types.Modifier.bl_rna.properties)
            props_data = {}
            for prop in mod.bl_rna.properties:
                if prop.identifier in base_props or prop.is_readonly:
                    continue
                p_info = {
                    "type": prop.type,
                    "description": prop.description,
                }
                if prop.type == 'ENUM':
                    p_info["enum_items"] = [it.identifier for it in prop.enum_items]
                    p_info["default"] = getattr(prop, "default", None)
                elif prop.type == 'POINTER' and prop.fixed_type:
                    p_info["pointer_type"] = prop.fixed_type.identifier
                elif prop.type in ('INT', 'FLOAT'):
                    p_info["default"] = getattr(prop, "default", None)
                    p_info["min"] = getattr(prop, "hard_min", None)
                    p_info["max"] = getattr(prop, "hard_max", None)
                elif prop.type == 'BOOLEAN':
                    p_info["default"] = getattr(prop, "default", None)
                props_data[prop.identifier] = p_info

            return {
                "status": "ok",
                "modifier_type": mod_type,
                "name": valid_items[mod_type].name,
                "description": valid_items[mod_type].description,
                "properties_count": len(props_data),
                "properties": props_data
            }
        except Exception as ex:
            return {"status": "error", "message": f"Failed to query modifier type '{mod_type}': {ex}"}
        finally:
            bpy.data.objects.remove(temp_obj)
            bpy.data.meshes.remove(temp_mesh)

    # Actions below require object_name
    obj_name = args.get("object_name")
    if not obj_name:
        return {"status": "error", "message": "Argument 'object_name' is required for action '" + action + "'"}

    obj = bpy.data.objects.get(obj_name)
    if not obj:
        return {"status": "error", "message": f"Object '{obj_name}' not found"}

    # 3. Inspect: list all modifiers on the target object with active configuration
    if action == "inspect":
        base_props = set(p.identifier for p in bpy.types.Modifier.bl_rna.properties)
        mods_list = []
        for mod in obj.modifiers:
            props_dump = {}
            for prop in mod.bl_rna.properties:
                if prop.identifier in base_props or prop.is_readonly:
                    continue
                try:
                    val = getattr(mod, prop.identifier)
                    if prop.type == 'POINTER':
                        props_dump[prop.identifier] = val.name if val else None
                    elif isinstance(val, (set, frozenset)):
                        props_dump[prop.identifier] = list(val)
                    elif prop.type in ('INT', 'FLOAT', 'BOOLEAN', 'STRING', 'ENUM'):
                        props_dump[prop.identifier] = val
                    elif prop.is_array:
                        props_dump[prop.identifier] = list(val)
                except Exception:
                    pass
            mods_list.append({
                "name": mod.name,
                "type": mod.type,
                "show_viewport": mod.show_viewport,
                "show_render": mod.show_render,
                "properties": props_dump
            })
        return {
            "status": "ok",
            "object_name": obj.name,
            "modifiers_count": len(mods_list),
            "modifiers": mods_list
        }

    # Helper for setting RNA properties with smart pointer resolution and enum matching
    def set_smart_prop(mod, k, v):
        prop = mod.bl_rna.properties.get(k)
        if not prop:
            for p_name in mod.bl_rna.properties.keys():
                if p_name.lower() == k.lower():
                    prop = mod.bl_rna.properties[p_name]
                    k = p_name
                    break
        if not prop:
            return False, f"Property '{k}' not found on modifier '{mod.type}'"
        if prop.is_readonly:
            return False, f"Property '{k}' is read-only"

        try:
            if prop.type == 'POINTER':
                target_type = prop.fixed_type.identifier if prop.fixed_type else None
                target = None
                if isinstance(v, str):
                    if target_type == 'Object':
                        target = bpy.data.objects.get(v)
                    elif target_type == 'Collection':
                        target = bpy.data.collections.get(v)
                    elif target_type == 'NodeTree':
                        target = bpy.data.node_groups.get(v)
                    elif target_type == 'Material':
                        target = bpy.data.materials.get(v)
                    elif target_type == 'Texture':
                        target = bpy.data.textures.get(v)
                    elif target_type == 'Image':
                        target = bpy.data.images.get(v)
                elif v is None:
                    setattr(mod, k, None)
                    return True, f"Cleared {k}"

                if target is not None:
                    setattr(mod, k, target)
                    return True, f"Set {k} to {target_type} '{v}'"
                else:
                    return False, f"Could not find {target_type} '{v}' for property '{k}'"

            elif prop.type == 'ENUM':
                if isinstance(v, str):
                    v_upper = v.upper()
                    matched = None
                    for it in prop.enum_items:
                        if it.identifier == v_upper or it.identifier.lower() == v.lower():
                            matched = it.identifier
                            break
                    if matched:
                        setattr(mod, k, matched)
                        return True, f"Set {k}={matched}"
                    else:
                        valid_items = [it.identifier for it in prop.enum_items]
                        return False, f"Invalid enum '{v}' for '{k}'. Valid: {valid_items}"
                else:
                    setattr(mod, k, v)
                    return True, f"Set {k}={v}"

            elif prop.type == 'BOOLEAN':
                setattr(mod, k, bool(v))
                return True, f"Set {k}={bool(v)}"

            elif prop.type == 'INT':
                if prop.is_array:
                    setattr(mod, k, [int(x) for x in v])
                else:
                    setattr(mod, k, int(v))
                return True, f"Set {k}={v}"

            elif prop.type == 'FLOAT':
                if prop.is_array:
                    setattr(mod, k, [float(x) for x in v])
                else:
                    setattr(mod, k, float(v))
                return True, f"Set {k}={v}"

            else:
                setattr(mod, k, v)
                return True, f"Set {k}={v}"
        except Exception as ex:
            return False, f"Error setting {k}={v}: {ex}"

    mod_name = args.get("modifier_name")
    props = args.get("properties", {})

    bpy.ops.ed.undo_push(message=f"MCP Modifier {action.title()}")

    # 4. Add action
    if action == "add":
        if not mod_type:
            return {"status": "error", "message": "Argument 'modifier_type' is required for action 'add'"}

        actual_name = mod_name or mod_type.title()
        try:
            mod = obj.modifiers.new(name=actual_name, type=mod_type)
        except Exception as ex:
            return {"status": "error", "message": f"Failed to create modifier '{mod_type}': {ex}"}

        applied_props = {}
        warnings = []
        for k, v in props.items():
            ok, msg = set_smart_prop(mod, k, v)
            if ok:
                applied_props[k] = v
            else:
                warnings.append(msg)

        res = {
            "status": "ok",
            "message": f"Added modifier '{mod.name}' ({mod.type}) to '{obj.name}'",
            "modifier": {"name": mod.name, "type": mod.type},
            "applied_properties": applied_props
        }
        if warnings:
            res["warnings"] = warnings
        return res

    # 5. Configure action
    elif action == "configure":
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if not mod and mod_type:
            for m in obj.modifiers:
                if m.type == mod_type:
                    mod = m
                    break
        if not mod:
            return {"status": "error", "message": f"Modifier '{mod_name or mod_type}' not found on '{obj.name}'"}

        applied_props = {}
        warnings = []
        for k, v in props.items():
            ok, msg = set_smart_prop(mod, k, v)
            if ok:
                applied_props[k] = v
            else:
                warnings.append(msg)

        res = {
            "status": "ok",
            "message": f"Configured modifier '{mod.name}' on '{obj.name}'",
            "modifier": {"name": mod.name, "type": mod.type},
            "applied_properties": applied_props
        }
        if warnings:
            res["warnings"] = warnings
        return res

    # 6. Apply action
    elif action == "apply":
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if not mod and mod_type:
            for m in obj.modifiers:
                if m.type == mod_type:
                    mod = m
                    break
        if not mod:
            return {"status": "error", "message": f"Modifier '{mod_name or mod_type}' not found on '{obj.name}'"}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
            return {"status": "ok", "message": f"Applied modifier '{mod.name}' on '{obj.name}'"}
        except Exception as ex:
            return {"status": "error", "message": f"Failed to apply modifier: {ex}"}

    # 7. Remove action
    elif action == "remove":
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if not mod and mod_type:
            for m in obj.modifiers:
                if m.type == mod_type:
                    mod = m
                    break
        if not mod:
            return {"status": "error", "message": f"Modifier '{mod_name or mod_type}' not found on '{obj.name}'"}
        name_removed = mod.name
        obj.modifiers.remove(mod)
        return {"status": "ok", "message": f"Removed modifier '{name_removed}' from '{obj.name}'"}

    else:
        return {"status": "error", "message": f"Unknown action '{action}'. Allowed: add, configure, apply, remove, inspect, query_type, search"}
"#;

    match call_python_tool(py, code, "run_modifier", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Modifier operation failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during modifier operation: {}", e)),
    }
}
