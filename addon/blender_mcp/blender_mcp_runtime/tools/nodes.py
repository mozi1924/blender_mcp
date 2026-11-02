# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_manage_nodes``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy
from .. import catalogs, rna
from ..rna import find_socket, set_socket_value

# Tool-level tree names -> Blender node tree types (API vocabulary, not RNA data).
_TREE_TYPES = {
    "MATERIAL": "ShaderNodeTree",
    "SHADER": "ShaderNodeTree",
    "WORLD": "ShaderNodeTree",
    "LINESTYLE": "ShaderNodeTree",
    "LIGHT": "ShaderNodeTree",
    "GEOMETRY": "GeometryNodeTree",
    "COMPOSITING": "CompositorNodeTree",
    "TEXTURE": "TextureNodeTree",
}

def tree_type_id(tree_type):
    if not tree_type:
        return None
    return _TREE_TYPES.get(str(tree_type).upper(), tree_type)

def search_nodes(query, tree_type=None, limit=15):
    # Authoritative, cached validity probing lives in the runtime catalog.
    result = catalogs.search_node_types(
        query=query,
        tree_type=tree_type_id(tree_type),
        limit=limit,
        include_tree_types=True,
    )
    return result["results"]

def resolve_node_ref(nid, tree, id_to_node):
    if not nid:
        return None
    if nid in id_to_node:
        return id_to_node[nid]
    if nid in tree.nodes:
        return tree.nodes[nid]

    norm = nid.lower().replace(" ", "").replace("_", "").replace("-", "")
    for n in tree.nodes:
        n_name = n.name.lower().replace(" ", "").replace("_", "").replace("-", "")
        n_id = n.bl_idname.lower().replace(" ", "").replace("_", "").replace("-", "")
        if n_name == norm or n_id == norm:
            return n

    # Semantic alias fallback for interface nodes in localized Blenders
    if norm in ("groupinput", "input"):
        for n in tree.nodes:
            if n.bl_idname == "NodeGroupInput":
                return n
    elif norm in ("groupoutput", "output"):
        for n in tree.nodes:
            if n.bl_idname == "NodeGroupOutput":
                return n
    elif norm in ("materialoutput", "surfaceoutput"):
        for n in tree.nodes:
            if "output" in n.bl_idname.lower():
                return n
    elif norm in ("composite", "compositeoutput"):
        for n in tree.nodes:
            if n.bl_idname == "CompositorNodeComposite":
                return n
    elif norm in ("rlayers", "renderlayers"):
        for n in tree.nodes:
            if n.bl_idname == "CompositorNodeRLayers":
                return n
    elif norm in ("principledbsdf", "principled", "bsdf"):
        for n in tree.nodes:
            if n.bl_idname in ("ShaderNodeBsdfPrincipled", "ShaderNodePrincipled"):
                return n
    return None

def compute_dag_layout(nodes, links):
    adj = {n.get("id", ""): [] for n in nodes}
    in_degree = {n.get("id", ""): 0 for n in nodes}
    for l in links:
        from_id = l.get("from", "").split(".")[0]
        to_id = l.get("to", "").split(".")[0]
        if from_id in adj and to_id in in_degree:
            adj[from_id].append(to_id)
            in_degree[to_id] += 1

    ranks = {n.get("id", ""): 0 for n in nodes}
    queue = [nid for nid, deg in in_degree.items() if deg == 0 and nid]
    while queue:
        curr = queue.pop(0)
        curr_rank = ranks[curr]
        for neighbor in adj[curr]:
            if ranks[neighbor] < curr_rank + 1:
                ranks[neighbor] = curr_rank + 1
            queue.append(neighbor)

    by_rank = {}
    for nid, r in ranks.items():
        if nid:
            by_rank.setdefault(r, []).append(nid)

    positions = {}
    for r, nids in by_rank.items():
        for idx, nid in enumerate(nids):
            positions[nid] = [r * 260.0 - 200.0, (idx - len(nids) / 2.0 + 0.5) * -180.0]
    return positions

