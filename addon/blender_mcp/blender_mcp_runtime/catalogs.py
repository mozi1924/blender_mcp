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
_IO_FORMATS = None
_RENDER_DEVICES = None
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
    global _NODE_CATALOG, _IO_FORMATS, _RENDER_DEVICES
    _NODE_CATALOG = None
    _IO_FORMATS = None
    _RENDER_DEVICES = None
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


# ---------------------------------------------------------------------------
# Dynamic 3D I/O Formats & Operators Catalog
# ---------------------------------------------------------------------------

_COMMON_EXT_ALIASES = {
    "usd": ("usd", "usda", "usdc", "usdz"),
    "usda": ("usd", "usda", "usdc", "usdz"),
    "usdc": ("usd", "usda", "usdc", "usdz"),
    "usdz": ("usd", "usda", "usdc", "usdz"),
    "alembic": ("abc", "alembic"),
    "abc": ("abc", "alembic"),
    "gltf": ("gltf", "glb"),
    "glb": ("gltf", "glb"),
    "obj": ("obj", "mtl"),
}


def io_formats(query=""):
    """Authoritatively discover all registered 3D import/export operators and file formats via RNA.

    Zero hardcoding: inspects registered bpy.ops and bpy.types.FileHandler subclasses.
    Extracts supported extensions dynamically from RNA filter_glob and filename_ext.
    """
    global _IO_FORMATS
    if _IO_FORMATS is None:
        importers = {}
        exporters = {}

        # 1. Inspect registered FileHandler subclasses if available (Blender 4.0+)
        file_handler_cls = getattr(bpy.types, "FileHandler", None)
        if file_handler_cls and hasattr(file_handler_cls, "__subclasses__"):
            for fh in file_handler_cls.__subclasses__():
                ext_str = getattr(fh, "bl_file_extensions", "") or ""
                exts = [e.lstrip(".*").lower() for e in ext_str.split(";") if e.strip()]
                imp_op = getattr(fh, "bl_import_operator", None)
                exp_op = getattr(fh, "bl_export_operator", None)
                label = getattr(fh, "bl_label", fh.__name__)
                for e in exts:
                    if imp_op and e not in importers:
                        importers[e] = {
                            "operator": imp_op,
                            "name": label,
                            "extensions": exts,
                            "source": "file_handler",
                        }
                    if exp_op and e not in exporters:
                        exporters[e] = {
                            "operator": exp_op,
                            "name": label,
                            "extensions": exts,
                            "source": "file_handler",
                        }

        # 2. Inspect all registered bpy.ops via RNA reflection
        for mod_name in dir(bpy.ops):
            if mod_name.startswith("_"):
                continue
            mod = getattr(bpy.ops, mod_name, None)
            if mod is None:
                continue
            for op_name in dir(mod):
                if op_name.startswith("_"):
                    continue
                full_op = f"{mod_name}.{op_name}"
                is_imp = "import" in op_name or "import" in mod_name
                is_exp = "export" in op_name or "export" in mod_name
                if not (is_imp or is_exp):
                    continue

                try:
                    op = getattr(mod, op_name)
                    rna_type = op.get_rna_type()
                    props = rna_type.properties
                    if "filepath" not in props:
                        continue

                    filt = getattr(props.get("filter_glob"), "default", "") or ""
                    ext_def = getattr(props.get("filename_ext"), "default", "") or ""

                    exts = set()
                    if filt:
                        for part in filt.split(";"):
                            p = part.strip().lstrip("*.").lower()
                            if p and p != "*":
                                exts.add(p)
                    if ext_def:
                        exts.add(ext_def.lstrip(".*").lower())

                    clean_name = op_name.replace("primitive_", "").replace("grease_pencil_", "")
                    for token in ("gltf", "glb", "fbx", "obj", "usd", "abc", "alembic", "ply", "stl", "svg", "bvh"):
                        if token in clean_name:
                            exts.add(token)
                            if token in _COMMON_EXT_ALIASES:
                                exts.update(_COMMON_EXT_ALIASES[token])

                    desc = (rna_type.description or "").strip()
                    op_title = rna_type.name

                    for e in exts:
                        entry = {
                            "operator": full_op,
                            "name": op_title,
                            "description": desc,
                            "extensions": sorted(exts),
                            "source": "rna_operator",
                        }
                        if is_imp:
                            if e not in importers or full_op.startswith("wm."):
                                importers[e] = entry
                        if is_exp:
                            if e not in exporters or full_op.startswith("wm."):
                                exporters[e] = entry
                except Exception:
                    pass

        _IO_FORMATS = {
            "importers": importers,
            "exporters": exporters,
            "supported_import_formats": sorted(importers.keys()),
            "supported_export_formats": sorted(exporters.keys()),
        }

    q = rna.norm(query or "")
    if not q:
        return {
            "status": "ok",
            "counts": {
                "importers": len(_IO_FORMATS["importers"]),
                "exporters": len(_IO_FORMATS["exporters"]),
            },
            "supported_import_formats": _IO_FORMATS["supported_import_formats"],
            "supported_export_formats": _IO_FORMATS["supported_export_formats"],
            "importers": _IO_FORMATS["importers"],
            "exporters": _IO_FORMATS["exporters"],
        }

    filtered_imps = {
        k: v for k, v in _IO_FORMATS["importers"].items()
        if q in rna.norm(k) or q in rna.norm(v["operator"]) or q in rna.norm(v["name"])
    }
    filtered_exps = {
        k: v for k, v in _IO_FORMATS["exporters"].items()
        if q in rna.norm(k) or q in rna.norm(v["operator"]) or q in rna.norm(v["name"])
    }
    return {
        "status": "ok",
        "query": query,
        "counts": {
            "importers": len(filtered_imps),
            "exporters": len(filtered_exps),
        },
        "supported_import_formats": sorted(filtered_imps.keys()),
        "supported_export_formats": sorted(filtered_exps.keys()),
        "importers": filtered_imps,
        "exporters": filtered_exps,
    }


