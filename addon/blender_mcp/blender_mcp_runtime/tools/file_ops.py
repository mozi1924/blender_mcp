# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""``blender_manage_file``: centralized external file and asset operations.

Covers:
  - Read-only introspection / preview of external .blend files (inspect linkable datablocks)
  - Appending and linking datablocks from external .blend libraries into current scene
  - Opening, saving, saving as, reverting, and resetting project files
  - Importing and exporting standard 3D formats (glTF, FBX, OBJ, USD, Alembic, PLY, STL, SVG)
  - Asset packaging, path relative/absolute conversion, and missing file remapping
"""

from __future__ import annotations

import os
from pathlib import Path
import bpy

from .. import catalogs, registry, rna

_ACTIONS = (
    "preview",
    "append",
    "link",
    "open",
    "save",
    "save_as",
    "revert",
    "new",
    "import_format",
    "export_format",
    "pack_resources",
)


def _normalize_path(path_str: str) -> str:
    raw = str(path_str or "").strip()
    if not raw:
        return ""
    expanded = os.path.expanduser(os.path.expandvars(raw))
    return bpy.path.abspath(expanded)


def _resolve_io_operator(format_str: str, is_import: bool) -> tuple[str, dict]:
    """Dynamically resolve operator identifier for a given 3D format from catalogs."""
    io = catalogs.io_formats()
    table = io.get("importers" if is_import else "exporters", {})
    key = str(format_str).lower().strip().lstrip(".")
    if key in table:
        entry = table[key]
        return entry["operator"], entry
    supported = sorted(table.keys())
    raise ValueError(
        f"No {'importer' if is_import else 'exporter'} registered for 3D format '{key}'. "
        f"Supported {('import' if is_import else 'export')} formats in this session: {supported}"
    )


def _detect_format(filepath: str, explicit_format: str | None = None, is_import: bool = True) -> str:
    """Detect file format dynamically from explicit format argument or filepath extension."""
    io = catalogs.io_formats()
    table = io.get("importers" if is_import else "exporters", {})
    if explicit_format:
        fmt = str(explicit_format).lower().strip().lstrip(".")
        if fmt in table:
            return fmt
    ext = Path(filepath).suffix.lower().lstrip(".")
    if ext in table:
        return ext
    supported = sorted(table.keys())
    raise ValueError(
        f"Unable to match a registered 3D format for file '{filepath}'. "
        f"Provided or detected format '{explicit_format or ext}' is not registered in this session. "
        f"Supported formats: {supported}. Check available formats via blender_describe(target='io_formats')."
    )


def _preview_blend(args: dict) -> dict:
    filepath = _normalize_path(args.get("filepath"))
    if not filepath:
        raise ValueError("Argument 'filepath' is required for action 'preview'")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: '{filepath}'")

    datablock_filter = str(args.get("datablock_type") or "all").lower().strip()

    # Special case: inspecting currently open mainfile directly from bpy.data
    is_current = bool(bpy.data.filepath and os.path.abspath(filepath) == os.path.abspath(bpy.data.filepath))

    datablocks = {}
    libraries = []
    version = None

    if is_current:
        version = list(bpy.app.version)
        libraries = [lib.filepath for lib in bpy.data.libraries]
        for attr in dir(bpy.data):
            col = getattr(bpy.data, attr, None)
            if isinstance(col, bpy.types.bpy_prop_collection) and hasattr(col, "keys"):
                names = list(col.keys())
                if names and (datablock_filter in ("all", "*") or datablock_filter == attr):
                    datablocks[attr] = names
    else:
        try:
            with bpy.data.libraries.load(filepath) as (data_from, _):
                raw_ver = getattr(data_from, "version", None)
                version = list(raw_ver) if raw_ver is not None else None
                raw_libs = getattr(data_from, "libraries", [])
                libraries = [lib[0] if isinstance(lib, (list, tuple)) else str(lib) for lib in raw_libs]

                # Inspect all linkable collections exposed on data_from
                for attr in dir(data_from):
                    if attr.startswith("_") or attr in ("libraries", "version"):
                        continue
                    try:
                        items = getattr(data_from, attr)
                        if isinstance(items, (list, tuple)):
                            names = list(items)
                            if names and (datablock_filter in ("all", "*") or datablock_filter == attr):
                                datablocks[attr] = names
                    except Exception:
                        pass
        except Exception as e:
            raise RuntimeError(f"Failed to preview blend file '{filepath}': {e}") from e

    return {
        "status": "ok",
        "action": "preview",
        "filepath": filepath,
        "is_current_file": is_current,
        "blend_version": version,
        "linked_libraries": libraries,
        "datablocks": datablocks,
        "counts": {k: len(v) for k, v in datablocks.items()},
    }


def _load_library(args: dict, link: bool) -> dict:
    filepath = _normalize_path(args.get("filepath"))
    if not filepath:
        raise ValueError(f"Argument 'filepath' is required for action '{'link' if link else 'append'}'")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Blend file not found: '{filepath}'")

    datablock_type = str(args.get("datablock_type") or "collections").lower().strip()
    req_names = args.get("names")
    if isinstance(req_names, str):
        req_names = [req_names]
    elif req_names is not None:
        req_names = list(req_names)

    target_collection_name = args.get("target_collection")
    target_col = None
    if target_collection_name:
        target_col = bpy.data.collections.get(target_collection_name)
        if not target_col and target_collection_name in ("Scene Collection", bpy.context.scene.collection.name):
            target_col = bpy.context.scene.collection
        if not target_col:
            raise KeyError(f"Target collection '{target_collection_name}' not found")
    else:
        target_col = bpy.context.scene.collection

    recursive = bool(args.get("recursive", True))
    set_fake = bool(args.get("set_fake", False))
    reuse_local_id = bool(args.get("reuse_local_id", False))
    create_liboverrides = bool(args.get("create_liboverrides", False)) if link else False
    undo = bool(args.get("undo", True))

    if undo:
        bpy.ops.ed.undo_push(message=f"MCP {'Link' if link else 'Append'} from {os.path.basename(filepath)}")

    loaded_summary = {}
    linked_to_scene = []

    load_kwargs = {
        "link": link,
        "relative": bool(args.get("relative", False)),
    }
    if not link:
        load_kwargs["recursive"] = recursive
        load_kwargs["set_fake"] = set_fake
        load_kwargs["reuse_local_id"] = reuse_local_id
    else:
        load_kwargs["create_liboverrides"] = create_liboverrides

    with bpy.data.libraries.load(filepath, **load_kwargs) as (data_from, data_to):
        types_to_load = []
        if datablock_type in ("all", "*"):
            types_to_load = [
                attr for attr in dir(data_from)
                if not attr.startswith("_") and attr not in ("libraries", "version")
            ]
        else:
            types_to_load = [datablock_type]

        for attr in types_to_load:
            if not hasattr(data_from, attr):
                continue
            available = getattr(data_from, attr)
            if not isinstance(available, (list, tuple)):
                continue

            to_load = []
            if req_names is None or req_names == ["*"] or not req_names:
                to_load = list(available)
            else:
                to_load = [n for n in req_names if n in available]

            if to_load:
                setattr(data_to, attr, to_load)
                loaded_summary[attr] = to_load

    # After exiting libraries.load context, data_to contains the materialized datablocks
    materialized = {}
    for attr in loaded_summary:
        items = getattr(data_to, attr, [])
        materialized[attr] = [getattr(it, "name", str(it)) for it in items if it]

    # Ensure appended/linked collections and objects are placed into the target scene collection
    if "collections" in materialized:
        for col in getattr(data_to, "collections", []):
            if col and col.name not in target_col.children:
                target_col.children.link(col)
                linked_to_scene.append(f"collection:{col.name}")

    if "objects" in materialized:
        for obj in getattr(data_to, "objects", []):
            if obj and not obj.users_collection:
                target_col.objects.link(obj)
                linked_to_scene.append(f"object:{obj.name}")

    bpy.context.view_layer.update()

    return {
        "status": "ok",
        "action": "link" if link else "append",
        "filepath": filepath,
        "loaded": materialized,
        "linked_to_scene_collection": target_col.name,
        "linked_items": linked_to_scene,
    }


def _open_file(args: dict) -> dict:
    filepath = _normalize_path(args.get("filepath"))
    if not filepath:
        raise ValueError("Argument 'filepath' is required for action 'open'")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Blend file not found: '{filepath}'")

    load_ui = bool(args.get("load_ui", False))
    use_scripts = bool(args.get("use_scripts", True))

    bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=load_ui, use_scripts=use_scripts)

    return {
        "status": "ok",
        "action": "open",
        "filepath": bpy.data.filepath,
        "active_scene": bpy.context.scene.name if bpy.context.scene else None,
        "objects_count": len(bpy.data.objects),
    }


def _save_file(args: dict, save_as: bool = False) -> dict:
    filepath = _normalize_path(args.get("filepath"))
    if not filepath:
        if save_as:
            raise ValueError("Argument 'filepath' is required for action 'save_as'")
        filepath = bpy.data.filepath
        if not filepath:
            raise ValueError("The current file has never been saved. Please provide a 'filepath'.")

    # Ensure parent directory exists
    parent_dir = os.path.dirname(filepath)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    compress = bool(args.get("compress", True))
    relative_remap = bool(args.get("relative_remap", True))
    copy = bool(args.get("copy", False)) if save_as else False

    if save_as:
        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=compress, copy=copy, relative_remap=relative_remap)
    else:
        bpy.ops.wm.save_mainfile(filepath=filepath, compress=compress, relative_remap=relative_remap)

    return {
        "status": "ok",
        "action": "save_as" if save_as else "save",
        "filepath": filepath,
        "copy": copy,
        "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else None,
    }


def _revert_file(args: dict) -> dict:
    if not bpy.data.filepath or not os.path.exists(bpy.data.filepath):
        raise ValueError("Cannot revert: the current file has not been saved on disk.")
    bpy.ops.wm.revert_mainfile()
    return {
        "status": "ok",
        "action": "revert",
        "filepath": bpy.data.filepath,
    }


def _new_file(args: dict) -> dict:
    use_empty = bool(args.get("use_empty", True))
    bpy.ops.wm.read_homefile(use_empty=use_empty)
    return {
        "status": "ok",
        "action": "new",
        "use_empty": use_empty,
        "objects_count": len(bpy.data.objects),
    }


def _import_format(args: dict) -> dict:
    filepath = _normalize_path(args.get("filepath"))
    if not filepath:
        raise ValueError("Argument 'filepath' is required for action 'import_format'")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: '{filepath}'")

    fmt = _detect_format(filepath, args.get("format"), is_import=True)
    op_path, _entry = _resolve_io_operator(fmt, is_import=True)

    target_col_name = args.get("target_collection")
    target_col = None
    if target_col_name:
        target_col = bpy.data.collections.get(target_col_name)
        if not target_col and target_col_name in ("Scene Collection", bpy.context.scene.collection.name):
            target_col = bpy.context.scene.collection
        if not target_col:
            raise KeyError(f"Target collection '{target_col_name}' not found")

    existing_objs = set(bpy.data.objects.keys())
    existing_cols = set(bpy.data.collections.keys())

    options = dict(args.get("options") or {})
    options["filepath"] = filepath

    result = rna.run_operator(
        op_path,
        options,
        undo=bool(args.get("undo", True)),
    )

    # Detect newly generated objects
    new_objs = [o for name, o in bpy.data.objects.items() if name not in existing_objs]
    new_cols = [c for name, c in bpy.data.collections.items() if name not in existing_cols]

    if target_col:
        for obj in new_objs:
            if obj.name not in target_col.objects:
                target_col.objects.link(obj)
            for c in list(obj.users_collection):
                if c != target_col and c != bpy.context.scene.collection:
                    c.objects.unlink(obj)
        for col in new_cols:
            if col.name not in target_col.children:
                target_col.children.link(col)

    bpy.context.view_layer.update()

    return {
        "status": "ok",
        "action": "import_format",
        "format": fmt,
        "filepath": filepath,
        "operator": op_path,
        "imported_objects": [o.name for o in new_objs],
        "imported_collections": [c.name for c in new_cols],
        "target_collection": target_col.name if target_col else None,
        "operator_result": result.get("result"),
    }


def _export_format(args: dict) -> dict:
    filepath = _normalize_path(args.get("filepath"))
    if not filepath:
        raise ValueError("Argument 'filepath' is required for action 'export_format'")

    fmt = _detect_format(filepath, args.get("format"), is_import=False)
    op_path, _entry = _resolve_io_operator(fmt, is_import=False)

    parent_dir = os.path.dirname(filepath)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    options = dict(args.get("options") or {})
    options["filepath"] = filepath

    selected_only = bool(args.get("selected_only", False))
    if selected_only:
        # Introspect whether operator uses use_selection or export_selected_objects
        mod_name, _, op_name = op_path.partition(".")
        parent_mod = getattr(bpy.ops, mod_name, None)
        if parent_mod:
            fn = getattr(parent_mod, op_name, None)
            if fn and hasattr(fn, "get_rna_type"):
                props = fn.get_rna_type().properties
                if "use_selection" in props:
                    options.setdefault("use_selection", True)
                elif "export_selected_objects" in props:
                    options.setdefault("export_selected_objects", True)

    result = rna.run_operator(op_path, options, undo=False)

    return {
        "status": "ok",
        "action": "export_format",
        "format": fmt,
        "filepath": filepath,
        "operator": op_path,
        "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else None,
        "operator_result": result.get("result"),
    }


def _pack_resources(args: dict) -> dict:
    mode = str(args.get("mode") or args.get("type") or "pack_all").lower().strip()
    undo = bool(args.get("undo", True))

    if mode == "pack_all":
        if undo:
            bpy.ops.ed.undo_push(message="MCP Pack All Resources")
        bpy.ops.file.pack_all()
        return {"status": "ok", "action": "pack_resources", "mode": "pack_all", "message": "All resources packed"}

    if mode == "unpack_all":
        if undo:
            bpy.ops.ed.undo_push(message="MCP Unpack All Resources")
        method = str(args.get("method") or "USE_LOCAL").upper().strip()
        bpy.ops.file.unpack_all(method=method)
        return {"status": "ok", "action": "pack_resources", "mode": "unpack_all", "method": method}

    if mode in ("find_missing", "find_missing_files"):
        search_dir = _normalize_path(args.get("directory") or args.get("filepath"))
        if not search_dir or not os.path.exists(search_dir):
            raise ValueError("Valid 'directory' is required for find_missing mode")
        bpy.ops.file.find_missing_files(directory=search_dir)
        return {"status": "ok", "action": "pack_resources", "mode": "find_missing", "search_directory": search_dir}

    if mode in ("make_relative", "make_paths_relative"):
        bpy.ops.file.make_paths_relative()
        return {"status": "ok", "action": "pack_resources", "mode": "make_relative"}

    if mode in ("make_absolute", "make_paths_absolute"):
        bpy.ops.file.make_paths_absolute()
        return {"status": "ok", "action": "pack_resources", "mode": "make_absolute"}

    raise ValueError(
        f"Unknown pack_resources mode '{mode}'. "
        "Valid: pack_all, unpack_all, find_missing, make_relative, make_absolute"
    )


def run(args: dict) -> dict:
    action = str(args.get("action") or "preview").lower().strip()

    if action == "preview":
        return _preview_blend(args)
    if action == "append":
        return _load_library(args, link=False)
    if action == "link":
        return _load_library(args, link=True)
    if action == "open":
        return _open_file(args)
    if action == "save":
        return _save_file(args, save_as=False)
    if action == "save_as":
        return _save_file(args, save_as=True)
    if action == "revert":
        return _revert_file(args)
    if action == "new":
        return _new_file(args)
    if action == "import_format":
        return _import_format(args)
    if action == "export_format":
        return _export_format(args)
    if action == "pack_resources":
        return _pack_resources(args)

    raise ValueError(f"Unknown action '{action}'. Valid actions: {list(_ACTIONS)}")


# --- MCP Registration -------------------------------------------------------

registry.register(
    name="blender_manage_file",
    handler=run,
    description=(
        "Comprehensive management of external files and asset libraries. "
        "Actions: 'preview' (inspect linkable datablocks of an external .blend without loading), "
        "'append' (append collections, objects, materials from external .blend into scene), "
        "'link' (link external datablocks with optional liboverrides), "
        "'open' (open main .blend project), 'save' (save active project), "
        "'save_as' (save as new file or copy), 'revert' (revert to disk), "
        "'new' (create empty or default project), "
        "'import_format' (import 3D formats: glTF, FBX, OBJ, USD, Alembic, PLY, STL, SVG), "
        "'export_format' (export to 3D formats), and 'pack_resources' (pack/unpack assets or resolve missing paths)."
    ),
    input_schema={
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": "File or asset operation to perform.",
            },
            "filepath": {
                "type": "string",
                "description": "Path to the .blend or external 3D file on disk.",
            },
            "datablock_type": {
                "type": "string",
                "default": "collections",
                "description": (
                    "Type of datablock for preview/append/link: 'collections', 'objects', "
                    "'materials', 'node_groups', 'armatures', 'actions', 'worlds', or 'all'."
                ),
            },
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific datablock names to append or link (or ['*'] for all).",
            },
            "target_collection": {
                "type": "string",
                "description": "Scene collection to link imported collections or objects into (defaults to active scene collection).",
            },
            "format": {
                "type": "string",
                "description": "Explicit 3D file format (e.g. gltf, glb, fbx, obj, usd, abc, ply, stl, svg). Auto-detected from file extension if omitted. Query available session formats via blender_describe(target='io_formats').",
            },
            "options": {
                "type": "object",
                "description": "Operator parameters passed to the format importer/exporter.",
            },
            "selected_only": {
                "type": "boolean",
                "default": False,
                "description": "Whether to export only selected objects when action is export_format.",
            },
            "copy": {
                "type": "boolean",
                "default": False,
                "description": "When action is save_as, save a copy without changing the active working file.",
            },
            "compress": {
                "type": "boolean",
                "default": True,
                "description": "Whether to compress the saved .blend file.",
            },
            "load_ui": {
                "type": "boolean",
                "default": False,
                "description": "Whether to load UI layout when action is open.",
            },
            "use_empty": {
                "type": "boolean",
                "default": True,
                "description": "Whether new project starts completely empty (default True).",
            },
            "create_liboverrides": {
                "type": "boolean",
                "default": False,
                "description": "When action is link, automatically create library overrides for modification.",
            },
            "recursive": {
                "type": "boolean",
                "default": True,
                "description": "When action is append, make indirect dependencies local.",
            },
            "mode": {
                "type": "string",
                "enum": ["pack_all", "unpack_all", "find_missing", "make_relative", "make_absolute"],
                "description": "Mode when action is pack_resources.",
            },
            "directory": {
                "type": "string",
                "description": "Search directory when mode is find_missing in pack_resources.",
            },
            "undo": {
                "type": "boolean",
                "default": True,
                "description": "Whether to record an undo step.",
            },
        },
    },
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