def get_or_create_tree(tree_type, target_name, material_name=None, modifier_name=None, create=True):
    tree_type = tree_type.upper() if tree_type else "MATERIAL"

    # Global NodeGroup direct lookup
    if tree_type in ("NODEGROUP", "GROUP") or (target_name and target_name in bpy.data.node_groups):
        grp = bpy.data.node_groups.get(target_name)
        if grp:
            return grp, f"NodeGroup '{grp.name}' ({grp.bl_idname})"
        if tree_type in ("NODEGROUP", "GROUP"):
            return None, f"NodeGroup '{target_name}' not found"

    if tree_type == "MATERIAL":
        obj = bpy.data.objects.get(target_name) if target_name else None
        mat = None
        if obj and obj.type in ('MESH', 'CURVE', 'FONT', 'SURFACE', 'VOLUME'):
            if material_name and material_name in bpy.data.materials:
                mat = bpy.data.materials[material_name]
            elif obj.data.materials and obj.data.materials[0]:
                mat = obj.data.materials[0]
            elif not create:
                return None, f"Object '{obj.name}' has no material (inspect is read-only; pass ensure=true to create one)"
            else:
                mat_name = material_name or f"{obj.name}_Material"
                mat = bpy.data.materials.new(name=mat_name)
                mat.use_nodes = True
                if not obj.data.materials:
                    obj.data.materials.append(mat)
                else:
                    obj.data.materials[0] = mat
        elif obj and obj.type == 'LIGHT':
            if getattr(obj.data, "node_tree", None) is None:
                if not create:
                    return None, f"Light '{obj.name}' has no node tree (pass ensure=true to create one)"
                if hasattr(obj.data, "use_nodes"):
                    obj.data.use_nodes = True
            return obj.data.node_tree, f"Light Shader Tree on '{obj.name}'"
        elif target_name and target_name in bpy.data.materials:
            mat = bpy.data.materials[target_name]
        elif material_name and material_name in bpy.data.materials:
            mat = bpy.data.materials[material_name]
        elif not create:
            return None, (
                f"Material '{material_name or target_name or ''}' not found "
                "(inspect is read-only; pass ensure=true to create one)"
            )
        else:
            mat = bpy.data.materials.new(name=material_name or target_name or "NewMaterial")
            mat.use_nodes = True

        if getattr(mat, "node_tree", None) is None:
            if not create:
                return None, f"Material '{mat.name}' has no node tree (pass ensure=true to create one)"
            mat.use_nodes = True
        return mat.node_tree, f"Material '{mat.name}'"

    elif tree_type in ("LIGHT", "LIGHT_SHADER"):
        obj = bpy.data.objects.get(target_name) if target_name else None
        light_data = None
        if obj and obj.type == 'LIGHT':
            light_data = obj.data
        elif target_name and target_name in bpy.data.lights:
            light_data = bpy.data.lights[target_name]
        elif not obj and len(bpy.data.lights) > 0:
            light_data = bpy.data.lights[0]
        elif not create:
            return None, f"Light '{target_name or ''}' not found (pass ensure=true to create one)"
        else:
            light_data = bpy.data.lights.new(name=target_name or "Light", type='POINT')

        if getattr(light_data, "node_tree", None) is None:
            if not create:
                return None, f"Light '{light_data.name}' has no node tree (pass ensure=true to create one)"
            if hasattr(light_data, "use_nodes"):
                light_data.use_nodes = True
        return light_data.node_tree, f"Light '{light_data.name}' Shader Tree"

    elif tree_type == "GEOMETRY":
        if target_name and target_name in bpy.data.node_groups:
            return bpy.data.node_groups[target_name], f"Geometry NodeGroup '{target_name}'"

        obj = bpy.data.objects.get(target_name) if target_name else None
        if not obj:
            return None, f"Object '{target_name}' not found for GEOMETRY nodes"

        mod = None
        if modifier_name:
            mod = obj.modifiers.get(modifier_name)
        else:
            for m in obj.modifiers:
                if m.type == 'NODES':
                    mod = m
                    break

        if not mod:
            if not create:
                return None, (
                    f"Object '{obj.name}' has no Geometry Nodes modifier "
                    "(inspect is read-only; pass ensure=true to create one)"
                )
            mod_name = modifier_name or "GeometryNodes"
            mod = obj.modifiers.new(name=mod_name, type='NODES')

        if not mod.node_group:
            if not create:
                return None, (
                    f"Geometry Nodes modifier '{mod.name}' has no node group "
                    "(pass ensure=true to create one)"
                )
            group_name = f"{obj.name}_GeoTree"
            group = bpy.data.node_groups.new(name=group_name, type='GeometryNodeTree')
            mod.node_group = group
            if len(group.interface.items_tree) == 0:
                group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
                group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
            group.nodes.new('NodeGroupInput')
            group.nodes.new('NodeGroupOutput')

        return mod.node_group, f"Geometry Nodes '{mod.node_group.name}' on '{obj.name}'"

    elif tree_type == "COMPOSITING":
        if target_name and target_name in bpy.data.node_groups:
            return bpy.data.node_groups[target_name], f"Compositor NodeGroup '{target_name}'"

        scene = bpy.context.scene
        if create and hasattr(scene, "use_nodes"):
            scene.use_nodes = True

        if not hasattr(scene, "compositing_node_group") or scene.compositing_node_group is None:
            if not create:
                return None, "Scene has no compositing node group (pass ensure=true to create one)"
            group = bpy.data.node_groups.new("CompositingTree", type='CompositorNodeTree')
            scene.compositing_node_group = group

        group = scene.compositing_node_group
        if create and len(group.nodes) == 0:
            if len(group.interface.items_tree) == 0:
                group.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
            rl = group.nodes.new("CompositorNodeRLayers")
            rl.location = (-200, 0)
            comp = group.nodes.new("NodeGroupOutput")
            comp.location = (200, 0)
            try:
                valid_inps = [s for s in comp.inputs if getattr(s, "identifier", "") != "__extend__"]
                if valid_inps and "Image" in rl.outputs:
                    group.links.new(rl.outputs["Image"], valid_inps[0])
            except Exception:
                pass

        return group, f"Compositor Tree on scene '{scene.name}'"

    elif tree_type == "WORLD":
        world = None
        if target_name and target_name in bpy.data.worlds:
            world = bpy.data.worlds[target_name]
        else:
            scene = bpy.context.scene
            world = scene.world
            if not world:
                if not create:
                    return None, "Scene has no world (pass ensure=true to create one)"
                world = bpy.data.worlds.new("World")
                scene.world = world

        if getattr(world, "node_tree", None) is None:
            if not create:
                return None, f"World '{world.name}' has no node tree (pass ensure=true to create one)"
            world.use_nodes = True
        return world.node_tree, f"World Shader Tree '{world.name}'"

    elif tree_type == "LINESTYLE":
        ls = None
        if target_name and target_name in bpy.data.linestyles:
            ls = bpy.data.linestyles[target_name]
        elif len(bpy.data.linestyles) > 0:
            ls = bpy.data.linestyles[0]
        else:
            if not create:
                return None, f"LineStyle '{target_name or ''}' not found (pass ensure=true to create one)"
            ls = bpy.data.linestyles.new(name=target_name or "LineStyle")

        if getattr(ls, "node_tree", None) is None:
            if not create:
                return None, f"LineStyle '{ls.name}' has no node tree (pass ensure=true to create one)"
            ls.use_nodes = True
        return ls.node_tree, f"LineStyle Shader Tree '{ls.name}'"

    return None, f"Unknown tree_type '{tree_type}'. Allowed: MATERIAL, GEOMETRY, COMPOSITING, WORLD, LINESTYLE, LIGHT, NODEGROUP"

