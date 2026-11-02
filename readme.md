# Blender MCP (Rust)

A high-performance, embedded MCP (Model Context Protocol) server for Blender 5.x, written in **Rust** with **PyO3** bindings and an RNA-driven Python runtime.

Instead of running an external Python virtual environment with fragile multi-process socket bridges, **Blender MCP (Rust)** consolidates everything into a **single native Blender extension**. It provides an embedded Tokio async runtime with Streamable HTTP & SSE MCP services, alongside 12 agent-centric tools.

The tool layer is **adaptive**: instead of hardcoding Blender's parameters and enum values in Rust, tools read them from Blender's RNA at runtime. A new modifier, node type, operator parameter or render engine therefore works without updating this project.

---

## ⚡ Features

- **Single Addon Architecture**: Native Rust cdylib (`blender_mcp_core.so`) loaded directly by Blender's embedded Python via PyO3 (`abi3-py310`). Zero external `uv` / `pip` setup required.
- **Thread-Safe Command Dispatch**: Tokio handles high-concurrency async HTTP/SSE requests in a background OS thread; tasks are dispatched safely to Blender's main thread via lock-free channels with GIL synchronization.
- **Streamable HTTP & SSE Protocol**: Conforms to standard Model Context Protocol (JSON-RPC 2.0). Connect directly via `http://localhost:8765/mcp`.
- **Adaptive RNA-driven Tools**: `blender_describe` and `blender_run_operator` expose Blender's live RNA (operator parameters, enum identifiers, ranges, defaults, node-tree validity). New Blender features are available immediately; stale hardcoded enums are gone.
- **Shared Python Runtime**: all Blender knowledge lives in `addon/blender_mcp/blender_mcp_runtime` (one cached module) instead of Python source strings recompiled on every call. Catalogs and RNA metadata persist across requests.
- **12 Tools**:
  1. `blender_describe`: Adaptive introspection — operator/struct/property schemas, modifier and node catalogs, valid node tree types, render engines, primitive kinds, ID types.
  2. `blender_run_operator`: Run any `bpy.ops` operator with RNA validation, enum coercion, pointer-by-name resolution, poll diagnostics and explicit unknown-parameter errors.
  3. `blender_inspect`: Unified scene hierarchy, deep object info, file status, and dynamic datablock counts.
  4. `blender_capture`: Viewport / camera rendering returning Base64 PNG image content for vision LLMs.
  5. `blender_create_primitive`: Operator-driven primitive creation (including `grid`, `monkey`, NURBS and add-on primitives) with every parameter validated from the creation operator's RNA.
  6. `blender_transform_object`: Translation, rotation (degrees), scaling, origin manipulation and apply-transform, adapting to Euler/Quaternion/Axis-Angle modes.
  7. `blender_manage_modifier`: Live modifier catalog, RNA introspection, add/configure/apply/remove with generic pointer resolution.
  8. `blender_manage_material`: Principled BSDF / OpenPBR socket editing using socket RNA, multi-slot assignment and inspection.
  9. `blender_manage_nodes`: Shader, Geometry, Compositor, World, LineStyle and NodeGroup DAGs; node validity is probed per tree instead of guessed from name prefixes.
  10. `blender_setup_scene`: Camera look-at, lights, live render-engine enum, RNA-discovered sample properties and world background sockets.
  11. `blender_execute_script`: Python execution with automatic Undo, timing and stdout/stderr capture.
  12. `blender_undo`: One-click undo.

---

## 🛠️ Build & Installation

### Prerequisites
- Blender 5.1+ / 5.2+ LTS
- Rust 1.80+ (with Cargo)

### Build
```bash
# Build release cdylib and copy into addon/blender_mcp/
make build

# Run both integration suites in headless Blender
make test

# Run only the adaptive-tool suite
make test-adaptive

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

Or connect via Server-Sent Events (SSE) at `http://127.0.0.1:8765/sse`.

---

## 📄 License
GPL-3.0-or-later. Original Python reference implementation preserved in the `official-reference` branch.
