# Blender MCP (Rust)

A high-performance, embedded MCP (Model Context Protocol) server for Blender 5.x, written in **Rust** with **PyO3** bindings and an RNA-driven Python runtime.

Instead of running an external Python virtual environment with fragile multi-process socket bridges, **Blender MCP (Rust)** consolidates everything into a **single native Blender extension**. It provides an embedded Tokio async runtime with Streamable HTTP & SSE MCP services, alongside 9 consolidated, adaptive tools.

The tool layer is **adaptive**: instead of hardcoding Blender's parameters and enum values in Rust, tools read them from Blender's RNA at runtime. A new modifier, node type, operator parameter or render engine therefore works without updating this project.

---

## ⚡ Features

- **Single Addon Architecture**: Native Rust cdylib (`blender_mcp_core.so`) loaded directly by Blender's embedded Python via PyO3 (`abi3-py310`). Zero external `uv` / `pip` setup required.
- **Thread-Safe Command Dispatch**: Tokio handles high-concurrency async HTTP/SSE requests in a background OS thread; tasks are dispatched safely to Blender's main thread via lock-free channels with GIL synchronization.
- **Streamable HTTP & SSE Protocol**: Conforms to standard Model Context Protocol (JSON-RPC 2.0). Connect directly via `http://localhost:8765/mcp`.
- **Adaptive RNA-driven Tools**: `blender_describe` and `blender_run_operator` expose Blender's live RNA (operator parameters, enum identifiers, ranges, defaults, node-tree validity). New Blender features are available immediately; stale hardcoded enums are gone.
- **Transport-only Rust**: Rust owns the Tokio/HTTP/SSE server, the main-thread bridge, panic isolation and MCP envelope conversion. All 9 tool handlers and their schemas live in the persistent Python runtime; adding a tool needs zero Rust changes.
- **Shared Python Runtime**: `addon/blender_mcp/blender_mcp_runtime` is imported once and cached in `sys.modules`. Catalogs, RNA metadata and schema builders persist across requests instead of Python source strings being recompiled per call.
- **9 Consolidated Tools**:
  1. `blender_describe`: Adaptive introspection — operator/struct/property schemas, modifier and node catalogs, valid node tree types, render engines, primitive kinds, ID types.
  2. `blender_inspect`: Unified scene hierarchy, deep object info, file status, and dynamic datablock counts.
  3. `blender_run_operator`: Run any `bpy.ops` operator with RNA validation. Supports `primitive_type` semantic creation, plus post-processing (`name`, `collection`, `properties`, `location`, `rotation` in degrees, `scale`). This absorbs the former `blender_create_primitive` tool.
  4. `blender_set`: Generic RNA property writer with a path resolver (`object:RustCube.location`, `modifier:RustCube/Subsurf.levels`, `material:M.node_tree.nodes[Principled BSDF].inputs[Base Color].default_value`, `scene.render`). Supports `mode=relative|append`, `create`, `look_at`, `origin_to` and degree-based rotations. This absorbs the former `transform_object`, `manage_material` and `setup_scene` property paths.
  5. `blender_manage_modifier`: Live modifier catalog, RNA introspection, add/configure/apply/remove with generic pointer resolution.
  6. `blender_manage_nodes`: Shader, Geometry, Compositor, World, LineStyle and NodeGroup DAGs; node validity is probed per tree instead of guessed from name prefixes. `inspect` is read-only unless `ensure=true`.
  7. `blender_manage_hierarchy`: Scene hierarchy and collection management. Parent and unparent objects with transform preservation (`keep_transform`), bone parenting, create/nest/reparent collections, move or link objects between collections, configure visibility, renderability, color tags and view-layer exclusion, and inspect outliner trees.
  8. `blender_capture`: Viewport / camera rendering returning Base64 PNG image content for vision LLMs.
  9. `blender_execute_script`: Python execution with automatic Undo, timing and stdout/stderr capture.

  Removed handlers: `blender_create_primitive`, `blender_transform_object`,
  `blender_manage_material`, `blender_setup_scene` and `blender_undo`.
  `ed.undo` remains available as
  `blender_run_operator({"operator": "ed.undo", "undo": false})`.

