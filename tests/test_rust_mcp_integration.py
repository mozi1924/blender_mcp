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

def rpc_call(method, params=None, req_id=1):
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method
    }
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
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
        "blender_inspect", "blender_capture", "blender_create_primitive",
        "blender_transform_object", "blender_manage_modifier",
        "blender_manage_material", "blender_setup_scene",
        "blender_manage_nodes", "blender_execute_script", "blender_undo"
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
    print("   [OK] blender_inspect (scene) passed")

    insp_blocks = run_rpc_with_main_loop(lambda: tool_call("blender_inspect", {"target": "datablocks"}))
    assert not insp_blocks["result"]["isError"]
    blocks_data = json.loads(insp_blocks["result"]["content"][0]["text"])
    assert "meshes" in blocks_data
    print("   [OK] blender_inspect (datablocks) passed")

    # Test 4: blender_create_primitive
    print("==> Test 4: blender_create_primitive")
    create_res = run_rpc_with_main_loop(lambda: tool_call("blender_create_primitive", {
        "primitive_type": "cube",
        "name": "RustCube",
        "location": [2.0, 3.0, 4.0],
        "scale": [1.5, 1.5, 1.5]
    }))
    assert not create_res["result"]["isError"], f"Create primitive failed: {create_res}"
    cube_obj = bpy.data.objects.get("RustCube")
    assert cube_obj is not None, "RustCube should exist in bpy.data.objects!"
    print("   [OK] Created RustCube at", list(cube_obj.location))

    # Test 5: blender_transform_object
    print("==> Test 5: blender_transform_object")
    trans_res = run_rpc_with_main_loop(lambda: tool_call("blender_transform_object", {
        "name": "RustCube",
        "location": [5.0, 5.0, 5.0],
        "rotation": [45.0, 0.0, 0.0],
        "mode": "absolute"
    }))
    assert not trans_res["result"]["isError"], f"Transform failed: {trans_res}"
    assert cube_obj.location[0] == 5.0
    print("   [OK] Transformed RustCube location to", list(cube_obj.location))

    # Test 6: blender_manage_modifier
    print("==> Test 6: blender_manage_modifier (add subsurf)")
    mod_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_modifier", {
        "object_name": "RustCube",
        "action": "add",
        "modifier_type": "SUBSURF",
        "properties": {"levels": 2, "render_levels": 3}
    }))
    assert not mod_res["result"]["isError"], f"Modifier add failed: {mod_res}"
    mod = cube_obj.modifiers.get("Subsurf")
    assert mod is not None and mod.levels == 2, f"Subsurf modifier mismatch: {mod}"
    print("   [OK] Added Subsurf modifier (levels=2) to RustCube")

    # Test 7: blender_manage_material
    print("==> Test 7: blender_manage_material")
    mat_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_material", {
        "object_name": "RustCube",
        "action": "create_and_assign",
        "material_name": "MetallicBlue",
        "base_color": "#0088FF",
        "metallic": 0.9,
        "roughness": 0.1
    }))
    assert not mat_res["result"]["isError"], f"Material assign failed: {mat_res}"
    assert cube_obj.data.materials[0].name == "MetallicBlue"
    print("   [OK] Created & assigned MetallicBlue material (metallic=0.9, roughness=0.1)")

    # Test 7.1: blender_manage_nodes (query_type)
    print("==> Test 7.1: blender_manage_nodes (query_type)")
    q_res = run_rpc_with_main_loop(lambda: tool_call("blender_manage_nodes", {
        "action": "query_type",
        "node_type": "ShaderNodeTexNoise"
    }))
    assert not q_res["result"]["isError"], f"Query type failed: {q_res}"
    q_data = json.loads(q_res["result"]["content"][0]["text"])
    assert q_data["status"] == "ok"
    assert any(s["name"] == "Scale" for s in q_data["inputs"])
    print("   [OK] Queried ShaderNodeTexNoise sockets successfully")

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

    # Test 8: blender_setup_scene
    print("==> Test 8: blender_setup_scene")
    setup_res = run_rpc_with_main_loop(lambda: tool_call("blender_setup_scene", {
        "camera": {"location": [10.0, -10.0, 8.0], "look_at": "RustCube", "focal_length": 50.0},
        "light": {"name": "SunLight", "type": "SUN", "energy": 5.0},
        "render_engine": "BLENDER_EEVEE_NEXT",
        "resolution": [640, 480]
    }))
    assert not setup_res["result"]["isError"], f"Setup scene failed: {setup_res}"
    assert bpy.context.scene.render.resolution_x == 640
    assert bpy.context.scene.render.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")
    print(f"   [OK] Configured camera look_at, SunLight, {bpy.context.scene.render.engine}, and 640x480 resolution")

    # Test 9: blender_capture
    print("==> Test 9: blender_capture (render to Base64 image)")
    cap_res = run_rpc_with_main_loop(lambda: tool_call("blender_capture", {
        "view": "camera",
        "resolution": [320, 240],
        "return_image": True
    }))
    assert not cap_res["result"]["isError"], f"Capture failed: {cap_res}"
    contents = cap_res["result"]["content"]
    img_content = [c for c in contents if c.get("type") == "image"]
    assert len(img_content) > 0, f"Expected image content in response: {cap_res}"
    assert len(img_content[0]["data"]) > 100, "Base64 image data should not be empty!"
    print(f"   [OK] Captured rendered frame: {len(img_content[0]['data'])} Base64 characters")

    # Test 10: blender_execute_script (with auto undo)
    print("==> Test 10: blender_execute_script")
    script_code = """
import bpy
# Calculate volume approximation
result = {"cube_loc": list(bpy.data.objects['RustCube'].location)}
print("Hello from procedural script!")
"""
    exec_res = run_rpc_with_main_loop(lambda: tool_call("blender_execute_script", {
        "code": script_code
    }))
    assert not exec_res["result"]["isError"], f"Script exec failed: {exec_res}"
    exec_data = json.loads(exec_res["result"]["content"][0]["text"])
    assert exec_data["status"] == "ok"
    assert "Hello from procedural script!" in exec_data["stdout"]
    assert exec_data["result"]["cube_loc"] == [5.0, 5.0, 5.0]
    print(f"   [OK] Script executed successfully in {exec_data['duration_ms']} ms with captured stdout")

    # Test 11: blender_undo
    print("==> Test 11: blender_undo")
    undo_res = run_rpc_with_main_loop(lambda: tool_call("blender_undo", {}))
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