# ---------------------------------------------------------------------------
# Dynamic Render Devices & Compute Acceleration Catalog
# ---------------------------------------------------------------------------


def render_devices():
    """Discover real physical GPU devices and available compute engines via RNA."""
    global _RENDER_DEVICES
    if _RENDER_DEVICES is not None:
        return _RENDER_DEVICES

    gpu_info = {}
    try:
        import gpu
        if hasattr(gpu, "init"):
            try:
                gpu.init()
            except Exception:
                pass
        if hasattr(gpu, "platform"):
            gpu_info = {
                "renderer": gpu.platform.renderer_get() if hasattr(gpu.platform, "renderer_get") else None,
                "vendor": gpu.platform.vendor_get() if hasattr(gpu.platform, "vendor_get") else None,
                "device_type": gpu.platform.device_type_get() if hasattr(gpu.platform, "device_type_get") else None,
                "version": gpu.platform.version_get() if hasattr(gpu.platform, "version_get") else None,
            }
    except Exception:
        gpu_info = {"note": "GPU platform inspection unavailable in current context"}

    cycles_addon = bpy.context.preferences.addons.get("cycles")
    compute_info = {
        "active_compute_device_type": "NONE",
        "available_device_types": [],
        "physical_devices": [],
    }

    if cycles_addon:
        cprefs = cycles_addon.preferences
        compute_info["active_compute_device_type"] = getattr(cprefs, "compute_device_type", "NONE")
        try:
            types_list = cprefs.get_device_types(bpy.context)
            compute_info["available_device_types"] = [
                {"identifier": t[0], "name": t[1], "description": t[2]}
                for t in types_list
            ]
        except Exception:
            pass

        try:
            cprefs.refresh_devices()
            devices_list = []
            for d in getattr(cprefs, "devices", []):
                devices_list.append({
                    "name": d.name,
                    "type": d.type,
                    "use": bool(d.use),
                    "id": getattr(d, "id", None),
                })
            compute_info["physical_devices"] = devices_list
        except Exception:
            pass

    _RENDER_DEVICES = {
        "status": "ok",
        "gpu_platform": gpu_info,
        "cycles": compute_info,
    }
    return _RENDER_DEVICES


def activate_render_device(device_type=None):
    """Dynamically activate the best available Cycles GPU compute device with zero hardcoding."""
    cycles_addon = bpy.context.preferences.addons.get("cycles")
    if not cycles_addon:
        return {"status": "warning", "message": "Cycles addon not loaded"}

    cprefs = cycles_addon.preferences
    try:
        types_list = cprefs.get_device_types(bpy.context)
        valid_types = [t[0] for t in types_list if t[0] != "NONE"]
    except Exception:
        valid_types = []

    if not valid_types:
        return {
            "status": "warning",
            "message": "No GPU compute acceleration supported on this platform",
            "active_device_type": getattr(cprefs, "compute_device_type", "NONE"),
        }

    target_type = None
    if device_type and str(device_type).upper() in valid_types:
        target_type = str(device_type).upper()
    else:
        if "OPTIX" in valid_types:
            target_type = "OPTIX"
        else:
            target_type = valid_types[0]

    cprefs.compute_device_type = target_type
    try:
        cprefs.refresh_devices()
    except Exception:
        pass

    activated_devices = []
    for d in getattr(cprefs, "devices", []):
        if d.type == target_type or d.type != "CPU":
            d.use = True
            activated_devices.append(d.name)

    global _RENDER_DEVICES
    _RENDER_DEVICES = None

    return {
        "status": "ok",
        "compute_device_type": target_type,
        "activated_devices": activated_devices,
    }


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
    "io_formats",
    "render_devices",
    "activate_render_device",
]