### Architecture

```text
Rust (blender_mcp_core.so)
  ├── axum / Tokio        JSON-RPC, HTTP + SSE transport
  ├── bridge              async request -> Blender main thread (try_send + oneshot)
  ├── dispatcher          main-thread poll_tick, catch_unwind, responder
  └── tools/runtime.rs    name-based forwarding + tool catalog cache

Python (blender_mcp_runtime, imported once)
  ├── rna.py              RNA introspection, coercion, pointers, sockets
  ├── catalogs.py         live operators/modifiers/nodes/engines/ID types
  ├── registry.py         tool registration + schema materialization
  ├── schemas.py          migrated tool schemas with live enum patching
  └── tools/*.py          9 tool handlers
```

`blender_describe` reads the same RNA kernel, so agents can discover parameters
at runtime instead of relying on a stale schema. `tools/list` is populated from
the Python catalog at `start_server`, and the live schemas override the static
fallback.

---

## 🛠️ Build & Installation

### Prerequisites
- Blender 5.1+ / 5.2+ LTS
- Rust 1.80+ (with Cargo)

### Build
```bash
# Build release cdylib and copy into addon/blender_mcp/
make build

# Run all integration suites (tools + transport) in headless Blender
make test

# Run only the adaptive-tool or transport suite
make test-adaptive
make test-transport

# Package Blender extension zip into dist/
make extension
```

### Development Symlink
To develop and test live inside Blender without reinstalling:
```bash
ln -s "$(pwd)/addon/blender_mcp" "$HOME/Library/Application Support/Blender/5.2/extensions/user_default/blender_mcp_rust"
```
Then enable **Blender MCP (Rust)** in Blender Preferences -> Add-ons / Extensions.

---

## 🔌 Connecting with MCP Clients

Add the following to your MCP client configuration (Claude Desktop, Cursor, Antigravity, etc.):

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

If an **Auth Token** is configured in the add-on preferences:

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://127.0.0.1:8765/mcp",
      "headers": {
        "Authorization": "Bearer your-token"
      }
    }
  }
}
```

### Transport & sessions

Streamable HTTP endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/mcp` | JSON-RPC request; JSON or SSE response |
| `GET` | `/mcp` | Per-session server-sent event stream |
| `DELETE` | `/mcp` | Terminate the session |
| `GET` | `/sse` | Legacy HTTP+SSE `endpoint` event |
| `POST` | `/messages?sessionId=...` | Legacy HTTP+SSE request tunnel |
| `GET` | `/health` | Status, session count, auth/timeout info |

Behavior:

- `initialize` returns an `Mcp-Session-Id` header. Clients must send it on all
  subsequent `/mcp` requests. Unknown/expired sessions return `404`; a missing
  header returns `400`.
- Sessions expire after 24 hours of inactivity. `DELETE /mcp` closes one
  immediately.
- `POST /mcp` returns JSON by default. Send `Accept: text/event-stream` (without
  `application/json` or `*/*`) to receive a single SSE `message` event.
- Notifications (for example `notifications/initialized`) return `202 Accepted`
  with no body.
- Batch JSON-RPC arrays are rejected with `400`; send one message per request.
- Supported protocol versions: `2025-06-18`, `2025-03-26`, `2024-11-05`.
- Browser CORS is restricted to loopback origins (`localhost`, `127.0.0.1`,
  `::1`). Non-browser MCP clients are unaffected.
- The **Auth Token** preference enables `Authorization: Bearer ...` checking.
  When binding to a non-loopback host without a token, the server logs a warning.
- The **Tool Timeout (s)** preference controls how long a request waits for
  Blender's main thread (default 120s).

---

## 📄 License
GPL-3.0-or-later. Original Python reference implementation preserved in the `official-reference` branch.
