use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn manage_nodes(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
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
    if t == 'RGBA':
        if isinstance(val, str) and val.startswith('#'):
            sock.default_value = hex_to_rgba(val)
        elif isinstance(val, (list, tuple)):
            c = list(val)
            sock.default_value = c + ([1.0] if len(c) == 3 else [])
    elif t == 'VECTOR':
        if isinstance(val, (list, tuple)):
            sock.default_value = list(val)[:3]
    elif t in ('VALUE', 'FLOAT', 'INT'):
        sock.default_value = float(val) if t != 'INT' else int(val)
    elif t == 'BOOLEAN':
        sock.default_value = bool(val)
    elif t == 'STRING':
        sock.default_value = str(val)
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
    tree_type = tree_type.upper()

    if tree_type == "MATERIAL":
        # 1. target is object or material
        obj = bpy.data.objects.get(target_name) if target_name else None
        mat = None
        if obj and obj.type in ('MESH', 'CURVE', 'FONT', 'SURFACE'):
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

    elif tree_type == "GEOMETRY":
        obj = bpy.data.objects.get(target_name) if target_name else None
        if not obj:
            return None, f"Object '{target_name}' not found for GEOMETRY nodes"

        # find or create modifier
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
            # setup standard group input & output with Geometry interface
            if len(group.interface.items_tree) == 0:
                group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
                group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
            group.nodes.new('NodeGroupInput')
            group.nodes.new('NodeGroupOutput')

        return mod.node_group, f"Geometry Nodes '{mod.node_group.name}' on '{obj.name}'"

    elif tree_type == "COMPOSITING":
        scene = bpy.context.scene
        if not hasattr(scene, "compositing_node_group") or scene.compositing_node_group is None:
            group = bpy.data.node_groups.new("CompositingTree", type='CompositorNodeTree')
            scene.compositing_node_group = group
        return scene.compositing_node_group, f"Compositor Tree on scene '{scene.name}'"

    elif tree_type == "WORLD":
        scene = bpy.context.scene
        world = scene.world
        if not world:
            world = bpy.data.worlds.new("World")
            scene.world = world
        world.use_nodes = True
        return world.node_tree, f"World Shader Tree '{world.name}'"

    return None, f"Unknown tree_type '{tree_type}'"

def run_manage_nodes(args):
    action = args.get("action", "inspect").lower()
    tree_type = args.get("tree_type", "MATERIAL")
    target_name = args.get("target")
    mat_name = args.get("material_name")
    mod_name = args.get("modifier_name")

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
                    d_val = list(s.default_value) if hasattr(s.default_value, "__iter__") else s.default_value
                except Exception:
                    pass
                inps.append({"name": s.name, "identifier": s.identifier, "type": getattr(s, "type", "N/A"), "default_value": d_val})

            outs = [{"name": s.name, "identifier": s.identifier, "type": getattr(s, "type", "N/A")} for s in node.outputs]
            return {
                "status": "ok",
                "node_type": node_type,
                "inputs": inps,
                "outputs": outs
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
            # Keep output nodes or clear all
            to_remove = [n for n in tree.nodes if not ("Output" in n.bl_idname or "GroupOutput" in n.bl_idname)]
            for n in to_remove:
                tree.nodes.remove(n)

        auto_positions = compute_dag_layout(dag_nodes, dag_links)
        id_to_node = {}

        # 1. Create or match nodes
        for item in dag_nodes:
            node_id = item.get("id") or item.get("name")
            bl_type = item.get("type")
            node = None

            # Check if matching existing node by name or unique output type
            if node_id and node_id in tree.nodes:
                node = tree.nodes[node_id]
            elif bl_type:
                # If output node already exists, reuse it
                if "Output" in bl_type:
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

            # Set location
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

            from_node = id_to_node.get(from_nid) or tree.nodes.get(from_nid)
            to_node = id_to_node.get(to_nid) or tree.nodes.get(to_nid)

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
                    if (l.from_node.name == from_nid or l.from_node.name == from_nid) and \
                       (l.to_node.name == to_nid or l.to_node.name == to_nid):
                        tree.links.remove(l)
                        removed_links += 1
        return {"status": "ok", "message": f"Disconnected {removed_links} link(s)"}

    return {"status": "error", "message": f"Unknown action '{action}'. Allowed: inspect, query_type, apply_dag, remove_nodes, disconnect"}
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