def run_manage_nodes(args):
    action = args.get("action", "inspect").lower()
    tree_type = args.get("tree_type", "MATERIAL")
    target_name = args.get("target")
    mat_name = args.get("material_name")
    mod_name = args.get("modifier_name")

    # Action 0: search (instant catalog lookup)
    if action in ("search", "find"):
        query = args.get("query", "")
        limit = int(args.get("limit", 15))
        results = search_nodes(query, tree_type, limit)
        return {
            "status": "ok",
            "query": query,
            "tree_type_filter": tree_type,
            "count": len(results),
            "results": results
        }

    # Action 1: query_type (doesn't require existing tree)
    if action == "query_type":
        node_type = args.get("node_type")
        if not node_type:
            return {"status": "error", "message": "Argument 'node_type' is required for action 'query_type'"}

        valid_trees = catalogs.node_tree_types(node_type)
        if not valid_trees:
            suggestions = [item["identifier"] for item in catalogs.node_catalog()]
            return {
                "status": "error",
                "message": f"Unknown node type '{node_type}'. Did you mean: {rna.suggest(node_type, suggestions)}"
            }
        ttype = valid_trees[0]

        temp_tree = bpy.data.node_groups.new("__temp_mcp_query__", type=ttype)
        try:
            node = temp_tree.nodes.new(node_type)
            inps = []
            for s in node.inputs:
                d_val = None
                try:
                    d_val = list(s.default_value) if hasattr(s.default_value, "__iter__") and not isinstance(s.default_value, (str, dict)) else s.default_value
                except Exception:
                    pass
                inps.append({"name": s.name, "identifier": s.identifier, "type": getattr(s, "type", "N/A"), "default_value": d_val})

            outs = [{"name": s.name, "identifier": s.identifier, "type": getattr(s, "type", "N/A")} for s in node.outputs]

            # Introspect operational RNA properties (base props derived from RNA)
            base_props = {p.identifier for p in bpy.types.Node.bl_rna.properties}
            props = {}
            for p in node.bl_rna.properties:
                if p.identifier not in base_props:
                    val = getattr(node, p.identifier, None)
                    if hasattr(val, "__iter__") and not isinstance(val, (str, dict)):
                        val = list(val)
                    prop_info = {
                        "type": p.type,
                        "description": p.description or "",
                        "value": val
                    }
                    if p.type == "ENUM":
                        prop_info["enum_items"] = [item.identifier for item in p.enum_items]
                    props[p.identifier] = prop_info

            # Meta info
            node_rna = bpy.types.Node.bl_rna_get_subclass(node_type)
            from bpy.app.translations import pgettext_iface
            name_en = node_rna.name if node_rna else node.name
            try:
                name_i18n = pgettext_iface(name_en)
            except Exception:
                name_i18n = name_en

            return {
                "status": "ok",
                "node_type": node_type,
                "name": name_en,
                "name_i18n": name_i18n,
                "description": node_rna.description if node_rna else "",
                "tree_type": ttype,
                "valid_tree_types": valid_trees,
                "inputs": inps,
                "outputs": outs,
                "properties": props
            }
        except Exception as ex:
            return {"status": "error", "message": f"Failed to query node type '{node_type}': {ex}"}
        finally:
            bpy.data.node_groups.remove(temp_tree)

    # All other actions require target tree
    is_write = action in ("apply_dag", "build_graph", "remove_nodes", "disconnect")
    ensure = bool(args.get("ensure", False))
    tree, desc = get_or_create_tree(
        tree_type, target_name, mat_name, mod_name, create=is_write or ensure
    )
    if not tree:
        if action == "inspect":
            return {
                "status": "ok",
                "tree_type": tree_type.upper(),
                "target": desc,
                "nodes_count": 0,
                "links_count": 0,
                "nodes": [],
                "links": [],
                "note": desc,
            }
        return {"status": "error", "message": desc}

    # Action 2: inspect
    if action == "inspect":
        nodes_info = []
        for n in tree.nodes:
            inps = []
            for s in n.inputs:
                inps.append({
                    "name": s.name,
                    "identifier": s.identifier,
                    "type": getattr(s, "type", "N/A"),
                    "is_linked": s.is_linked
                })
            outs = []
            for s in n.outputs:
                outs.append({
                    "name": s.name,
                    "identifier": s.identifier,
                    "type": getattr(s, "type", "N/A"),
                    "is_linked": s.is_linked
                })
            nodes_info.append({
                "id": n.name,
                "type": n.bl_idname,
                "label": n.label,
                "location": [round(n.location.x, 2), round(n.location.y, 2)],
                "inputs": inps,
                "outputs": outs
            })

        links_info = []
        for l in tree.links:
            links_info.append({
                "from_node": l.from_node.name,
                "from_socket": l.from_socket.name,
                "to_node": l.to_node.name,
                "to_socket": l.to_socket.name
            })

        return {
            "status": "ok",
            "tree_type": tree_type.upper(),
            "target": desc,
            "nodes_count": len(nodes_info),
            "links_count": len(links_info),
            "nodes": nodes_info,
            "links": links_info
        }

    # Action 3: apply_dag
    elif action in ("apply_dag", "build_graph"):
        bpy.ops.ed.undo_push(message="MCP Manage Nodes")
        dag_nodes = args.get("nodes", [])
        dag_links = args.get("links", [])
        clear_existing = args.get("clear", False)

        if clear_existing:
            to_remove = [n for n in tree.nodes if not ("Output" in n.bl_idname or "GroupOutput" in n.bl_idname or "Composite" in n.bl_idname)]
            for n in to_remove:
                tree.nodes.remove(n)

        auto_positions = compute_dag_layout(dag_nodes, dag_links)
        id_to_node = {}

        # 1. Create or match nodes
        for item in dag_nodes:
            node_id = item.get("id") or item.get("name")
            bl_type = item.get("type")
            node = None

            if node_id and node_id in tree.nodes:
                node = tree.nodes[node_id]
            elif bl_type:
                if "Output" in bl_type or bl_type in ("NodeGroupInput", "NodeGroupOutput", "ShaderNodeOutputMaterial", "CompositorNodeComposite", "ShaderNodeOutputLineStyle"):
                    for n in tree.nodes:
                        if n.bl_idname == bl_type:
                            node = n
                            break
                if not node:
                    node = tree.nodes.new(bl_type)

            if not node:
                continue

            if node_id:
                node.name = node_id
                id_to_node[node_id] = node

            pos = item.get("location") or auto_positions.get(node_id)
            if pos and len(pos) >= 2:
                node.location = (float(pos[0]), float(pos[1]))

            # Set properties (node attributes)
            props = item.get("properties", {})
            for pk, pv in props.items():
                if hasattr(node, pk):
                    try:
                        setattr(node, pk, pv)
                    except Exception as ex:
                        print(f"Warning: could not set node prop {pk}: {ex}")

            # Set input socket default values
            inputs_data = item.get("inputs", {})
            for sk, sv in inputs_data.items():
                sock = find_socket(node, sk, is_output=False)
                if sock:
                    try:
                        set_socket_value(sock, sv)
                    except Exception as ex:
                        print(f"Warning: could not set socket value {sk}: {ex}")

        # 2. Establish connections
        created_links = 0
        for link_item in dag_links:
            from_str = link_item.get("from", "")
            to_str = link_item.get("to", "")

            if "." not in from_str or "." not in to_str:
                continue

            from_nid, from_sname = from_str.split(".", 1)
            to_nid, to_sname = to_str.split(".", 1)

            from_node = resolve_node_ref(from_nid, tree, id_to_node)
            to_node = resolve_node_ref(to_nid, tree, id_to_node)

            if not from_node or not to_node:
                continue

            from_sock = find_socket(from_node, from_sname, is_output=True)
            to_sock = find_socket(to_node, to_sname, is_output=False)

            if from_sock and to_sock:
                tree.links.new(from_sock, to_sock)
                created_links += 1

        return {
            "status": "ok",
            "message": f"Successfully applied DAG to {desc}",
            "created_nodes": len(id_to_node),
            "created_links": created_links,
            "total_nodes": len(tree.nodes),
            "total_links": len(tree.links)
        }

    # Action 4: remove_nodes
    elif action == "remove_nodes":
        bpy.ops.ed.undo_push(message="MCP Remove Nodes")
        node_ids = args.get("node_ids", [])
        removed = 0
        for nid in node_ids:
            if nid in tree.nodes:
                tree.nodes.remove(tree.nodes[nid])
                removed += 1
        return {"status": "ok", "message": f"Removed {removed} node(s) from {desc}"}

    # Action 5: disconnect
    elif action == "disconnect":
        bpy.ops.ed.undo_push(message="MCP Disconnect Nodes")
        links_data = args.get("links", [])
        removed_links = 0
        for item in links_data:
            from_str = item.get("from", "")
            to_str = item.get("to", "")
            if "." in from_str and "." in to_str:
                from_nid, from_sname = from_str.split(".", 1)
                to_nid, to_sname = to_str.split(".", 1)
                for l in list(tree.links):
                    if l.from_node.name == from_nid and l.to_node.name == to_nid:
                        tree.links.remove(l)
                        removed_links += 1
        return {"status": "ok", "message": f"Disconnected {removed_links} link(s)"}

    return {"status": "error", "message": f"Unknown action '{action}'. Allowed: search, inspect, query_type, apply_dag, remove_nodes, disconnect"}

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_manage_nodes", run_manage_nodes)
