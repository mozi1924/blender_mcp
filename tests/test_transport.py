# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transport-layer tests: sessions, Streamable HTTP, SSE, auth and CORS."""

import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "addon/blender_mcp")
import blender_mcp_core

HOST = "127.0.0.1"
PORT = 8802
BASE = f"http://{HOST}:{PORT}"
TOKEN = "transport-secret"


def http(method, path, payload=None, headers=None, token=True):
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    if token:
        request_headers.setdefault("Authorization", f"Bearer {TOKEN}")
    request = urllib.request.Request(
        BASE + path, data=body, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def initialize(protocol_version="2025-03-26"):
    status, headers, body = http(
        "POST",
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "transport-test", "version": "1.0"},
            },
        },
        {"Accept": "application/json"},
    )
    assert status == 200, (status, body)
    session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    assert session, headers
    return session, json.loads(body)


def main():
    print("=" * 60)
    print("Blender MCP transport tests")
    print("=" * 60)

    blender_mcp_core.start_server(HOST, PORT, TOKEN, 10)
    time.sleep(0.1)
    try:
        # 1. Auth is enforced before JSON-RPC handling.
        status, _headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            token=False,
        )
        assert status == 401, (status, body)
        print("[OK] unauthenticated request rejected with 401")

        # 2. Initialize returns a session id and negotiates a supported version.
        session, init = initialize("2025-03-26")
        assert init["result"]["protocolVersion"] == "2025-03-26", init
        assert init["result"]["serverInfo"]["name"] == "blender-mcp-rust"
        print("[OK] initialize created session and negotiated protocol version")

        # 3. Unsupported protocol version falls back to the latest supported.
        latest_session, latest = initialize("1900-01-01")
        assert latest["result"]["protocolVersion"] == "2025-06-18", latest
        print("[OK] unsupported protocol version falls back to latest")

        # 4. Session header is required after initialize.
        status, _headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"Accept": "application/json"},
        )
        assert status == 400, (status, body)
        print("[OK] missing Mcp-Session-Id rejected with 400")

        status, _headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            {"Accept": "application/json", "Mcp-Session-Id": "not-a-session"},
        )
        assert status == 404, (status, body)
        print("[OK] unknown session rejected with 404")

        # 4b. Mismatched MCP-Protocol-Version is rejected.
        status, _headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 31, "method": "tools/list"},
            {
                "Accept": "application/json",
                "Mcp-Session-Id": session,
                "Mcp-Protocol-Version": "2024-11-05",
            },
        )
        assert status == 400, (status, body)
        print("[OK] mismatched MCP-Protocol-Version rejected with 400")

        # 5. Normal JSON response with a valid session.
        status, headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            {"Accept": "application/json", "Mcp-Session-Id": session},
        )
        assert status == 200, (status, body)
        tools = json.loads(body)["result"]["tools"]
        assert len(tools) == 10, [tool["name"] for tool in tools]
        assert headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        print(f"[OK] tools/list with session: {len(tools)} tools")

        # 6. Accept: text/event-stream returns one SSE message.
        status, headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
            {
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session,
            },
        )
        assert status == 200, (status, body)
        content_type = headers.get("Content-Type") or headers.get("content-type")
        assert "text/event-stream" in content_type, headers
        text = body.decode("utf-8")
        assert "event: message" in text and '"tools"' in text, text[:300]
        print("[OK] POST with Accept: text/event-stream returns SSE")

        # 7. GET /mcp opens a per-session SSE stream.
        request = urllib.request.Request(
            BASE + "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session,
                "Authorization": f"Bearer {TOKEN}",
            },
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            assert "text/event-stream" in response.headers.get("Content-Type", "")
            line = response.readline().decode("utf-8", "replace")
            assert ": connected" in line, line
        print("[OK] GET /mcp opens a session SSE stream")

        # 8. CORS: local origins get ACAO, arbitrary origins do not.
        status, headers, _body = http(
            "OPTIONS",
            "/mcp",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
            token=False,
        )
        assert status in (200, 204), status
        assert headers.get("access-control-allow-origin") == "http://localhost:3000", headers
        status, headers, _body = http(
            "OPTIONS",
            "/mcp",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
            token=False,
        )
        assert not headers.get("access-control-allow-origin"), headers
        print("[OK] CORS allows loopback origins and blocks arbitrary origins")

        # 9. Health reports auth/timeout/session state.
        status, _headers, body = http("GET", "/health", token=False)
        assert status == 200, (status, body)
        health = json.loads(body)
        assert health["auth_required"] is True
        assert health["tool_timeout_secs"] == 10
        assert health["sessions"] >= 2
        print("[OK] /health exposes auth/timeout/session state")

        # 10. DELETE terminates the session.
        status, _headers, _body = http(
            "DELETE", "/mcp", headers={"Mcp-Session-Id": session}
        )
        assert status == 204, status
        status, _headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 6, "method": "tools/list"},
            {"Accept": "application/json", "Mcp-Session-Id": session},
        )
        assert status == 404, (status, body)
        print("[OK] DELETE /mcp terminates the session")

        # 11. Legacy HTTP+SSE endpoint event and message tunnel.
        request = urllib.request.Request(
            BASE + "/sse",
            headers={"Accept": "text/event-stream", "Authorization": f"Bearer {TOKEN}"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            assert "text/event-stream" in response.headers.get("Content-Type", "")
            lines = [response.readline().decode("utf-8", "replace") for _ in range(2)]
            chunk = "".join(lines)
            assert "event: endpoint" in chunk, chunk
            endpoint = None
            for line in chunk.splitlines():
                if line.startswith("data: /messages?sessionId="):
                    endpoint = line[len("data: "):]
                    break
            assert endpoint, chunk
            status, _headers, _body = http(
                "POST",
                endpoint,
                {"jsonrpc": "2.0", "id": 7, "method": "ping"},
                {"Accept": "application/json"},
            )
            assert status == 202, status
        print("[OK] legacy /sse endpoint + /messages tunnel")

        # 12. Notifications return 202 and do not create JSON-RPC responses.
        status, _headers, body = http(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"Accept": "application/json", "Mcp-Session-Id": latest_session},
        )
        assert status == 202 and not body, (status, body)
        print("[OK] notifications return 202 with empty body")

        # 13. Batch requests are rejected explicitly.
        status, _headers, body = http(
            "POST",
            "/mcp",
            [{"jsonrpc": "2.0", "id": 8, "method": "ping"}],
            {"Accept": "application/json", "Mcp-Session-Id": latest_session},
        )
        assert status == 400, (status, body)
        print("[OK] batch requests rejected with 400")
    finally:
        blender_mcp_core.stop_server()
        time.sleep(0.1)

    print("=" * 60)
    print("ALL TRANSPORT TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
