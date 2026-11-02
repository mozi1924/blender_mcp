# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""``blender_describe``: the adaptive introspection surface.

Instead of shipping stale enums in Rust, agents ask Blender what exists:

    target=operator      -> full RNA schema + enum items + ranges for one op
    target=operators     -> searchable operator catalog
    target=struct        -> properties of any RNA struct
    target=property      -> detailed info/schema for one property
    target=modifier_types-> live modifier enum                                
    target=modifier      -> RNA schema of a modifier type
    target=node_types    -> live node catalog, validated per tree type
    target=node          -> sockets + properties of a node type
    target=primitives    -> discoverable primitive creation operators
    target=render_engines-> live engine enum
    target=id_types      -> bpy.data collections and counts
    target=tool_schemas  -> schemas of the runtime tools
"""

from __future__ import annotations

import bpy

from .. import catalogs, rna, registry

_TARGETS = (
    "operator",
    "operators",
    "struct",
    "property",
    "modifier_types",
    "modifier",
    "node_types",
    "node",
    "primitives",
    "render_engines",
    "id_types",
    "tool_schemas",
    "refresh",
)


def _resolve_struct(name):
    raw = str(name or "").strip()
    if raw.startswith("bpy.types."):
        raw = raw[len("bpy.types."):]
    elif raw.startswith("bpy."):
        raw = raw[len("bpy."):]
    if "." in raw:
        raw = raw.split(".", 1)[0]
    cls = getattr(bpy.types, raw, None)
    if cls is None or not hasattr(cls, "bl_rna"):
        raise KeyError(f"RNA struct 'bpy.types.{raw}' not found")
    return cls


def _struct_property(args):
    path = str(args.get("path") or args.get("struct") or "").strip()
    prop_name = args.get("property")
    if not path:
        raise ValueError("Argument 'path' is required (e.g. 'Object.location')")

    if "." in path.replace("bpy.types.", ""):
        raw = path
        if raw.startswith("bpy.types."):
            raw = raw[len("bpy.types."):]
        struct_name, property_name = raw.rsplit(".", 1)
        cls = _resolve_struct(struct_name)
        prop_name = property_name
    else:
        cls = _resolve_struct(path)

    srna = cls.bl_rna
    if prop_name:
        prop = srna.properties.get(str(prop_name))
        if prop is None:
            identifiers = [p.identifier for p in srna.properties if p.identifier != "rna_type"]
            raise KeyError(
                f"Property '{prop_name}' not found on {srna.identifier}. "
                f"Did you mean: {rna.suggest(prop_name, identifiers)}"
            )
        return {
            "status": "ok",
            "struct": srna.identifier,
            "property": rna.prop_info(prop),
            "schema": rna.prop_schema(prop),
        }

    return {
        "status": "ok",
        "struct": rna.describe_struct(srna),
    }


def _modifier_schema(modifier_type):
    enum_prop = bpy.types.Modifier.bl_rna.properties.get("type")
    valid = {item.identifier: item for item in enum_prop.enum_items if item.identifier}
    requested = str(modifier_type or "").strip()
    identifier = None
    if requested in valid:
        identifier = requested
    else:
        nk = rna.norm(requested)
        for item in valid.values():
            if rna.norm(item.identifier) == nk or rna.norm(item.name) == nk:
                identifier = item.identifier
                break
    if identifier is None:
        raise KeyError(
            f"Unknown modifier type '{requested}'. "
            f"Did you mean: {rna.suggest(requested, list(valid.keys()))}"
        )

    mesh = bpy.data.meshes.new("__mcp_modifier_probe__")
    obj = bpy.data.objects.new("__mcp_modifier_probe__", mesh)
    try:
        modifier = obj.modifiers.new("probe", identifier)
        base = {p.identifier for p in bpy.types.Modifier.bl_rna.properties}
        properties = [
            rna.prop_info(p)
            for p in modifier.bl_rna.properties
            if p.identifier not in base and not p.is_readonly
        ]
        schema = {
            "type": "object",
            "properties": {p.identifier: rna.prop_schema(p) for p in modifier.bl_rna.properties
                           if p.identifier not in base and not p.is_readonly},
        }
        item = valid[identifier]
        return {
            "status": "ok",
            "modifier_type": identifier,
            "name": item.name,
            "description": (item.description or "").strip(),
            "properties_count": len(properties),
            "properties": properties,
            "input_schema": schema,
        }
    finally:
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)


def _node_schema(node_type, tree_type=None):
    node_type = str(node_type or "").strip()
    if not node_type:
        raise ValueError("Argument 'node_type' is required")

    tree_type = catalogs.normalize_tree_type(tree_type)
    valid_trees = catalogs.node_tree_types(node_type)
    if not valid_trees:
        catalog = catalogs.node_catalog()
        identifiers = [item["identifier"] for item in catalog]
        raise KeyError(
            f"Unknown node type '{node_type}'. "
            f"Did you mean: {rna.suggest(node_type, identifiers)}"
        )

    if tree_type and tree_type not in valid_trees:
        raise KeyError(
            f"Node '{node_type}' cannot be used in {tree_type}. Valid tree types: {valid_trees}"
        )
    tree_type = tree_type or valid_trees[0]

    tree = bpy.data.node_groups.new("__mcp_node_probe__", type=tree_type)
    try:
        node = tree.nodes.new(node_type)
        inputs = [rna.socket_info(sock) for sock in node.inputs]
        outputs = [rna.socket_info(sock) for sock in node.outputs]

        base = {p.identifier for p in bpy.types.Node.bl_rna.properties}
        properties = [
            rna.prop_info(p)
            for p in node.bl_rna.properties
            if p.identifier not in base and not p.is_readonly
        ]

        socket_schema = {}
        for sock in node.inputs:
            prop = sock.bl_rna.properties.get("default_value")
            if prop is not None and sock.identifier not in socket_schema:
                socket_schema[sock.identifier] = rna.prop_schema(prop)
                if sock.name != sock.identifier:
                    socket_schema.setdefault(sock.name, rna.prop_schema(prop))

        node_rna = bpy.types.Node.bl_rna_get_subclass(node_type)
        return {
            "status": "ok",
            "node_type": node_type,
            "name": node_rna.name if node_rna is not None else node_type,
            "description": (node_rna.description or "").strip() if node_rna is not None else "",
            "tree_type": tree_type,
            "valid_tree_types": valid_trees,
            "inputs": inputs,
            "outputs": outputs,
            "properties": properties,
            "input_socket_schema": socket_schema,
        }
    finally:
        bpy.data.node_groups.remove(tree)


def describe(args):
    target = str(args.get("target") or "operator").strip().lower()

    if target == "refresh":
        catalogs.clear()
        return {"status": "ok", "message": "RNA and catalog caches cleared"}

    if target == "operator":
        path = args.get("path") or args.get("operator")
        if not path:
            raise ValueError("Argument 'path' is required for target 'operator'")
        return rna.describe_operator(path)

    if target == "operators":
        return rna.list_operators(
            query=args.get("query", ""),
            module=args.get("module"),
            prefix=args.get("prefix"),
            limit=int(args.get("limit", 50)),
        )

    if target in ("struct", "property"):
        return _struct_property(args)

    if target == "modifier_types":
        return catalogs.modifier_types(args.get("query", ""))

    if target == "modifier":
        return _modifier_schema(args.get("modifier_type") or args.get("path"))

    if target == "node_types":
        return catalogs.search_node_types(
            query=args.get("query", ""),
            tree_type=args.get("tree_type"),
            limit=int(args.get("limit", 50)),
            include_tree_types=not bool(args.get("tree_type")),
        )

    if target == "node":
        return _node_schema(
            args.get("node_type") or args.get("path"),
            tree_type=args.get("tree_type"),
        )

    if target == "primitives":
        result = catalogs.primitive_kinds()
        query = args.get("query")
        if query:
            nq = rna.norm(query)
            result["primitives"] = [
                item for item in result["primitives"]
                if nq in rna.norm(item["kind"])
                or nq in rna.norm(item["name"])
                or nq in rna.norm(item["description"])
            ]
            result["count"] = len(result["primitives"])
        return result

    if target == "render_engines":
        return catalogs.render_engines()

    if target == "id_types":
        return catalogs.id_types()

    if target == "tool_schemas":
        return {"status": "ok", "tools": registry.list_tools()}

    raise KeyError(f"Unknown target '{target}'. Valid targets: {list(_TARGETS)}")


registry.register(
    name="blender_describe",
    handler=describe,
    description=(
        "Adaptive introspection of Blender's live RNA. Use this before hardcoding a "
        "parameter: it returns real operator/modifier/node parameters, enum identifiers, "
        "defaults, ranges and valid tree types for THIS Blender session. Targets: "
        "operator, operators, struct, property, modifier_types, modifier, node_types, "
        "node, primitives, render_engines, id_types, tool_schemas, refresh."
    ),
    input_schema={
        "type": "object",
        "required": ["target"],
        "properties": {
            "target": {
                "type": "string",
                "enum": list(_TARGETS),
                "description": "What to introspect.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Operator path ('mesh.primitive_cube_add' / 'MESH_OT_primitive_cube_add'), "
                    "struct name ('Object'), or struct property ('RenderSettings.engine')."
                ),
            },
            "property": {
                "type": "string",
                "description": "Optional property name when target is 'struct'.",
            },
            "modifier_type": {
                "type": "string",
                "description": "Modifier identifier or display name for target 'modifier'.",
            },
            "node_type": {
                "type": "string",
                "description": "Node bl_idname for target 'node'.",
            },
            "tree_type": {
                "type": "string",
                "enum": ["ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree", "TextureNodeTree"],
                "description": "Optional node tree type filter / restriction.",
            },
            "query": {
                "type": "string",
                "description": "Search term (English or localized names) for catalog targets.",
            },
            "module": {
                "type": "string",
                "description": "Limit operator search to one bpy.ops module (e.g. 'mesh').",
            },
            "prefix": {
                "type": "string",
                "description": "Limit operator search to names starting with this prefix.",
            },
            "limit": {
                "type": "integer",
                "default": 50,
                "minimum": 1,
                "maximum": 500,
                "description": "Maximum number of catalog entries to return.",
            },
        },
    },
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
