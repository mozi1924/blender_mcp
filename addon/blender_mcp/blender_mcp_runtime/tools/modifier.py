# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_manage_modifier``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy
from .. import catalogs, rna

def run_modifier(args):
    action = args.get("action", "add").lower()
    mod_type = args.get("modifier_type", "")
    if isinstance(mod_type, str):
        mod_type = mod_type.upper().strip()

    # 1. Search action: shared, cached live modifier catalog
    if action == "search":
        return catalogs.modifier_types(args.get("query") or "")

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

    # All property setting (pointer resolution, enums, arrays, coercion) is
    # delegated to the shared RNA kernel; no per-modifier hardcoding here.
    def apply_modifier_props(mod, mapping):
        result = rna.apply_properties(mod, mapping)
        warnings = list(result.get("warnings", [])) + list(result.get("errors", []))
        return result.get("applied", {}), warnings

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

        applied_props, warnings = apply_modifier_props(mod, props)

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

        applied_props, warnings = apply_modifier_props(mod, props)

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

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_manage_modifier", run_modifier)
