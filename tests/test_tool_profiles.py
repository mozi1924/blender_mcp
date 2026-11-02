# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tool-profile and deprecation tests.

Core profile advertises only the orthogonal adaptive tools; deprecated
compatibility wrappers remain callable by explicit name.
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
PORT = 8801
ENDPOINT = f"http://{HOST}:{PORT}/mcp"

CORE = {
    "blender_describe",
    "blender_inspect",
    "blender_run_operator",
    "blender_set",
    "blender_create_primitive",
    "blender_transform_object",
    "blender_manage_material",
    "blender_manage_modifier",
    "blender_manage_nodes",
    "blender_capture",
    "blender_execute_script",
}
DEPRECATED = {
    "blender_setup_scene",
    "blender_undo",
}


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
        except Exception as ex:  # noqa: BLE001
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


def list_tools():
    res = run_with_main_loop(lambda: rpc_call("tools/list"))
    return {tool["name"]: tool for tool in res["result"]["tools"]}


def tool_call(name, arguments):
    res = run_with_main_loop(
        lambda: rpc_call("tools/call", {"name": name, "arguments": arguments})
    )
    return res["result"]


def payload(result):
    assert not result["isError"], result
    return json.loads(result["content"][0]["text"])


def main():
    print("=" * 60)
    print("Blender MCP tool profile tests")
    print("=" * 60)

    blender_mcp_core.start_server(HOST, PORT)
    time.sleep(0.1)
    try:
        full = list_tools()
        assert len(full) == 13, sorted(full)
        assert CORE <= set(full)
        assert DEPRECATED <= set(full)
        assert full["blender_undo"]["annotations"]["deprecated"] is True
        assert "DEPRECATED" in full["blender_undo"]["description"]
        assert full["blender_undo"]["annotations"]["replacedBy"] == ["blender_run_operator"]
        assert full["blender_set"]["annotations"].get("deprecated") is not True
        print("[OK] full profile: 13 tools with deprecation metadata")

        blender_mcp_core.set_tool_profile("CORE")
        core = list_tools()
        assert set(core) == CORE, sorted(core)
        assert not (DEPRECATED & set(core)), sorted(DEPRECATED & set(core))
        print("[OK] core profile: 11 recommended tools")

        # Hidden tools remain callable by explicit name.
        created = payload(
            tool_call("blender_create_primitive", {"primitive_type": "cube", "name": "HiddenCube"})
        )
        assert bpy.data.objects.get("HiddenCube") is not None
        set_res = payload(
            tool_call(
                "blender_set",
                {"target": "object:HiddenCube", "path": "location", "value": [3, 2, 1]},
            )
        )
        assert set_res["applied"]["location"] == [3.0, 2.0, 1.0]
        print("[OK] deprecated tools still dispatch when called explicitly")

        schemas = payload(
            tool_call("blender_describe", {"target": "tool_schemas", "profile": "full"})
        )
        by_name = {tool["name"]: tool for tool in schemas["tools"]}
        assert by_name["blender_setup_scene"]["deprecated"] is True
        assert by_name["blender_setup_scene"]["profiles"] == ["full"]
        assert by_name["blender_create_primitive"]["deprecated"] is False
        assert by_name["blender_set"]["deprecated"] is False
        print("[OK] blender_describe exposes profile/deprecation metadata")

        blender_mcp_core.set_tool_profile("FULL")
        assert len(list_tools()) == 13
        print("[OK] profile switch back to full")
    finally:
        blender_mcp_core.stop_server()
        time.sleep(0.1)

    print("=" * 60)
    print("ALL TOOL PROFILE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
