# Blender MCP (Rust) Makefile

BLENDER ?= blender
CARGO ?= cargo

.PHONY: all build build-debug test extension clean run-blender

all: build

build:
	@echo "==> Building blender_mcp_core (release)..."
	$(CARGO) build --release -p blender_mcp_core
	@mkdir -p addon/blender_mcp
	@cp target/release/libblender_mcp_core.dylib addon/blender_mcp/blender_mcp_core.so 2>/dev/null || \
	 cp target/release/libblender_mcp_core.so addon/blender_mcp/blender_mcp_core.so
	@echo "==> Copied blender_mcp_core.so to addon/blender_mcp/"

build-debug:
	@echo "==> Building blender_mcp_core (debug)..."
	$(CARGO) build -p blender_mcp_core
	@mkdir -p addon/blender_mcp
	@cp target/debug/libblender_mcp_core.dylib addon/blender_mcp/blender_mcp_core.so 2>/dev/null || \
	 cp target/debug/libblender_mcp_core.so addon/blender_mcp/blender_mcp_core.so

test: build
	@echo "==> Running integration tests in headless Blender..."
	$(BLENDER) -b --python tests/test_rust_mcp_integration.py

extension: build
	@echo "==> Packaging Blender extension..."
	@mkdir -p dist
	$(BLENDER) --command extension build --source addon/blender_mcp --output-dir dist/
	@echo "==> Extension package generated in dist/"

run-blender: build
	@echo "==> Launching Blender with MCP extension directory..."
	$(BLENDER) --python-expr "import sys, bpy; sys.path.insert(0, 'addon/blender_mcp'); import blender_mcp_core; bpy.ops.preferences.addon_enable(module='blender_mcp')"

clean:
	$(CARGO) clean
	@rm -f addon/blender_mcp/blender_mcp_core.so
	@rm -rf dist/
