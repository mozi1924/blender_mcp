# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
End-to-end tests for the adaptive tool layer:

  blender_describe      -> live RNA introspection
  blender_run_operator  -> validated bpy.ops execution
  blender_run_operator     -> operator-driven primitive creation
  tools/list            -> live Python catalog overriding static Rust schema

Run with: blender -b --python tests/test_adaptive_tools.py
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

import bpy

sys.path.insert(0, "addon/blender_mcp")
import blender_mcp_core

HOST = "127.0.0.1"
PORT = 8800
ENDPOINT = f"http://{HOST}:{PORT}/mcp"


SESSION_ID = None
AUTH_TOKEN = None


def rpc_call(method, params=None, req_id=1):
    global SESSION_ID
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
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

    global SESSION_ID
    SESSION_ID = None
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
        expected_tools = {
            "blender_describe", "blender_inspect", "blender_run_operator",
            "blender_set", "blender_manage_modifier", "blender_manage_nodes",
            "blender_capture", "blender_execute_script", "blender_manage_hierarchy",
            "blender_manage_file",
        }
        assert set(tools) == expected_tools, sorted(tools)
        run_op = tools["blender_run_operator"]["inputSchema"]["properties"]
        assert "primitive_type" in run_op and "properties" in run_op
        set_schema = tools["blender_set"]["inputSchema"]["properties"]
        assert set(set_schema["mode"]["enum"]) == {"absolute", "relative", "append"}
        assert "create" in set_schema and "origin_to" in set_schema
        assert len(
            tools["blender_manage_modifier"]["inputSchema"]["properties"]["modifier_type"].get("enum", [])
        ) > 50
        assert "MESH" in tools["blender_inspect"]["inputSchema"]["properties"]["object_type"]["enum"]
        hier_props = tools["blender_manage_hierarchy"]["inputSchema"]["properties"]
        assert "OBJECT" in hier_props["parent_type"]["enum"]
        assert "COLOR_01" in hier_props["color_tag"]["enum"]
        assert tools["blender_describe"]["annotations"]["readOnlyHint"] is True
        assert tools["blender_inspect"]["annotations"]["readOnlyHint"] is True
        assert tools["blender_set"]["annotations"]["destructiveHint"] is True
        assert tools["blender_manage_hierarchy"]["annotations"]["destructiveHint"] is True
        print(f"[OK] tools/list exposes {len(tools)} consolidated tools")

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
                "blender_run_operator",
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
        monkey = payload(tool_call("blender_run_operator", {"primitive_type": "monkey"}))
        assert bpy.data.objects[monkey["created_object"]["name"]].type == "MESH"
        print("[OK] adaptive monkey primitive (not in the old enum)")

        # 9. Deferred data properties (light size/energy) resolve against Light RNA.
        light = payload(
            tool_call(
                "blender_run_operator",
                {
                    "primitive_type": "light",
                    "parameters": {"type": "AREA"},
                    "properties": {
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
            "blender_run_operator",
            {"primitive_type": "cube", "parameters": {"radii": 2.0}},
        )
        text = error_payload(bad_primitive)
        assert "radii" in text and "Did you mean" in text
        print("[OK] run_operator primitive rejects unknown parameters")

        # 10a. Read-only node inspection must not create a Geometry Nodes modifier.
        before_nodes_mods = [m.name for m in bpy.data.objects["AdaptiveTorus"].modifiers if m.type == "NODES"]
        read_only = payload(
            tool_call(
                "blender_manage_nodes",
                {"tree_type": "GEOMETRY", "target": "AdaptiveTorus", "action": "inspect"},
            )
        )
        after_nodes_mods = [m.name for m in bpy.data.objects["AdaptiveTorus"].modifiers if m.type == "NODES"]
        assert before_nodes_mods == after_nodes_mods == []
        assert read_only["nodes_count"] == 0 and "note" in read_only
        print("[OK] node inspect is read-only (no implicit modifier/tree creation)")

        # 10b. Generic RNA setter (consolidation path).
        set_loc = payload(
            tool_call(
                "blender_set",
                {"target": "object:AdaptiveTorus", "path": "location", "value": [1.0, 2.0, 3.0]},
            )
        )
        assert set_loc["applied"]["location"] == [1.0, 2.0, 3.0]
        set_rot = payload(
            tool_call(
                "blender_set",
                {
                    "target": "object:AdaptiveTorus",
                    "path": "rotation_euler",
                    "value": [90.0, 0.0, 0.0],
                    "unit": "degrees",
                },
            )
        )
        assert abs(bpy.data.objects["AdaptiveTorus"].rotation_euler[0] - 1.5707963) < 1e-4
        set_render = payload(
            tool_call(
                "blender_set",
                {
                    "target": "scene.render",
                    "properties": {"resolution_x": 512, "resolution_y": 384},
                },
            )
        )
        assert set_render["applied"]["resolution_x"] == 512
        print("[OK] blender_set: object transform + render settings")

        create_mat = payload(
            tool_call(
                "blender_set",
                {
                    "target": "material:SetMat",
                    "create": True,
                    "properties": {"use_nodes": True},
                },
            )
        )
        assign_mat = payload(
            tool_call(
                "blender_set",
                {
                    "target": "object:AdaptiveTorus",
                    "path": "data.materials",
                    "value": "SetMat",
                    "mode": "append",
                },
            )
        )
        set_mat = bpy.data.materials["SetMat"]
        bsdf_name = next(
            node.name for node in set_mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
        )
        set_color = payload(
            tool_call(
                "blender_set",
                {
                    "target": "material:SetMat",
                    "path": f"node_tree.nodes[{bsdf_name}].inputs[Base Color].default_value",
                    "value": "#00FF00",
                },
            )
        )
        assert set_color["status"] == "ok"
        color = set_mat.node_tree.nodes[bsdf_name].inputs["Base Color"].default_value
        assert abs(color[1] - 1.0) < 1e-4
        print("[OK] blender_set: material create/append + node socket color")

        mod = payload(
            tool_call(
                "blender_manage_modifier",
                {"object_name": "AdaptiveTorus", "action": "add", "modifier_type": "SUBSURF"},
            )
        )
        set_mod = payload(
            tool_call(
                "blender_set",
                {
                    "target": "modifier:AdaptiveTorus/Subsurf",
                    "properties": {"levels": 2, "render_levels": 3},
                },
            )
        )
        assert set_mod["applied"]["levels"] == 2
        print("[OK] blender_set: modifier properties via path")

        bad_set = tool_call(
            "blender_set",
            {"target": "object:AdaptiveTorus", "path": "locaton", "value": [0, 0, 0]},
        )
        assert "Did you mean" in error_payload(bad_set)
        print("[OK] blender_set: unknown path suggestions")

        # 10c. look_at convenience replaces setup_scene's camera aiming.
        cam_data = bpy.data.cameras.new("LookCamData")
        cam_obj = bpy.data.objects.new("LookCam", cam_data)
        bpy.context.scene.collection.objects.link(cam_obj)
        cam_obj.location = (5.0, -5.0, 5.0)
        aim = payload(
            tool_call(
                "blender_set",
                {"target": "object:LookCam", "path": "look_at", "value": "AdaptiveTorus"},
            )
        )
        assert any(abs(value) > 1e-4 for value in cam_obj.rotation_euler), cam_obj.rotation_euler
        print("[OK] transform look_at covers camera aiming")

        # 11. Scene configuration via blender_set + blender_run_operator.
        cam_move = payload(
            tool_call(
                "blender_set",
                {"target": "object:LookCam", "properties": {"location": [8.0, -8.0, 6.0]}},
            )
        )
        cam_aim = payload(
            tool_call(
                "blender_set",
                {"target": "object:LookCam", "path": "look_at", "value": [0.0, 0.0, 0.0]},
            )
        )
        sun = payload(
            tool_call(
                "blender_run_operator",
                {
                    "operator": "object.light_add",
                    "parameters": {"type": "SUN"},
                    "name": "AdaptiveSun",
                    "properties": {"energy": 3.0},
                },
            )
        )
        render = payload(
            tool_call(
                "blender_set",
                {
                    "target": "scene.render",
                    "properties": {
                        "engine": "BLENDER_EEVEE",
                        "resolution_x": 320,
                        "resolution_y": 240,
                    },
                },
            )
        )
        samples = payload(
            tool_call(
                "blender_set",
                {"target": "scene", "path": "eevee", "properties": {"taa_render_samples": 16}},
            )
        )
        world_obj = bpy.context.scene.world
        bg_name = next(
            node.name for node in world_obj.node_tree.nodes if node.type == "BACKGROUND"
        )
        world = payload(
            tool_call(
                "blender_set",
                {
                    "target": "world",
                    "path": f"node_tree.nodes[{bg_name}].inputs[Color].default_value",
                    "value": "#0D0D14",
                },
            )
        )
        assert bpy.context.scene.render.engine == "BLENDER_EEVEE"
        assert bpy.context.scene.render.resolution_x == 320
        assert bpy.context.scene.eevee.taa_render_samples == 16
        print("[OK] scene setup via blender_set + run_operator")

        # 16. Hierarchy management: collections and transform-preserved parenting
        col_res = payload(
            tool_call(
                "blender_manage_hierarchy",
                {
                    "action": "create_collection",
                    "collection": "AdaptiveAssets",
                    "color_tag": "COLOR_04",
                },
            )
        )
        assert col_res["status"] == "ok"
        assert col_res["collection"] == "AdaptiveAssets"

        # Spawn a chassis and two wheels via operator
        payload(
            tool_call(
                "blender_run_operator",
                {
                    "primitive_type": "box",
                    "name": "Chassis",
                    "location": [0.0, 0.0, 1.0],
                },
            )
        )
        payload(
            tool_call(
                "blender_run_operator",
                {
                    "primitive_type": "cylinder",
                    "name": "Wheel_L",
                    "location": [-1.5, 0.0, 0.5],
                },
            )
        )
        payload(
            tool_call(
                "blender_run_operator",
                {
                    "primitive_type": "cylinder",
                    "name": "Wheel_R",
                    "location": [1.5, 0.0, 0.5],
                },
            )
        )

        # Move to AdaptiveAssets collection
        move_res = payload(
            tool_call(
                "blender_manage_hierarchy",
                {
                    "action": "move_to_collection",
                    "collection": "AdaptiveAssets",
                    "objects": ["Chassis", "Wheel_L", "Wheel_R"],
                    "mode": "move",
                },
            )
        )
        assert move_res["status"] == "ok"
        assert len(move_res["objects"]) == 3
        assert "Wheel_L" in bpy.data.collections["AdaptiveAssets"].objects

        # Parent wheels to Chassis keeping transform
        parent_res = payload(
            tool_call(
                "blender_manage_hierarchy",
                {
                    "action": "set_parent",
                    "parent": "Chassis",
                    "children": ["Wheel_L", "Wheel_R"],
                    "keep_transform": True,
                },
            )
        )
        assert parent_res["status"] == "ok"
        wheel_l = bpy.data.objects["Wheel_L"]
        assert wheel_l.parent.name == "Chassis"
        # World coordinates preserved: x should still be -1.5
        assert round(wheel_l.matrix_world.translation.x, 3) == -1.5

        # Move chassis by +2 in X and verify wheel followed in world space
        bpy.data.objects["Chassis"].location.x += 2.0
        bpy.context.view_layer.update()
        assert round(wheel_l.matrix_world.translation.x, 3) == 0.5

        # Clear parent of Wheel_R keeping transform
        clear_res = payload(
            tool_call(
                "blender_manage_hierarchy",
                {
                    "action": "clear_parent",
                    "objects": ["Wheel_R"],
                    "keep_transform": True,
                },
            )
        )
        assert clear_res["status"] == "ok"
        wheel_r = bpy.data.objects["Wheel_R"]
        assert wheel_r.parent is None
        # World position of Wheel_R was 1.5 + 2 = 3.5
        assert round(wheel_r.matrix_world.translation.x, 3) == 3.5

        # Inspect hierarchy
        insp_hier = payload(
            tool_call(
                "blender_manage_hierarchy",
                {
                    "action": "inspect",
                    "target": "all",
                },
            )
        )
        assert insp_hier["status"] == "ok"
        assert "collections" in insp_hier
        assert "root_objects" in insp_hier
        print("[OK] blender_manage_hierarchy: collections and transform-preserved parenting")

        # 17. Multi-scene and view layer support across inspect, manage_nodes, and capture
        extra_scene = bpy.data.scenes.new("TestMultiScene")
        extra_cam_data = bpy.data.cameras.new("MultiCamData")
        extra_cam = bpy.data.objects.new("MultiCam", extra_cam_data)
        extra_scene.collection.objects.link(extra_cam)
        extra_scene.camera = extra_cam

        # 17a. blender_inspect on non-active scene
        insp_scene = payload(
            tool_call(
                "blender_inspect",
                {"target": "scene", "scene": "TestMultiScene"},
            )
        )
        assert insp_scene["status"] == "ok"
        assert insp_scene["scene"] == "TestMultiScene"
        assert insp_scene["is_active_scene"] is False
        assert "view_layers" in insp_scene

        # 17b. blender_manage_nodes (COMPOSITING) on non-active scene
        comp_scene = payload(
            tool_call(
                "blender_manage_nodes",
                {
                    "tree_type": "COMPOSITING",
                    "scene": "TestMultiScene",
                    "action": "apply_dag",
                    "ensure": True,
                    "nodes": [
                        {"id": "Invert", "type": "CompositorNodeInvert"}
                    ],
                },
            )
        )
        assert comp_scene["status"] == "ok"
        assert extra_scene.compositing_node_group is not None
        assert "TestMultiScene" in extra_scene.compositing_node_group.name

        # 17c. blender_capture with scene parameter
        cap_scene = payload(
            tool_call(
                "blender_capture",
                {
                    "scene": "TestMultiScene",
                    "resolution": [160, 120],
                    "return_image": False,
                },
            )
        )
        assert cap_scene["status"] == "ok"
        assert cap_scene["scene"] == "TestMultiScene"
        print("[OK] multi-scene and view layer support across inspect, manage_nodes, capture")

        # 18. blender_manage_file: save_as copy, preview, and append
        import tempfile
        tmp_blend = os.path.join(tempfile.gettempdir(), "test_adaptive_file.blend")
        save_res = payload(tool_call("blender_manage_file", {"action": "save_as", "filepath": tmp_blend, "copy": True}))
        assert save_res["status"] == "ok"
        assert os.path.exists(tmp_blend)

        prev_res = payload(tool_call("blender_manage_file", {"action": "preview", "filepath": tmp_blend}))
        assert prev_res["status"] == "ok"
        assert "collections" in prev_res["datablocks"]

        append_res = payload(tool_call("blender_manage_file", {"action": "append", "filepath": tmp_blend, "datablock_type": "collections", "names": ["Collection"]}))
        assert append_res["status"] == "ok"
        assert "collections" in append_res["loaded"]

        pack_res = payload(tool_call("blender_manage_file", {"action": "pack_resources", "mode": "make_relative"}))
        assert pack_res["status"] == "ok"
        if os.path.exists(tmp_blend):
            os.remove(tmp_blend)
        print("[OK] blender_manage_file: save_as, preview, append, pack_resources verified")

        # 19. blender_manage_hierarchy: delete_object
        tool_call("blender_run_operator", {"primitive_type": "box", "name": "BoxToDelete"})
        assert bpy.data.objects.get("BoxToDelete") is not None
        del_res = payload(tool_call("blender_manage_hierarchy", {"action": "delete_object", "objects": ["BoxToDelete"], "delete_data": True}))
        assert del_res["status"] == "ok"
        assert "BoxToDelete" in del_res["deleted_objects"]
        assert bpy.data.objects.get("BoxToDelete") is None
        print("[OK] blender_manage_hierarchy: delete_object verified")

        # 20. blender_inspect: world_bound_box and raycast
        tool_call("blender_run_operator", {"primitive_type": "box", "name": "RaycastCube", "location": [0, 0, 0]})
        insp_cube = payload(tool_call("blender_inspect", {"target": "object", "name": "RaycastCube"}))
        assert "world_bound_box" in insp_cube
        assert "min" in insp_cube["world_bound_box"] and "max" in insp_cube["world_bound_box"]

        ray_res = payload(tool_call("blender_inspect", {"target": "raycast", "origin": [0, 0, 5], "direction": [0, 0, -1]}))
        assert ray_res["status"] == "ok"
        assert ray_res["hit"] is True
        assert ray_res["hit_object"] is not None
        print("[OK] blender_inspect: world_bound_box and raycast verified")

        # 21. blender_set: armature pose bone and pose batch setting
        arm_data = bpy.data.armatures.new("TestArmature")
        arm_obj = bpy.data.objects.new("TestArmature", arm_data)
        bpy.context.scene.collection.objects.link(arm_obj)
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm_data.edit_bones.new("Bone1")
        eb.head = (0, 0, 0)
        eb.tail = (0, 0, 1)
        bpy.ops.object.mode_set(mode='OBJECT')

        pose_set_res = payload(tool_call("blender_set", {
            "target": "pose_bone:TestArmature/Bone1",
            "path": "rotation_deg",
            "value": [45, 0, 0],
        }))
        assert pose_set_res["status"] == "ok"

        batch_pose_res = payload(tool_call("blender_set", {
            "target": "pose:TestArmature",
            "properties": {"Bone1": {"rotation_deg": [15, 20, 0]}},
        }))
        assert batch_pose_res["status"] == "ok"
        assert "Bone1" in batch_pose_res["applied_bones"]
        print("[OK] blender_set: pose_bone and batch pose setting verified")

        # 22. blender_describe: addons, render_devices, and dynamic io_formats
        addons_res = payload(tool_call("blender_describe", {"target": "addons"}))
        assert addons_res["status"] == "ok"
        assert "addons" in addons_res and addons_res["count"] > 0

        dev_res = payload(tool_call("blender_describe", {"target": "render_devices"}))
        assert dev_res["status"] == "ok"
        assert "gpu_platform" in dev_res and "cycles" in dev_res
        print("[OK] blender_describe: addons and render_devices verified")

        io_res = payload(tool_call("blender_describe", {"target": "io_formats"}))
        assert io_res["status"] == "ok"
        assert "supported_import_formats" in io_res
        assert "supported_export_formats" in io_res
        for expected_fmt in ("obj", "ply", "stl", "usd", "abc"):
            assert expected_fmt in io_res["supported_import_formats"], f"Expected {expected_fmt} in import formats"
            assert expected_fmt in io_res["supported_export_formats"], f"Expected {expected_fmt} in export formats"

        io_query_res = payload(tool_call("blender_describe", {"target": "io_formats", "query": "obj"}))
        assert io_query_res["status"] == "ok"
        assert "obj" in io_query_res["importers"]
        print("[OK] blender_describe: dynamic RNA io_formats discovery and query verified")

        # 23. blender_manage_file: dynamic format export without hardcoding
        tmp_obj = os.path.join(tempfile.gettempdir(), "test_export.obj")
        exp_res = payload(tool_call("blender_manage_file", {
            "action": "export_format",
            "filepath": tmp_obj,
            "format": "obj",
        }))
        assert exp_res["status"] == "ok"
        assert exp_res["format"] == "obj"
        assert os.path.exists(tmp_obj)
        if os.path.exists(tmp_obj):
            os.remove(tmp_obj)
        mtl_file = tmp_obj.replace(".obj", ".mtl")
        if os.path.exists(mtl_file):
            os.remove(mtl_file)
        print("[OK] blender_manage_file: dynamic format export verified")
    finally:
        blender_mcp_core.stop_server()
        time.sleep(0.1)

    print("=" * 60)
    print("ALL ADAPTIVE TOOL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
