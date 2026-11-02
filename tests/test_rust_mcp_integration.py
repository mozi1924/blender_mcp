# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Automated end-to-end integration test for Blender MCP (Rust).
Exercises the HTTP server, bridge, and all semantic tools.
"""

import sys
import time
import json
import urllib.request
import threading
import bpy

# Add addon directory to sys.path
sys.path.insert(0, 'addon/blender_mcp')
import blender_mcp_core

HOST = "127.0.0.1"
PORT = 8799
ENDPOINT = f"http://{HOST}:{PORT}/mcp"

SESSION_ID = None
AUTH_TOKEN = None


def rpc_call(method, params=None, req_id=1):
    global SESSION_ID
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method
    }
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if SESSION_ID:
        headers["Mcp-Session-Id"] = SESSION_ID
    if AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
    req = urllib.request.Request(ENDPOINT, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        session_id = resp.headers.get("Mcp-Session-Id")
        if session_id:
            SESSION_ID = session_id
        return json.loads(resp.read().decode("utf-8"))

def tool_call(name, arguments, req_id=1):
    return rpc_call("tools/call", {"name": name, "arguments": arguments}, req_id)

def poll_ticks_until(predicate, timeout=5.0):
    start = time.time()
    while time.time() - start < timeout:
        blender_mcp_core.poll_tick(16)
        if predicate():
            return True
        time.sleep(0.01)
    return False

def run_tests():
    print("=" * 60)
    print("Starting Blender MCP (Rust) Automated Integration Test Suite")
    print("=" * 60)

    global SESSION_ID
    SESSION_ID = None

    # 1. Start Server
    print("==> Starting server...")
    blender_mcp_core.start_server(HOST, PORT)
    time.sleep(0.1)
    assert blender_mcp_core.is_running(), "Server must be running!"
    print("   [OK] Server running on", ENDPOINT)

    # Helper to run client RPC call in background thread while main thread polls ticks
    def run_rpc_with_main_loop(call_fn):
        result_holder = []
        def worker():
            try:
                res = call_fn()
                result_holder.append(res)
            except Exception as e:
                result_holder.append({"error": str(e)})

        t = threading.Thread(target=worker)
        t.start()

        # Pump main thread ticks until response arrives
        start_t = time.time()
        while t.is_alive() and time.time() - start_t < 15.0:
            blender_mcp_core.poll_tick(16)
            time.sleep(0.01)
        t.join(timeout=1.0)
        assert len(result_holder) > 0, "Request timed out!"
        return result_holder[0]

    # Test 1: initialize
    print("==> Test 1: initialize")
    init_res = run_rpc_with_main_loop(lambda: rpc_call("initialize", {"protocolVersion": "2024-11-05"}))
    assert "result" in init_res, f"Init failed: {init_res}"
    assert init_res["result"]["serverInfo"]["name"] == "blender-mcp-rust"
    print("   [OK] initialize returned server info successfully")

    # Test 2: tools/list
    print("==> Test 2: tools/list")
    list_res = run_rpc_with_main_loop(lambda: rpc_call("tools/list"))
    tools = list_res["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    print(f"   [OK] Found {len(tools)} tools: {', '.join(tool_names)}")
    expected_tools = [
        "blender_describe", "blender_inspect", "blender_run_operator",
        "blender_set", "blender_manage_modifier", "blender_manage_nodes",
        "blender_capture", "blender_execute_script",
    ]
    for exp in expected_tools:
        assert exp in tool_names, f"Expected tool {exp} missing!"

    # Test 3: blender_inspect (scene, datablocks, file)
    print("==> Test 3: blender_inspect")
    insp_scene = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {"target": "scene"}))
    assert not insp_scene["result"]["isError"], f"Inspect scene failed: {insp_scene}"
    insp_data = json.loads(insp_scene["result"]["content"][0]["text"])
    assert insp_data["status"] == "ok"
    assert "hierarchy" in insp_data
    assert "active_camera" in insp_data
    assert "fps" in insp_data and insp_data["fps"] > 0
    assert "units" in insp_data and "system" in insp_data["units"]
    assert "view_transform" in insp_data
    assert "resolution" in insp_data
    print(f"   [OK] blender_inspect (scene): FPS={insp_data['fps']}, ViewTransform={insp_data['view_transform']}, Camera={insp_data['active_camera']}")

    insp_blocks = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {"target": "datablocks"}))
    assert not insp_blocks["result"]["isError"]
    blocks_data = json.loads(insp_blocks["result"]["content"][0]["text"])
    assert "meshes" in blocks_data
    assert "curves" in blocks_data
    assert "grease_pencils" in blocks_data
    assert "armatures" in blocks_data
    print("   [OK] blender_inspect (datablocks): verified meshes, curves, grease_pencils, armatures counts")

    insp_file = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {"target": "file"}))
    assert not insp_file["result"]["isError"]
    file_data = json.loads(insp_file["result"]["content"][0]["text"])
    assert "version_string" in file_data
    assert "build_hash" in file_data
    print(f"   [OK] blender_inspect (file): version={file_data['version_string']}, hash={file_data['build_hash'][:10]}")

    # Test 4: blender_run_operator primitive creation
    print("==> Test 4: blender_run_operator (primitive_type)")
    create_res = run_rpc_with_main_loop(lambda: tool_call("blender_run_operator", {
        "primitive_type": "cube",
        "name": "RustCube",
        "location": [2.0, 3.0, 4.0],
        "scale": [1.5, 1.5, 1.5]
    }))
    assert not create_res["result"]["isError"], f"Create primitive failed: {create_res}"
    cube_obj = bpy.data.objects.get("RustCube")
    assert cube_obj is not None, "RustCube should exist in bpy.data.objects!"
    assert abs(cube_obj.scale[0] - 1.5) < 1e-4
    print("   [OK] Created RustCube at", list(cube_obj.location), "scale", list(cube_obj.scale))

    # Test 5: blender_set transforms + origin + transform_apply
    print("==> Test 5: blender_set transforms")
    set_loc = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "object:RustCube",
        "path": "location",
        "value": [5.0, 5.0, 5.0]
    }))
    assert not set_loc["result"]["isError"], f"Set location failed: {set_loc}"
    set_rot = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "object:RustCube",
        "path": "rotation",
        "value": [45.0, 0.0, 0.0]
    }))
    assert not set_rot["result"]["isError"], f"Set rotation failed: {set_rot}"
    set_origin = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "object:RustCube",
        "origin_to": "BOTTOM"
    }))
    assert not set_origin["result"]["isError"], f"Set origin failed: {set_origin}"
    apply_scale = run_rpc_with_main_loop(lambda: tool_call("blender_run_operator", {
        "operator": "object.transform_apply",
        "parameters": {"scale": True},
        "active": "RustCube"
    }))
    assert not apply_scale["result"]["isError"], f"Apply scale failed: {apply_scale}"
    assert abs(cube_obj.location[0] - 5.0) < 0.001
    print("   [OK] Set location/rotation, origin_to BOTTOM, applied scale")

    # Test 5b: rotation convenience adapts to QUATERNION rotation_mode
    cube_obj.rotation_mode = 'QUATERNION'
    trans_quat_res = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "object:RustCube",
        "path": "rotation",
        "value": [0.0, 90.0, 0.0]
    }))
    assert not trans_quat_res["result"]["isError"], f"Quaternion transform failed: {trans_quat_res}"
    insp_quat = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {
        "target": "object",
        "name": "RustCube"
    }))
    t_data = json.loads(insp_quat["result"]["content"][0]["text"])
    assert t_data["rotation_mode"] == "QUATERNION"
    assert abs(t_data["rotation_euler_deg"][1] - 90.0) < 1.0
    print("   [OK] Successfully adapted to QUATERNION rotation_mode on RustCube")

    # Test 6: blender_manage_modifier (catalog search, query_type, add with MANIFOLD solver)
    print("==> Test 6: blender_manage_modifier")
    # 6a. Search catalog
    mod_search = run_rpc_with_main_loop(lambda: tool_call("blender_manage_modifier", {
        "action": "search",
        "query": "boolean"
    }))
    assert not mod_search["result"]["isError"]
    s_data = json.loads(mod_search["result"]["content"][0]["text"])
    assert s_data["status"] == "ok" and s_data["count"] > 0
    assert any(m["identifier"] == "BOOLEAN" for m in s_data["modifiers"])
    print(f"   [OK] Catalog search found {s_data['count']} modifiers matching 'boolean'")

    # 6b. Query type for BOOLEAN and NODES (RNA introspection)
    mod_query = run_rpc_with_main_loop(lambda: tool_call("blender_manage_modifier", {
        "action": "query_type",
        "modifier_type": "BOOLEAN"
    }))
    assert not mod_query["result"]["isError"]
    q_data = json.loads(mod_query["result"]["content"][0]["text"])
    assert q_data["status"] == "ok"
    assert "solver" in q_data["properties"]
    assert "MANIFOLD" in q_data["properties"]["solver"]["enum_items"]
    print("   [OK] Queried BOOLEAN RNA properties: solver options include", q_data["properties"]["solver"]["enum_items"])

    # 6c. Add modifier with Blender 5.2 MANIFOLD solver
    mod_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_modifier", {
        "object_name": "RustCube",
        "action": "add",
        "modifier_type": "BOOLEAN",
        "modifier_name": "FastBoolean",
        "properties": {"solver": "MANIFOLD", "operation": "DIFFERENCE"}
    }))
    assert not mod_res["result"]["isError"], f"Modifier add failed: {mod_res}"
    mod = cube_obj.modifiers.get("FastBoolean")
    assert mod is not None and mod.solver == "MANIFOLD"
    print("   [OK] Added FastBoolean modifier with Blender 5.2 MANIFOLD solver to RustCube")

    # 6d. Inspect modifiers on object
    mod_insp = run_rpc_with_main_loop(lambda: tool_call("blender_manage_modifier", {
        "object_name": "RustCube",
        "action": "inspect"
    }))
    assert not mod_insp["result"]["isError"]
    insp_mods = json.loads(mod_insp["result"]["content"][0]["text"])
    assert insp_mods["status"] == "ok" and insp_mods["modifiers_count"] >= 1
    assert any(m["name"] == "FastBoolean" for m in insp_mods["modifiers"])
    print(f"   [OK] Inspected RustCube modifier stack: {insp_mods['modifiers_count']} active modifiers")

    # Test 7: blender_set material creation/assignment + Principled sockets
    print("==> Test 7: blender_set materials (OpenPBR + multi-slot)")
    create_mat = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "material:MetallicBlue",
        "create": True,
        "properties": {"use_nodes": True}
    }))
    assert not create_mat["result"]["isError"], f"Material create failed: {create_mat}"
    mat = bpy.data.materials["MetallicBlue"]
    bsdf = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")

    assign_mat = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "object:RustCube",
        "path": "data.materials",
        "value": "MetallicBlue",
        "mode": "append"
    }))
    assert not assign_mat["result"]["isError"], f"Material assign failed: {assign_mat}"

    for socket_name, socket_value in [
        ("Base Color", "#0088FF"),
        ("Metallic", 0.9),
        ("Roughness", 0.1),
        ("IOR", 1.45),
        ("Coat Weight", 0.8),
        ("Coat Roughness", 0.05),
        ("Thin Film Thickness", 500.0),
    ]:
        res = run_rpc_with_main_loop(lambda n=socket_name, v=socket_value: tool_call("blender_set", {
            "target": "material:MetallicBlue",
            "path": f"node_tree.nodes[{bsdf.name}].inputs[{n}].default_value",
            "value": v
        }))
        assert not res["result"]["isError"], f"Set socket {socket_name} failed: {res}"
    print("   [OK] Created & assigned MetallicBlue with OpenPBR v2 sockets")

    # 7b. Add a second material slot
    create_glass = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "material:ClearGlass",
        "create": True,
        "properties": {"use_nodes": True}
    }))
    assert not create_glass["result"]["isError"], f"Glass create failed: {create_glass}"
    assign_glass = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "object:RustCube",
        "path": "data.materials",
        "value": "ClearGlass",
        "mode": "append"
    }))
    assert not assign_glass["result"]["isError"]
    assert len(cube_obj.material_slots) == 2
    assert cube_obj.material_slots[1].material.name == "ClearGlass"
    print("   [OK] Added second material slot with ClearGlass")

    # 7c. Verify PBR values directly via RNA
    assert abs(bsdf.inputs["Coat Weight"].default_value - 0.8) < 1e-4
    assert abs(bsdf.inputs["IOR"].default_value - 1.45) < 1e-4
    print("   [OK] Verified PBR Coat Weight 0.8 and IOR 1.45")

    # 7d. Deep object inspection via blender_inspect for Mesh, Camera, and Light
    print("==> Test 7d: blender_inspect (deep object inspection)")
    insp_cube = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {
        "target": "object",
        "name": "RustCube"
    }))
    assert not insp_cube["result"]["isError"]
    cube_data = json.loads(insp_cube["result"]["content"][0]["text"])
    assert cube_data["status"] == "ok"
    assert "mesh_stats" in cube_data and cube_data["mesh_stats"]["vertices"] == 8
    assert len(cube_data["materials"]) == 2
    assert any(m["name"] == "FastBoolean" for m in cube_data["modifiers"])
    print("   [OK] Deep inspected RustCube: verified mesh stats, 2 material slots, and FastBoolean modifier")

    if bpy.data.objects.get("Camera"):
        insp_cam = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {
            "target": "object",
            "name": "Camera"
        }))
        assert not insp_cam["result"]["isError"]
        cam_data = json.loads(insp_cam["result"]["content"][0]["text"])
        assert "camera_stats" in cam_data and cam_data["camera_stats"]["lens"] > 0
        print(f"   [OK] Deep inspected Camera: lens={cam_data['camera_stats']['lens']}mm, type={cam_data['camera_stats']['camera_type']}")

    if bpy.data.objects.get("Light"):
        insp_light = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {
            "target": "object",
            "name": "Light"
        }))
        assert not insp_light["result"]["isError"]
        light_data = json.loads(insp_light["result"]["content"][0]["text"])
        assert "light_stats" in light_data and light_data["light_stats"]["energy"] > 0
        print(f"   [OK] Deep inspected Light: energy={light_data['light_stats']['energy']}W, type={light_data['light_stats']['light_type']}")

    # Test 7.1: blender_manage_nodes (query_type & search)
    print("==> Test 7.1: blender_manage_nodes (query_type with RNA properties)")
    q_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "action": "query_type",
        "node_type": "ShaderNodeMath"
    }))
    assert not q_res["result"]["isError"], f"Query type failed: {q_res}"
    q_data = json.loads(q_res["result"]["content"][0]["text"])
    assert q_data["status"] == "ok"
    assert "properties" in q_data and "operation" in q_data["properties"]
    assert "ADD" in q_data["properties"]["operation"]["enum_items"]
    print("   [OK] Queried ShaderNodeMath sockets and operational properties successfully")

    # Test 7.1b: blender_manage_nodes (search catalog across 550+ nodes)
    print("==> Test 7.1b: blender_manage_nodes (search catalog)")
    s_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "action": "search",
        "query": "extrude",
        "tree_type": "GEOMETRY"
    }))
    assert not s_res["result"]["isError"], f"Search failed: {s_res}"
    s_data = json.loads(s_res["result"]["content"][0]["text"])
    assert s_data["status"] == "ok"
    assert any("ExtrudeMesh" in r["identifier"] for r in s_data["results"])
    print(f"   [OK] Searched 'extrude' in GEOMETRY: matched {s_data['count']} nodes")

    # Test 7.2: blender_manage_nodes (apply_dag on MATERIAL)
    print("==> Test 7.2: blender_manage_nodes (apply_dag on MATERIAL)")
    mat_dag_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "tree_type": "MATERIAL",
        "target": "RustCube",
        "action": "apply_dag",
        "nodes": [
            {
                "id": "noise_tex",
                "type": "ShaderNodeTexNoise",
                "inputs": {"Scale": 12.0}
            },
            {
                "id": "bsdf_node",
                "type": "ShaderNodeBsdfPrincipled",
                "inputs": {"Metallic": 0.8, "Roughness": 0.2}
            },
            {
                "id": "mat_output",
                "type": "ShaderNodeOutputMaterial"
            }
        ],
        "links": [
            {"from": "noise_tex.Color", "to": "bsdf_node.Base Color"},
            {"from": "bsdf_node.BSDF", "to": "mat_output.Surface"}
        ]
    }))
    assert not mat_dag_res["result"]["isError"], f"Material DAG failed: {mat_dag_res}"
    print("   [OK] Wired procedural Material DAG successfully")

    # Test 7.3: blender_manage_nodes (apply_dag on GEOMETRY NODES)
    print("==> Test 7.3: blender_manage_nodes (apply_dag on GEOMETRY NODES)")
    geo_dag_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "tree_type": "GEOMETRY",
        "target": "RustCube",
        "action": "apply_dag",
        "nodes": [
            {
                "id": "cone_mesh",
                "type": "GeometryNodeMeshCone",
                "inputs": {"Radius Top": 0.0, "Radius Bottom": 1.5, "Depth": 3.0}
            },
            {
                "id": "group_out",
                "type": "NodeGroupOutput"
            }
        ],
        "links": [
            {"from": "cone_mesh.Mesh", "to": "group_out.Geometry"}
        ]
    }))
    assert not geo_dag_res["result"]["isError"], f"Geometry DAG failed: {geo_dag_res}"
    print("   [OK] Wired Geometry Nodes procedural cone DAG successfully")

    # Test 7.4: blender_manage_nodes (inspect GEOMETRY NODES)
    print("==> Test 7.4: blender_manage_nodes (inspect GEOMETRY NODES)")
    geo_insp_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "tree_type": "GEOMETRY",
        "target": "RustCube",
        "action": "inspect"
    }))
    assert not geo_insp_res["result"]["isError"], f"Inspect geo failed: {geo_insp_res}"
    insp_geo_data = json.loads(geo_insp_res["result"]["content"][0]["text"])
    assert insp_geo_data["status"] == "ok"
    assert insp_geo_data["nodes_count"] >= 2
    print(f"   [OK] Inspected Geometry Nodes tree: {insp_geo_data['nodes_count']} nodes, {insp_geo_data['links_count']} links")

    # Test 7.5: blender_manage_nodes (COMPOSITING & LINESTYLE trees)
    print("==> Test 7.5: blender_manage_nodes (COMPOSITING & LINESTYLE trees)")
    comp_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "tree_type": "COMPOSITING",
        "action": "inspect",
        "ensure": True
    }))
    assert not comp_res["result"]["isError"], f"Compositing inspect failed: {comp_res}"
    comp_data = json.loads(comp_res["result"]["content"][0]["text"])
    assert comp_data["status"] == "ok"
    print(f"   [OK] Compositing tree initialized & inspected: {comp_data['nodes_count']} nodes")

    ls_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "tree_type": "LINESTYLE",
        "target": "TestLineStyle",
        "action": "inspect",
        "ensure": True
    }))
    assert not ls_res["result"]["isError"], f"LineStyle inspect failed: {ls_res}"
    ls_data = json.loads(ls_res["result"]["content"][0]["text"])
    assert ls_data["status"] == "ok"
    print(f"   [OK] LineStyle tree initialized & inspected: {ls_data['nodes_count']} nodes")

    # Test 8: scene configuration via blender_set + blender_run_operator
    print("==> Test 8: scene setup via blender_set/run_operator")
    camera_obj = bpy.data.objects.get("Camera")
    if camera_obj is not None:
        for args in (
            {"target": "object:Camera", "properties": {"location": [10.0, -10.0, 8.0]}},
            {"target": "object:Camera", "path": "data.lens", "value": 50.0},
            {"target": "object:Camera", "path": "look_at", "value": "RustCube"},
        ):
            res = run_rpc_with_main_loop(lambda a=args: tool_call("blender_set", a))
            assert not res["result"]["isError"], f"Camera setup failed: {res}"

    add_light = run_rpc_with_main_loop(lambda: tool_call("blender_run_operator", {
        "operator": "object.light_add",
        "parameters": {"type": "SUN"},
        "name": "SunLight",
        "properties": {"energy": 5.0}
    }))
    assert not add_light["result"]["isError"], f"Light setup failed: {add_light}"

    render_res = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "scene.render",
        "properties": {
            "engine": "BLENDER_EEVEE",
            "resolution_x": 640,
            "resolution_y": 480,
        }
    }))
    assert not render_res["result"]["isError"], f"Render setup failed: {render_res}"
    samples_res = run_rpc_with_main_loop(lambda: tool_call("blender_set", {
        "target": "scene",
        "path": "eevee",
        "properties": {"taa_render_samples": 16}
    }))
    assert not samples_res["result"]["isError"], f"Sample setup failed: {samples_res}"
    assert bpy.context.scene.render.resolution_x == 640
    assert bpy.context.scene.render.engine == "BLENDER_EEVEE"
    print(f"   [OK] Configured camera look_at, SunLight, {bpy.context.scene.render.engine}, and 640x480 resolution")

    # Test 9: blender_capture
    print("==> Test 9: blender_capture (render to Base64 image with film_transparent)")
    cap_res = run_rpc_with_main_loop(lambda: tool_call("blender_capture", {
        "view": "camera",
        "film_transparent": True,
        "resolution": [320, 240],
        "return_image": True
    }))
    assert not cap_res["result"]["isError"], f"Capture failed: {cap_res}"
    contents = cap_res["result"]["content"]
    img_content = [c for c in contents if c.get("type") == "image"]
    assert len(img_content) > 0, f"Expected image content in response: {cap_res}"
    assert len(img_content[0]["data"]) > 100, "Base64 image data should not be empty!"
    print(f"   [OK] Captured rendered frame: {len(img_content[0]['data'])} Base64 characters (film_transparent=True)")

    # Test 10: blender_execute_script (with pre-injected mathutils, math, C, D)
    print("==> Test 10: blender_execute_script")
    script_code = """
