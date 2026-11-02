# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live Blender catalogs derived from RNA.

Every expensive discovery (node catalog, per-tree node validity, modifier
enums, render engines) is cached for the lifetime of the embedded Python
module.  Unlike the old ``PyModule::from_code`` approach, the cache now really
persists across MCP calls.
"""

from __future__ import annotations

import bpy

from . import rna

_NODE_CATALOG = None
_NODE_VALIDITY = {}
_TREE_TYPES = ("ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree", "TextureNodeTree")

# User-facing tree names (used by the tools) -> Blender tree identifiers.
_TREE_ALIASES = {
    "MATERIAL": "ShaderNodeTree",
    "SHADER": "ShaderNodeTree",
    "WORLD": "ShaderNodeTree",
    "LINESTYLE": "ShaderNodeTree",
    "LIGHT": "ShaderNodeTree",
    "GEOMETRY": "GeometryNodeTree",
    "COMPOSITING": "CompositorNodeTree",
    "TEXTURE": "TextureNodeTree",
}


def normalize_tree_type(tree_type):
    if not tree_type:
        return None
    text = str(tree_type)
    return _TREE_ALIASES.get(text.upper(), text)

_BASE_NODE_NAMES = {
    "Node",
    "NodeTree",
    "NodeSocket",
    "ShaderNode",
    "GeometryNode",
    "CompositorNode",
    "TextureNode",
    "FunctionNode",
    "NodeGroup",
    "NodeGroupInput",
    "NodeGroupOutput",
}


def clear():
    """Invalidate every cache (call after addon enable/disable or file load)."""
    global _NODE_CATALOG
    _NODE_CATALOG = None
    _NODE_VALIDITY.clear()
    rna.refresh()


# ---------------------------------------------------------------------------
# Node catalog
# ---------------------------------------------------------------------------


def node_catalog():
    """Metadata for every registered node type, independent of tree type."""
    global _NODE_CATALOG
    if _NODE_CATALOG is not None:
        return _NODE_CATALOG

    from bpy.app.translations import pgettext_iface, pgettext_tip

    catalog = []
    for name in dir(bpy.types):
        if name.endswith("Socket") or name in _BASE_NODE_NAMES:
            continue
        try:
            node_rna = bpy.types.Node.bl_rna_get_subclass(name)
        except Exception:
            node_rna = None
        if node_rna is None:
            continue

        name_en = node_rna.name
        desc_en = node_rna.description or ""
        try:
            name_i18n = pgettext_iface(name_en)
        except Exception:
            name_i18n = name_en
        try:
            desc_i18n = pgettext_tip(desc_en) if desc_en else desc_en
        except Exception:
            desc_i18n = desc_en

        catalog.append(
            {
                "identifier": name,
                "name": name_en,
                "name_i18n": name_i18n,
                "description": desc_en.strip(),
                "description_i18n": desc_i18n.strip(),
            }
        )

    _NODE_CATALOG = catalog
    return _NODE_CATALOG


def _node_validity(tree_type):
    """Authoritatively probe which node types can be instanced in a tree.

    Blender already knows the answer; prefix heuristics such as
    ``ShaderNode*`` -> shader tree are wrong in both directions (for example
    texture nodes are valid in geometry trees, while Principled BSDF is not).
    Probing costs only a few milliseconds and is cached.
    """
    tree_type = normalize_tree_type(tree_type) or "GeometryNodeTree"
    cached = _NODE_VALIDITY.get(tree_type)
    if cached is not None:
        return cached

    valid = {}
    tree = bpy.data.node_groups.new(f"__mcp_probe_{tree_type}__", type=tree_type)
    try:
        for item in node_catalog():
            identifier = item["identifier"]
            try:
                node = tree.nodes.new(identifier)
                tree.nodes.remove(node)
                valid[identifier] = True
            except Exception:
                valid[identifier] = False
    finally:
        bpy.data.node_groups.remove(tree)

    _NODE_VALIDITY[tree_type] = valid
    return valid


def node_tree_types(node_type):
    """All tree types in which ``node_type`` can actually be created."""
    return [tree_type for tree_type in _TREE_TYPES if _node_validity(tree_type).get(node_type)]


def search_node_types(query="", tree_type=None, limit=50, include_tree_types=False):
    tree_type = normalize_tree_type(tree_type)
    catalog = node_catalog()
    validity = _node_validity(tree_type) if tree_type else None
    q = rna.norm(query or "")

    results = []
    for item in catalog:
        if validity is not None and not validity.get(item["identifier"]):
            continue

        score = 0
        if not q:
            score = 1
        else:
            id_n = rna.norm(item["identifier"])
            name_n = rna.norm(item["name"])
            i18n_n = rna.norm(item["name_i18n"])
            desc_n = rna.norm(item["description"])
            desc_i18n_n = rna.norm(item["description_i18n"])
            if q == id_n or q == name_n or q == i18n_n:
                score = 100
            elif q in name_n or q in i18n_n:
                score = 50
            elif q in id_n:
                score = 30
            elif q in desc_n or q in desc_i18n_n:
                score = 10
        if score:
            entry = dict(item)
            if include_tree_types:
                entry["tree_types"] = node_tree_types(item["identifier"])
            results.append((score, entry))

    results.sort(key=lambda pair: (-pair[0], pair[1]["identifier"]))
    limited = [entry for _score, entry in results[: max(1, int(limit))]]
    return {
        "status": "ok",
        "query": query,
        "tree_type": tree_type,
        "count": len(results),
        "results": limited,
        "truncated": len(results) > int(limit),
    }


# ---------------------------------------------------------------------------
# Modifiers / render engines / primitives / ID types
# ---------------------------------------------------------------------------


def modifier_types(query=""):
    prop = bpy.types.Modifier.bl_rna.properties.get("type")
    if prop is None:
        return {"status": "error", "message": "Modifier.type RNA not found"}
    q = rna.norm(query or "")
    items = []
    for item in prop.enum_items:
        if not item.identifier:
            continue
        if q and not (
            q in rna.norm(item.identifier)
            or q in rna.norm(item.name)
            or q in rna.norm(item.description or "")
        ):
            continue
        items.append(
            {
                "identifier": item.identifier,
                "name": item.name,
                "description": (item.description or "").strip(),
            }
        )
    return {
        "status": "ok",
        "query": query,
        "count": len(items),
        "modifiers": items,
    }


def render_engines():
    prop = bpy.types.RenderSettings.bl_rna.properties.get("engine")
    if prop is None:
        return {"status": "error", "message": "RenderSettings.engine RNA not found"}
    items = [
        {
            "identifier": item.identifier,
            "name": item.name,
            "description": (item.description or "").strip(),
        }
        for item in prop.enum_items
    ]
    return {
        "status": "ok",
        "count": len(items),
        "engines": items,
        "note": (
            "Only engines registered in this Blender session are listed. "
            "Enable the Cycles add-on to make 'CYCLES' available."
            if not any(item["identifier"] == "CYCLES" for item in items)
            else None
        ),
    }


def primitive_kinds():
    """Enumerate primitive creation operators instead of hardcoding a list."""
    items = []
    for module in ("mesh", "curve", "object"):
        parent = getattr(bpy.ops, module, None)
        if parent is None:
            continue
        for op_name in dir(parent):
            if op_name.startswith("_"):
                continue
            if module in ("mesh", "curve"):
                if not (op_name.startswith("primitive_") and op_name.endswith("_add")):
                    continue
                kind = op_name[len("primitive_") : -len("_add")]
            else:
                if op_name not in ("text_add", "empty_add", "camera_add", "light_add"):
                    continue
                kind = op_name[: -len("_add")]
            try:
                rt = getattr(parent, op_name).get_rna_type()
                name = rt.name
                description = (rt.description or "").strip()
            except Exception:
                name, description = kind, ""
            items.append(
                {
                    "kind": kind,
                    "operator": f"{module}.{op_name}",
                    "name": name,
                    "description": description,
                }
            )
    return {
        "status": "ok",
        "count": len(items),
        "primitives": items,
    }


def id_types():
    counts = {}
    items = []
    for fixed_type, collection_name in sorted(rna.id_collections().items()):
        collection = getattr(bpy.data, collection_name, None)
        if collection is None:
            continue
        count = len(collection)
        counts[collection_name] = count
        items.append(
            {
                "rna_type": fixed_type,
                "collection": collection_name,
                "count": count,
            }
        )
    return {"status": "ok", "count": len(items), "id_types": items}


__all__ = [
    "clear",
    "normalize_tree_type",
    "node_catalog",
    "node_tree_types",
    "search_node_types",
    "modifier_types",
    "render_engines",
    "primitive_kinds",
    "id_types",
]
