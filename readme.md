# Blender MCP (Rust)

A high-performance, embedded MCP (Model Context Protocol) server for Blender 5.x, written in **Rust** with **PyO3** bindings.

Instead of running an external Python virtual environment with fragile multi-process socket bridges, **Blender MCP (Rust)** consolidates everything into a **single native Blender extension (736 KB)**. It provides an embedded Tokio async runtime with Streamable HTTP & SSE MCP services, alongside 9 agent-centric semantic 3D modeling and inspection tools.

---

## ⚡ Features

- **Single Addon Architecture**: Native Rust cdylib (`blender_mcp_core.so`) loaded directly by Blender's embedded Python via PyO3 (`abi3-py310`). Zero external `uv` / `pip` setup required.
- **Thread-Safe Command Dispatch**: Tokio handles high-concurrency async HTTP/SSE requests in a background OS thread; tasks are dispatched safely to Blender's main thread via lock-free channels with GIL synchronization.
- **Streamable HTTP & SSE Protocol**: Conforms to standard Model Context Protocol (JSON-RPC 2.0). Connect directly via `http://localhost:8765/mcp`.
- **9 High-Leverage Semantic Tools**:
  1. `blender_inspect`: Unified scene hierarchy, deep object info, file status, and datablock inspection.
  2. `blender_capture`: Multi-modal visual perception (viewport / camera rendering directly returning Base64 PNG image content for vision LLMs).
  3. `blender_create_primitive`: Parameter-driven primitive creation (cube, sphere, cylinder, cone, torus, plane, curve, text, empty, camera, light) with auto-naming, transform, and collection linking.
  4. `blender_transform_object`: Precise translation, rotation (degrees), and scaling in absolute or relative mode, with auto-apply transforms.
  5. `blender_manage_modifier`: Non-destructive modifier stack management (Subsurf, Bevel, Boolean, Mirror, Array, Solidify, Remesh, Decimate).
  6. `blender_manage_material`: Instant Principled BSDF creation and attribute tweaking (color, metallic, roughness, emission, transmission).
  7. `blender_setup_scene`: Auto camera look-at tracking, light placement, and modern render engines (**BLENDER_EEVEE_NEXT** / Cycles).
  8. `blender_execute_script`: Procedural Python script execution with **automatic Undo step safety** (`bpy.ops.ed.undo_push`), timing, and stdout/stderr capture.
  9. `blender_undo`: One-click undo for instant recovery.

---

## 🛠️ Build & Installation

### Prerequisites
- Blender 5.1+ / 5.2+ LTS
- Rust 1.80+ (with Cargo)

### Build
```bash
# Build release cdylib and copy into addon/blender_mcp/
make build

# Run automated integration test suite in headless Blender
make test

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