# Test pre-injected symbols: Vector, Matrix, radians, C, D without imports
v1 = Vector((1.0, 2.0, 3.0))
v2 = Vector((4.0, 5.0, 6.0))
dot_prod = v1.dot(v2)
rad = radians(180.0)
m = Matrix.Identity(3)

result = {
    "cube_loc": list(D.objects['RustCube'].location),
    "dot_product": dot_prod,
    "pi_approx": round(rad, 4),
    "scene_name": C.scene.name
}
print(f"Pre-injected test: dot={dot_prod}, pi={round(rad, 4)}")
"""
    exec_res = run_rpc_with_main_loop(lambda: tool_call("blender_execute_script", {
        "code": script_code
    }))
    assert not exec_res["result"]["isError"], f"Script exec failed: {exec_res}"
    exec_data = json.loads(exec_res["result"]["content"][0]["text"])
    assert exec_data["status"] == "ok"
    assert "Pre-injected test" in exec_data["stdout"]
    assert exec_data["result"]["dot_product"] == 32.0
    assert exec_data["result"]["pi_approx"] == 3.1416
    assert exec_data["result"]["scene_name"] == bpy.context.scene.name
    assert len(exec_data["result"]["cube_loc"]) == 3
    assert abs(exec_data["result"]["cube_loc"][0] - 5.0) < 0.01
    print(f"   [OK] Script executed successfully with pre-injected Vector, Matrix, radians, C, D in {exec_data['duration_ms']} ms")

    # Test 11: undo via run_operator
    print("==> Test 11: blender_run_operator (ed.undo)")
    undo_res = run_rpc_with_main_loop(lambda: tool_call("blender_run_operator", {
        "operator": "ed.undo",
        "undo": False
    }))
    assert not undo_res["result"]["isError"], f"Undo failed: {undo_res}"
    print("   [OK] Undo performed cleanly")

    # Stop Server
    print("==> Stopping server...")
    blender_mcp_core.stop_server()
    time.sleep(0.1)
    assert not blender_mcp_core.is_running()
    print("   [OK] Server stopped.")

    print("=" * 60)
    print("ALL 11 INTEGRATION TESTS PASSED SUCCESSFULLY! (100% PASS)")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
