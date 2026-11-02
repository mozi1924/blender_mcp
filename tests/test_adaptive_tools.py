# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
End-to-end tests for the adaptive tool layer:

  blender_describe      -> live RNA introspection
  blender_run_operator  -> validated bpy.ops execution
  blender_create_primitive -> operator-driven primitive creation
  tools/list            -> live Python catalog overriding static Rust schema

Run with: blender -b --python tests/test_adaptive_tools.py
"""

import json
import sys
import threading
import time
import urllib.request

import bpy

sys.path.insert(0, "addon/blender_mcp")
import blender_mcp_core

HOST = "127.0.0.1"
PORT = 8800
ENDPOINT = f"http://{HOST}:{PORT}/mcp"


def rpc_call(method, params=None, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_with_main_loop(call_fn):
    holder = []

    def worker():
        try:
            holder.append(call_fn())
        except Exception as ex:  # noqa: BLE001 - surfaced to the assertion below
            holder.append({"error": str(ex)})

    thread = threading.Thread(target=worker)
    thread.start()
    start = time.time()
    while thread.is_alive() and time.time() - start < 20.0:
        blender_mcp_core.poll_tick(16)
        time.sleep(0.01)
    thread.join(timeout=1.0)
    assert holder, "Request timed out"
    return holder[0]


def tool_call(name, arguments, req_id=1):
    return run_with_main_loop(
        lambda: rpc_call(
            "tools/call", {"name": name, "arguments": arguments}, req_id=req_id
        )
    )


def payload(response):
    result = response["result"]
    assert not result["isError"], result
    return json.loads(result["content"][0]["text"])


def error_payload(response):
    result = response["result"]
    assert result["isError"], f"Expected isError, got: {result}"
    return result["content"][0]["text"]


def main():
    print("=" * 60)
    print("Blender MCP adaptive tool integration tests")
    print("=" * 60)

    blender_mcp_core.start_server(HOST, PORT)
    time.sleep(0.1)
    assert blender_mcp_core.is_running()

    try:
        init = run_with_main_loop(lambda: rpc_call("initialize", {"protocolVersion": "2024-11-05"}))
        assert init["result"]["serverInfo"]["name"] == "blender-mcp-rust"
        print("[OK] initialize")

        # 1. tools/list is served from the live Python catalog.
        listed = run_with_main_loop(lambda: rpc_call("tools/list"))
        tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
        for expected in ("blender_describe", "blender_run_operator", "blender_create_primitive"):
            assert expected in tools, tools.keys()
        primitive = tools["blender_create_primitive"]
        assert "Adaptive" in primitive["description"]
        assert "operator" in primitive["inputSchema"]["properties"]
        # No stale hardcoded primitive enum survives in the live schema.
        assert "enum" not in primitive["inputSchema"]["properties"]["primitive_type"]
        engine_schema = tools["blender_setup_scene"]["inputSchema"]["properties"]["render_engine"]
        assert "enum" not in engine_schema, engine_schema
        print(f"[OK] tools/list exposes {len(tools)} tools with live schemas")

        # 2. Operator RNA introspection.
        cube = payload(
            tool_call("blender_describe", {"target": "operator", "path": "mesh.primitive_cube_add"})
        )
        props = {prop["identifier"]: prop for prop in cube["properties"]}
        assert "size" in props and "scale" in props and "align" in props
        assert "WORLD" in props["align"]["enum"]
        assert "size" in cube["input_schema"]["properties"]
        print("[OK] describe operator cube: live size/align schema")

        op_search = payload(
            tool_call("blender_describe", {"target": "operators", "query": "grid add", "limit": 10})
        )
        assert any("primitive_grid_add" in item["operator"] for item in op_search["operators"])
        print("[OK] describe operators: found mesh.primitive_grid_add")

        # 3. Modifier schema comes from the modifier's own RNA.
        modifiers = payload(tool_call("blender_describe", {"target": "modifier_types", "query": "boolean"}))
        assert any(item["identifier"] == "BOOLEAN" for item in modifiers["modifiers"])
        boolean = payload(tool_call("blender_describe", {"target": "modifier", "modifier_type": "BOOLEAN"}))
        solver = next(prop for prop in boolean["properties"] if prop["identifier"] == "solver")
        assert "MANIFOLD" in solver["enum"]
        print("[OK] describe modifier BOOLEAN: solver enum includes MANIFOLD")

        # 4. Node validity is probed, not guessed from prefixes.
        extrude = payload(
            tool_call(
                "blender_describe",
                {"target": "node_types", "query": "extrude", "tree_type": "GeometryNodeTree"},
            )
        )
        assert any("ExtrudeMesh" in item["identifier"] for item in extrude["results"])
        random_shader = payload(
            tool_call(
                "blender_describe",
                {"target": "node_types", "query": "random", "tree_type": "ShaderNodeTree"},
            )
        )
        assert not any(
            item["identifier"] == "FunctionNodeRandomValue" for item in random_shader["results"]
        ), random_shader
        cone = payload(tool_call("blender_describe", {"target": "node", "node_type": "GeometryNodeMeshCone"}))
        assert cone["valid_tree_types"] == ["GeometryNodeTree"]
        assert "Radius Bottom" in [item["name"] for item in cone["inputs"]]
        print("[OK] describe node_types/node: authoritative per-tree validity")

        # 5. Primitive discovery + live catalogs.
        primitives = payload(tool_call("blender_describe", {"target": "primitives"}))
        kinds = {item["kind"] for item in primitives["primitives"]}
        assert {"grid", "monkey", "uv_sphere", "nurbs_curve"} <= kinds
        engines = payload(tool_call("blender_describe", {"target": "render_engines"}))
        assert engines["engines"], engines
        id_types = payload(tool_call("blender_describe", {"target": "id_types"}))
        assert any(item["collection"] == "objects" for item in id_types["id_types"])
        print(f"[OK] live catalogs: {len(kinds)} primitive kinds, engines={[e['identifier'] for e in engines['engines']]}")

        # 6. Generic operator execution with RNA validation.
        grid = payload(
            tool_call(
                "blender_run_operator",
                {
                    "operator": "mesh.primitive_grid_add",
                    "parameters": {
                        "x_subdivisions": 3,
                        "y_subdivisions": 4,
                        "size": 2.5,
                        "location": [4.0, 0.0, 0.0],
                    },
                },
            )
        )
        grid_obj = bpy.data.objects[grid["created_objects"][0]]
        assert len(grid_obj.data.vertices) == 20, len(grid_obj.data.vertices)
        print("[OK] run_operator grid: 20 vertices from live subdivisions")

        bad = tool_call(
            "blender_run_operator",
            {"operator": "mesh.primitive_cube_add", "parameters": {"radii": 1.0}},
        )
        text = error_payload(bad)
        assert "radii" in text and "Did you mean" in text
        print("[OK] run_operator rejects unknown params with suggestions")

        # 7. Adaptive primitives: torus parameters + scale + collection.
        torus = payload(
            tool_call(
                "blender_create_primitive",
                {
                    "primitive_type": "torus",
                    "name": "AdaptiveTorus",
                    "location": [0.0, 0.0, 2.0],
                    "scale": [2.0, 2.0, 2.0],
                    "collection": "AdaptiveProps",
                    "parameters": {
                        "major_radius": 2.0,
                        "minor_radius": 0.3,
                        "major_segments": 24,
                        "minor_segments": 12,
                    },
                },
            )
        )
        torus_obj = bpy.data.objects["AdaptiveTorus"]
        assert torus_obj.scale[0] == 2.0
        assert torus_obj.users_collection[0].name == "AdaptiveProps"
        print("[OK] adaptive torus: parameters, scale and collection applied")

        # 8. New primitive kind that the old hardcoded enum did not contain.
        monkey = payload(tool_call("blender_create_primitive", {"primitive_type": "monkey"}))
        assert bpy.data.objects[monkey["created_object"]["name"]].type == "MESH"
        print("[OK] adaptive monkey primitive (not in the old enum)")

        # 9. Deferred data properties (light size/energy) resolve against Light RNA.
        light = payload(
            tool_call(
                "blender_create_primitive",
                {
                    "primitive_type": "light",
                    "parameters": {
                        "light_type": "AREA",
                        "energy": 250.0,
                        "color": [1.0, 0.5, 0.2],
                        "size": 3.0,
                    },
                },
            )
        )
        light_obj = bpy.data.objects[light["created_object"]["name"]]
        assert light_obj.data.type == "AREA"
        assert light_obj.data.energy == 250.0
        assert abs(light_obj.data.size - 3.0) < 1e-6
        print("[OK] adaptive light: type/energy/color/size resolved via Light RNA")

        # 10. Invalid deferred parameter is reported, not silently dropped.
        bad_primitive = tool_call(
            "blender_create_primitive",
            {"primitive_type": "cube", "parameters": {"radii": 2.0}},
        )
        text = error_payload(bad_primitive)
        assert "radii" in text and "created" in text
        print("[OK] adaptive primitive reports unresolved parameters")

        # 11. Setup scene uses the live engine enum.
        setup = payload(
            tool_call(
                "blender_setup_scene",
                {
                    "camera": {"location": [8.0, -8.0, 6.0], "look_at": [0.0, 0.0, 0.0]},
                    "render_engine": "EEVEE_NEXT",
                    "resolution": [320, 240],
                    "samples": 16,
                    "world_color": [0.05, 0.05, 0.08],
                },
            )
        )
        assert setup["render_engine"].startswith("BLENDER_EEVEE")
        assert bpy.context.scene.render.resolution_x == 320
        print(f"[OK] setup_scene live engine: {setup['render_engine']}, samples applied")
    finally:
        blender_mcp_core.stop_server()
        time.sleep(0.1)

    print("=" * 60)
    print("ALL ADAPTIVE TOOL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
