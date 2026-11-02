# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Handler for ``blender_manage_hierarchy``.

Unified scene hierarchy and collection management tool for Blender:
- Object-to-object and object-to-bone parenting with inverse transform preservation.
- Clear parenting keeping world transforms.
- Creation, nesting, renaming and removal of collections.
- Linking, unlinking and moving objects between collections.
- Configuring collection viewport/render visibility, color tags and view-layer exclusions.
- Inspecting collection and parent trees.
"""

from __future__ import annotations

import bpy
import mathutils

from ..registry import register
from . import schemas


def _normalize_list(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    return [s] if s else []


def _find_layer_collection(layer_collection, name):
    if layer_collection.name == name:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, name)
        if found is not None:
            return found
    return None


def _get_parent_collections(col):
    parents = []
    if col.name in bpy.context.scene.collection.children:
        parents.append(bpy.context.scene.collection)
    for c in bpy.data.collections:
        if col.name in c.children:
            parents.append(c)
    return parents


def _dump_collection_tree(col, max_depth=5, current_depth=1):
    if current_depth > max_depth:
        return {"name": col.name, "truncated": True}

    lc = _find_layer_collection(bpy.context.view_layer.layer_collection, col.name)
    exclude = lc.exclude if lc else False

    return {
        "name": col.name,
        "color_tag": getattr(col, "color_tag", "NONE"),
        "hide_viewport": getattr(col, "hide_viewport", False),
        "hide_render": getattr(col, "hide_render", False),
        "exclude": exclude,
        "objects": [obj.name for obj in col.objects],
        "children": [
            _dump_collection_tree(child, max_depth, current_depth + 1)
            for child in col.children
        ],
    }


def _dump_object_parent_tree(obj, max_depth=5, current_depth=1):
    if current_depth > max_depth:
        return {"name": obj.name, "truncated": True}

    child_nodes = []
    for child in obj.children:
        child_nodes.append(_dump_object_parent_tree(child, max_depth, current_depth + 1))

    return {
        "name": obj.name,
        "type": obj.type,
        "parent_type": getattr(obj, "parent_type", "OBJECT") if obj.parent else None,
        "parent_bone": getattr(obj, "parent_bone", "") if obj.parent and obj.parent_type == "BONE" else None,
        "children": child_nodes,
    }


def _is_descendant(potential_child, ancestor):
    """Check if potential_child is an ancestor of ancestor (would create a cycle)."""
    curr = ancestor
    visited = set()
    while curr:
        if curr == potential_child:
            return True
        if curr in visited:
            break
        visited.add(curr)
        curr = curr.parent
    return False


def run_hierarchy(args):
    action = str(args.get("action", "inspect")).lower().strip()
    undo = bool(args.get("undo", True))

    # 1. Action: set_parent / parent
    if action in ("set_parent", "parent"):
        parent_name = args.get("parent")
        if not parent_name:
            return {"status": "error", "message": "Argument 'parent' is required for action 'set_parent'"}

        parent = bpy.data.objects.get(parent_name)
        if not parent:
            return {"status": "error", "message": f"Parent object '{parent_name}' not found"}

        child_names = _normalize_list(
            args.get("children") or args.get("child") or args.get("objects") or args.get("object")
        )
        if not child_names:
            return {"status": "error", "message": "Provide 'children' (or 'child') object name(s) to parent"}

        parent_type = str(args.get("parent_type", "OBJECT")).upper().strip()
        parent_bone = args.get("parent_bone")
        keep_transform = bool(args.get("keep_transform", True))

        if parent_type == "BONE":
            if parent.type != "ARMATURE":
                return {
                    "status": "error",
                    "message": f"Parent '{parent.name}' must be an ARMATURE when parent_type='BONE'",
                }
            if not parent_bone:
                return {
                    "status": "error",
                    "message": "Argument 'parent_bone' is required when parent_type='BONE'",
                }
            if parent.data and parent_bone not in parent.data.bones:
                available = [b.name for b in parent.data.bones][:15] if hasattr(parent.data, "bones") else []
                return {
                    "status": "error",
                    "message": f"Bone '{parent_bone}' not found on armature '{parent.name}'. Available: {available}",
                }

        child_objs = []
        for name in child_names:
            c = bpy.data.objects.get(name)
            if not c:
                return {"status": "error", "message": f"Child object '{name}' not found"}
            if c == parent:
                return {"status": "error", "message": f"Object '{name}' cannot be parented to itself"}
            if _is_descendant(c, parent):
                return {
                    "status": "error",
                    "message": f"Cannot parent '{c.name}' to '{parent.name}': would create a cyclic dependency",
                }
            child_objs.append(c)

        if undo:
            bpy.ops.ed.undo_push(message="MCP Set Parent")

        applied = []
        for child in child_objs:
            world_before = child.matrix_world.copy()
            child.parent = parent
            child.parent_type = parent_type
            if parent_type == "BONE" and parent_bone:
                child.parent_bone = parent_bone

            if keep_transform:
                if parent_type == "BONE" and parent_bone and parent.pose and parent_bone in parent.pose.bones:
                    bone_mat = parent.matrix_world @ parent.pose.bones[parent_bone].matrix
                    child.matrix_parent_inverse = bone_mat.inverted()
                else:
                    child.matrix_parent_inverse = parent.matrix_world.inverted()
                child.matrix_world = world_before
            else:
                child.matrix_parent_inverse = mathutils.Matrix.Identity(4)
            applied.append(child.name)

        bpy.context.view_layer.update()
        return {
            "status": "ok",
            "action": "set_parent",
            "parent": parent.name,
            "parent_type": parent_type,
            "parent_bone": parent_bone if parent_type == "BONE" else None,
            "keep_transform": keep_transform,
            "children": applied,
        }

    # 2. Action: clear_parent / unparent
    elif action in ("clear_parent", "unparent"):
        obj_names = _normalize_list(
            args.get("objects") or args.get("object") or args.get("children") or args.get("child")
        )
        if not obj_names:
            return {"status": "error", "message": "Provide 'objects' to unparent"}

        keep_transform = bool(args.get("keep_transform", True))
        cleared = []

        if undo:
            bpy.ops.ed.undo_push(message="MCP Clear Parent")

        for name in obj_names:
            obj = bpy.data.objects.get(name)
            if not obj:
                return {"status": "error", "message": f"Object '{name}' not found"}
            if obj.parent:
                if keep_transform:
                    world_mat = obj.matrix_world.copy()
                    obj.parent = None
                    obj.matrix_parent_inverse = mathutils.Matrix.Identity(4)
                    obj.matrix_world = world_mat
                else:
                    obj.parent = None
                    obj.matrix_parent_inverse = mathutils.Matrix.Identity(4)
                cleared.append(obj.name)

        bpy.context.view_layer.update()
        return {
            "status": "ok",
            "action": "clear_parent",
            "keep_transform": keep_transform,
            "objects": cleared,
        }

    # 3. Action: create_collection
    elif action == "create_collection":
        col_name = str(args.get("collection") or args.get("name") or "").strip()
        if not col_name:
            return {"status": "error", "message": "Argument 'collection' (or 'name') is required"}

        parent_col_name = args.get("parent_collection")
        color_tag = args.get("color_tag")

        if undo:
            bpy.ops.ed.undo_push(message="MCP Create Collection")

        created = False
        col = bpy.data.collections.get(col_name)
        if col is None:
            col = bpy.data.collections.new(col_name)
            created = True

        if parent_col_name:
            parent_col = bpy.data.collections.get(parent_col_name)
            if not parent_col and parent_col_name in ("Scene Collection", bpy.context.scene.collection.name):
                parent_col = bpy.context.scene.collection
            if not parent_col:
                return {"status": "error", "message": f"Parent collection '{parent_col_name}' not found"}
            if col.name not in parent_col.children:
                parent_col.children.link(col)
        else:
            if not _get_parent_collections(col):
                bpy.context.scene.collection.children.link(col)

        if color_tag:
            try:
                col.color_tag = str(color_tag).upper().strip()
            except Exception:
                pass

        return {
            "status": "ok",
            "action": "create_collection",
            "collection": col.name,
            "created": created,
            "color_tag": getattr(col, "color_tag", "NONE"),
            "parents": [p.name for p in _get_parent_collections(col)],
        }

    # 4. Action: move_to_collection
    elif action == "move_to_collection":
        col_name = str(args.get("collection") or args.get("name") or "").strip()
        if not col_name:
            return {"status": "error", "message": "Argument 'collection' is required"}

        obj_names = _normalize_list(args.get("objects") or args.get("object"))
        if not obj_names:
            return {"status": "error", "message": "Provide 'objects' to move to collection"}

        mode = str(args.get("mode", "move")).lower().strip()
        if mode not in ("move", "link"):
            mode = "move"

        if undo:
            bpy.ops.ed.undo_push(message="MCP Move to Collection")

        target_col = bpy.data.collections.get(col_name)
        if target_col is None:
            target_col = bpy.data.collections.new(col_name)
            bpy.context.scene.collection.children.link(target_col)

        moved = []
        for name in obj_names:
            obj = bpy.data.objects.get(name)
            if not obj:
                return {"status": "error", "message": f"Object '{name}' not found"}

            if obj.name not in target_col.objects:
                target_col.objects.link(obj)

            if mode == "move":
                if obj.name in bpy.context.scene.collection.objects and bpy.context.scene.collection != target_col:
                    bpy.context.scene.collection.objects.unlink(obj)
                for c in list(obj.users_collection):
                    if c != target_col:
                        c.objects.unlink(obj)

            moved.append(obj.name)

        return {
            "status": "ok",
            "action": "move_to_collection",
            "collection": target_col.name,
            "mode": mode,
            "objects": moved,
        }

    # 5. Action: unlink_from_collection / remove_from_collection
    elif action in ("unlink_from_collection", "remove_from_collection"):
        col_name = str(args.get("collection") or args.get("name") or "").strip()
        if not col_name:
            return {"status": "error", "message": "Argument 'collection' is required"}

        obj_names = _normalize_list(args.get("objects") or args.get("object"))
        if not obj_names:
            return {"status": "error", "message": "Provide 'objects' to unlink from collection"}

        target_col = bpy.data.collections.get(col_name)
        if target_col is None and col_name in ("Scene Collection", bpy.context.scene.collection.name):
            target_col = bpy.context.scene.collection
        if not target_col:
            return {"status": "error", "message": f"Collection '{col_name}' not found"}

        if undo:
            bpy.ops.ed.undo_push(message="MCP Unlink from Collection")

        unlinked = []
        for name in obj_names:
            obj = bpy.data.objects.get(name)
            if not obj:
                return {"status": "error", "message": f"Object '{name}' not found"}

            if obj.name in target_col.objects:
                target_col.objects.unlink(obj)
                unlinked.append(obj.name)

            # Safeguard: if object is no longer in any collection, place in scene.collection
            if not obj.users_collection and obj.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(obj)

        return {
            "status": "ok",
            "action": "unlink_from_collection",
            "collection": target_col.name,
            "objects": unlinked,
        }

    # 6. Action: remove_collection / delete_collection
    elif action in ("remove_collection", "delete_collection"):
        col_name = str(args.get("collection") or args.get("name") or "").strip()
        if not col_name:
            return {"status": "error", "message": "Argument 'collection' is required"}

        col = bpy.data.collections.get(col_name)
        if not col:
            return {"status": "error", "message": f"Collection '{col_name}' not found in bpy.data.collections"}

        keep_objects = bool(args.get("keep_objects", True))
        delete_hierarchy = bool(args.get("delete_hierarchy", False))

        if undo:
            bpy.ops.ed.undo_push(message="MCP Remove Collection")

        parents = _get_parent_collections(col)
        target_fallback = parents[0] if parents else bpy.context.scene.collection

        if keep_objects:
            for obj in list(col.objects):
                if len(obj.users_collection) <= 1:
                    if obj.name not in target_fallback.objects:
                        target_fallback.objects.link(obj)

        if delete_hierarchy:
            def _delete_rec(c):
                for child in list(c.children):
                    _delete_rec(child)
                bpy.data.collections.remove(c)
            _delete_rec(col)
        else:
            for child in list(col.children):
                if child.name not in target_fallback.children:
                    target_fallback.children.link(child)
            bpy.data.collections.remove(col)

        return {
            "status": "ok",
            "action": "remove_collection",
            "collection": col_name,
            "keep_objects": keep_objects,
            "delete_hierarchy": delete_hierarchy,
        }

    # 7. Action: configure_collection
    elif action == "configure_collection":
        col_name = str(args.get("collection") or args.get("name") or "").strip()
        if not col_name:
            return {"status": "error", "message": "Argument 'collection' is required"}

        col = bpy.data.collections.get(col_name)
        if not col:
            return {"status": "error", "message": f"Collection '{col_name}' not found"}

        if undo:
            bpy.ops.ed.undo_push(message="MCP Configure Collection")

        applied_changes = {}

        parent_col_name = args.get("parent_collection")
        if parent_col_name is not None:
            new_parent = bpy.data.collections.get(parent_col_name)
            if not new_parent and parent_col_name in ("Scene Collection", bpy.context.scene.collection.name):
                new_parent = bpy.context.scene.collection
            if not new_parent:
                return {"status": "error", "message": f"Parent collection '{parent_col_name}' not found"}

            old_parents = _get_parent_collections(col)
            for op in old_parents:
                if col.name in op.children:
                    op.children.unlink(col)
            if col.name not in new_parent.children:
                new_parent.children.link(col)
            applied_changes["parent_collection"] = new_parent.name

        color_tag = args.get("color_tag")
        if color_tag is not None:
            col.color_tag = str(color_tag).upper().strip()
            applied_changes["color_tag"] = col.color_tag

        if "hide_viewport" in args:
            col.hide_viewport = bool(args["hide_viewport"])
            applied_changes["hide_viewport"] = col.hide_viewport

        if "hide_render" in args:
            col.hide_render = bool(args["hide_render"])
            applied_changes["hide_render"] = col.hide_render

        if "exclude" in args:
            lc = _find_layer_collection(bpy.context.view_layer.layer_collection, col.name)
            if lc:
                lc.exclude = bool(args["exclude"])
                applied_changes["exclude"] = lc.exclude

        new_name = args.get("new_name")
        if new_name and str(new_name).strip() != col.name:
            old_name = col.name
            col.name = str(new_name).strip()
            applied_changes["renamed_from"] = old_name
            applied_changes["name"] = col.name

        return {
            "status": "ok",
            "action": "configure_collection",
            "collection": col.name,
            "changes": applied_changes,
        }

    # 8. Action: inspect
    elif action == "inspect":
        target = str(args.get("target", "all")).lower().strip()
        depth = int(args.get("depth", 5))
        res = {"status": "ok", "action": "inspect"}

        if target in ("all", "collections"):
            filter_col = args.get("collection")
            root_col = bpy.data.collections.get(filter_col) if filter_col else bpy.context.scene.collection
            if not root_col:
                return {"status": "error", "message": f"Collection '{filter_col}' not found"}
            res["collections"] = _dump_collection_tree(root_col, max_depth=depth)

        if target in ("all", "parents"):
            filter_obj = args.get("object")
            if filter_obj:
                obj = bpy.data.objects.get(filter_obj)
                if not obj:
                    return {"status": "error", "message": f"Object '{filter_obj}' not found"}
                chain = []
                curr = obj.parent
                while curr:
                    chain.append({"name": curr.name, "type": curr.type})
                    curr = curr.parent
                res["parent_chain"] = chain
                res["object_hierarchy"] = _dump_object_parent_tree(obj, max_depth=depth)
            else:
                root_objs = [o for o in bpy.context.scene.objects if o.parent is None]
                res["root_objects"] = [_dump_object_parent_tree(o, max_depth=depth) for o in root_objs]

        return res

    # 9. Action: delete_object / remove_object
    elif action in ("delete_object", "remove_object"):
        obj_names = _normalize_list(
            args.get("objects") or args.get("object") or args.get("children") or args.get("child")
        )
        if not obj_names:
            return {"status": "error", "message": "Provide 'objects' (or 'object') to delete"}

        delete_data = bool(args.get("delete_data", True))
        if undo:
            bpy.ops.ed.undo_push(message="MCP Delete Objects")

        deleted = []
        deleted_data = []
        for name in obj_names:
            obj = bpy.data.objects.get(name)
            if not obj:
                continue
            data_block = obj.data if delete_data else None
            obj_name = obj.name
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted.append(obj_name)
            if data_block and getattr(data_block, "users", 0) == 0:
                try:
                    for coll_name in ("meshes", "curves", "lights", "cameras", "armatures", "grease_pencils"):
                        coll = getattr(bpy.data, coll_name, None)
                        if coll and data_block.name in coll:
                            dname = data_block.name
                            coll.remove(data_block)
                            deleted_data.append(f"{coll_name}:{dname}")
                            break
                except Exception:
                    pass

        bpy.context.view_layer.update()
        return {
            "status": "ok",
            "action": "delete_object",
            "deleted_objects": deleted,
            "deleted_data": deleted_data,
        }

    else:
        return {
            "status": "error",
            "message": (
                f"Unknown action '{action}'. Valid actions: set_parent, clear_parent, "
                "create_collection, move_to_collection, unlink_from_collection, "
                "remove_collection, configure_collection, inspect, delete_object"
            ),
        }


# --- MCP registration -------------------------------------------------------
schemas.register_tool(register, "blender_manage_hierarchy", run_hierarchy)
