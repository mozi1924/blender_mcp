use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn manage_nodes(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy
import os

NODE_BASE_PROPS = {
    'rna_type', 'type', 'location', 'location_absolute', 'width', 'height', 'dimensions',
    'name', 'label', 'inputs', 'outputs', 'panel_states', 'internal_links', 'parent',
    'warning_propagation', 'use_custom_color', 'color', 'color_tag', 'select',
    'show_options', 'show_preview', 'hide', 'mute', 'show_texture',
    'bl_idname', 'bl_label', 'bl_description', 'bl_icon', 'bl_static_type',
    'bl_width_default', 'bl_width_min', 'bl_width_max', 'bl_height_default',
    'bl_height_min', 'bl_height_max'
}

_NODE_CATALOG_CACHE = None

def get_node_catalog():
    global _NODE_CATALOG_CACHE
    if _NODE_CATALOG_CACHE is not None:
        return _NODE_CATALOG_CACHE

    from bpy.app.translations import pgettext_iface, pgettext_tip
    catalog = []
    for name in dir(bpy.types):
        if name.endswith("Socket") or name in ("Node", "ShaderNode", "GeometryNode", "CompositorNode", "TextureNode", "FunctionNode"):
            continue
        rna = bpy.types.Node.bl_rna_get_subclass(name)
        if rna:
            affinity = "OTHER"
            if name.startswith("GeometryNode"):
                affinity = "GEOMETRY"
            elif name.startswith("ShaderNode"):
                affinity = "SHADER"
            elif name.startswith("CompositorNode"):
                affinity = "COMPOSITING"
            elif name.startswith("FunctionNode"):
                affinity = "FUNCTION"
            elif name.startswith("TextureNode"):
                affinity = "TEXTURE"

            name_en = rna.name
            try:
                name_i18n = pgettext_iface(name_en)
            except Exception:
                name_i18n = name_en

            desc_en = rna.description or ""
            try:
                desc_i18n = pgettext_tip(desc_en) if desc_en else ""
            except Exception:
                desc_i18n = desc_en

            catalog.append({
                "identifier": name,
                "name": name_en,
                "name_i18n": name_i18n,
                "description": desc_en,
                "description_i18n": desc_i18n,
                "affinity": affinity,
            })
    _NODE_CATALOG_CACHE = catalog
    return _NODE_CATALOG_CACHE

def tree_type_matches(affinity, tree_type):
    if not tree_type:
        return True
    tt = tree_type.upper()
    if tt in ("MATERIAL", "WORLD", "LINESTYLE", "LIGHT", "SHADER"):
        return affinity in ("SHADER", "FUNCTION")
    elif tt == "GEOMETRY":
        return affinity in ("GEOMETRY", "FUNCTION", "SHADER")
    elif tt == "COMPOSITING":
        return affinity in ("COMPOSITING", "FUNCTION", "SHADER")
    elif tt == "TEXTURE":
        return affinity in ("TEXTURE", "FUNCTION")
    return True

def search_nodes(query, tree_type=None, limit=15):
    catalog = get_node_catalog()
    q = (query or "").lower().strip()
    if not q:
        filtered = [item for item in catalog if tree_type_matches(item["affinity"], tree_type)]
        return filtered[:limit]

    matches = []
    for item in catalog:
        if not tree_type_matches(item["affinity"], tree_type):
            continue

        score = 0
        id_l = item["identifier"].lower()
        name_l = item["name"].lower()
        name_i18n_l = item["name_i18n"].lower()
        desc_l = item["description"].lower()
        desc_i18n_l = item["description_i18n"].lower()

        if q == id_l or q == name_l or q == name_i18n_l:
            score = 100
        elif q in name_l or q in name_i18n_l:
            score = 50
        elif q in id_l:
            score = 30
        elif q in desc_l or q in desc_i18n_l:
            score = 10

        if score > 0:
            matches.append((score, item))

    matches.sort(key=lambda x: -x[0])
    return [m[1] for m in matches[:limit]]

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

def find_socket(node, socket_name, is_output=False):
    sockets = node.outputs if is_output else node.inputs
    # 1. exact match
    for s in sockets:
        if s.name == socket_name or s.identifier == socket_name:
            return s
    # 2. normalized match (lowercase, spaces to underscores)
    norm = socket_name.lower().replace(' ', '_').replace('-', '_')
    for s in sockets:
        s_norm = s.name.lower().replace(' ', '_').replace('-', '_')
        i_norm = s.identifier.lower().replace(' ', '_').replace('-', '_')
        if s_norm == norm or i_norm == norm:
            return s
    # 3. single matching type fallback (e.g. "Shader" or "Geometry")
    type_matches = [s for s in sockets if getattr(s, 'type', '').lower() == norm]
    if len(type_matches) == 1:
        return type_matches[0]
    return None

def set_socket_value(sock, val):
    t = getattr(sock, 'type', '')
    if t in ('RGBA', 'COLOR'):
        if isinstance(val, str) and val.startswith('#'):
            sock.default_value = hex_to_rgba(val)
        elif isinstance(val, (list, tuple)):
            c = list(val)
            sock.default_value = c + ([1.0] if len(c) == 3 else [])
    elif t in ('VECTOR', 'ROTATION'):
        if isinstance(val, (list, tuple)):
            sock.default_value = list(val)[:3]
    elif t == 'INT_VECTOR':
        if isinstance(val, (list, tuple)):
            sock.default_value = [int(x) for x in list(val)[:3]]
    elif t in ('VALUE', 'FLOAT'):
        sock.default_value = float(val)
    elif t == 'INT':
        sock.default_value = int(val)
    elif t == 'BOOLEAN':
        sock.default_value = bool(val)
    elif t == 'STRING':
        sock.default_value = str(val)
    elif t == 'MENU':
        try:
            sock.default_value = val
        except Exception:
            pass
    elif t == 'MATERIAL':
        if isinstance(val, str):
            mat = bpy.data.materials.get(val)
            if not mat:
                mat = bpy.data.materials.new(val)
                mat.use_nodes = True
            sock.default_value = mat
    elif t == 'OBJECT':
        if isinstance(val, str):
            obj = bpy.data.objects.get(val)
            if obj:
                sock.default_value = obj
    elif t == 'COLLECTION':
        if isinstance(val, str):
            coll = bpy.data.collections.get(val)
            if coll:
                sock.default_value = coll
    elif t == 'IMAGE':
        if isinstance(val, str):
            img = bpy.data.images.get(val)
            if not img and os.path.exists(val):
                try:
                    img = bpy.data.images.load(val)
                except Exception:
                    pass
            if img:
                sock.default_value = img

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

def get_or_create_tree(tree_type, target_name, material_name=None, modifier_name=None):
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
            else:
                mat_name = material_name or f"{obj.name}_Material"
                mat = bpy.data.materials.new(name=mat_name)
                mat.use_nodes = True
                if not obj.data.materials:
                    obj.data.materials.append(mat)
                else:
                    obj.data.materials[0] = mat
        elif obj and obj.type == 'LIGHT':
            if hasattr(obj.data, "use_nodes"):
                obj.data.use_nodes = True
            return obj.data.node_tree, f"Light Shader Tree on '{obj.name}'"
        elif target_name and target_name in bpy.data.materials:
            mat = bpy.data.materials[target_name]
        elif material_name and material_name in bpy.data.materials:
            mat = bpy.data.materials[material_name]
        else:
            mat = bpy.data.materials.new(name=material_name or target_name or "NewMaterial")
            mat.use_nodes = True

        if not mat.use_nodes:
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
        else:
            light_data = bpy.data.lights.new(name=target_name or "Light", type='POINT')

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
            mod_name = modifier_name or "GeometryNodes"
            mod = obj.modifiers.new(name=mod_name, type='NODES')

        if not mod.node_group:
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
        if hasattr(scene, "use_nodes"):
            scene.use_nodes = True

        if not hasattr(scene, "compositing_node_group") or scene.compositing_node_group is None:
            group = bpy.data.node_groups.new("CompositingTree", type='CompositorNodeTree')
            scene.compositing_node_group = group

        group = scene.compositing_node_group
        if len(group.nodes) == 0:
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
                world = bpy.data.worlds.new("World")
                scene.world = world

        world.use_nodes = True
        return world.node_tree, f"World Shader Tree '{world.name}'"

    elif tree_type == "LINESTYLE":
        ls = None
        if target_name and target_name in bpy.data.linestyles:
            ls = bpy.data.linestyles[target_name]
        elif len(bpy.data.linestyles) > 0:
            ls = bpy.data.linestyles[0]
        else:
            ls = bpy.data.linestyles.new(name=target_name or "LineStyle")

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

        ttype = "GeometryNodeTree"
        if node_type.startswith("ShaderNode"):
            ttype = "ShaderNodeTree"
        elif node_type.startswith("CompositorNode"):
            ttype = "CompositorNodeTree"

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

            # Introspect operational RNA properties
            props = {}
            for p in node.bl_rna.properties:
                if p.identifier not in NODE_BASE_PROPS:
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
            rna = bpy.types.Node.bl_rna_get_subclass(node_type)
            from bpy.app.translations import pgettext_iface
            name_en = rna.name if rna else node.name
            try:
                name_i18n = pgettext_iface(name_en)
            except Exception:
                name_i18n = name_en

            return {
                "status": "ok",
                "node_type": node_type,
                "name": name_en,
                "name_i18n": name_i18n,
                "description": rna.description if rna else "",
                "inputs": inps,
                "outputs": outs,
                "properties": props
            }
        except Exception as ex:
            return {"status": "error", "message": f"Failed to query node type '{node_type}': {ex}"}
        finally:
            bpy.data.node_groups.remove(temp_tree)

    # All other actions require target tree
    tree, desc = get_or_create_tree(tree_type, target_name, mat_name, mod_name)
    if not tree:
        return {"status": "error", "message": desc}

    bpy.ops.ed.undo_push(message="MCP Manage Nodes")

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
        node_ids = args.get("node_ids", [])
        removed = 0
        for nid in node_ids:
            if nid in tree.nodes:
                tree.nodes.remove(tree.nodes[nid])
                removed += 1
        return {"status": "ok", "message": f"Removed {removed} node(s) from {desc}"}

    # Action 5: disconnect
    elif action == "disconnect":
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
"#;

    match call_python_tool(py, code, "run_manage_nodes", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Node operation failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during node management: {}", e)),
    }
}
