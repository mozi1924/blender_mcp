# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic, version-agnostic Blender RNA kernel.

Nothing in this module knows about specific primitives, modifiers, materials or
node types.  Everything is discovered from Blender's RNA at runtime, which is
what makes the tools adaptive: when Blender adds a modifier, an operator
parameter or an enum item, the MCP surface picks it up automatically.

The kernel is intentionally dependency free (only ``bpy``) so it can be reused
by every tool handler.
"""

from __future__ import annotations

import bpy
import difflib
import math
import os

from mathutils import Quaternion

# RNA uses +-FLT_MAX style sentinels for "unbounded".  Do not advertise those as
# useful JSON-Schema bounds.
_SENTINEL = 1e29

_ID_COLLECTION_CACHE = None
_OPERATOR_MODULES_CACHE = None
_OPERATOR_METADATA_CACHE = {}


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def norm(key) -> str:
    """Normalise an RNA identifier / English label for fuzzy matching."""
    return (
        str(key)
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
        .replace("[", "")
        .replace("]", "")
    )


def jsonable(value):
    """Best effort conversion of RNA values to JSON friendly values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value, "name"):
        try:
            return value.name
        except Exception:
            pass
    try:
        return list(value)
    except Exception:
        return repr(value)


def suggest(key, candidates, limit=5):
    """Return close matches, supporting both identifiers and English labels."""
    candidates = list(candidates)
    matches = difflib.get_close_matches(str(key), candidates, n=limit, cutoff=0.45)
    if not matches:
        nk = norm(key)
        matches = [c for c in candidates if nk and (nk in norm(c) or norm(c) in nk)][:limit]
    return matches


def strip_bpy_ops(path: str) -> str:
    path = str(path).strip()
    if path.startswith("bpy.ops."):
        path = path[len("bpy.ops."):]
    return path


def operator_modules():
    global _OPERATOR_MODULES_CACHE
    if _OPERATOR_MODULES_CACHE is None:
        _OPERATOR_MODULES_CACHE = [m for m in dir(bpy.ops) if not m.startswith("_")]
    return _OPERATOR_MODULES_CACHE


def id_collections():
    """Map RNA struct identifier -> ``bpy.data`` collection name.

    Derived from ``bpy.data.bl_rna`` so new ID types (and addon ID types) work
    without a hardcoded table.  Example: ``{"Object": "objects", ...}``.
    """
    global _ID_COLLECTION_CACHE
    if _ID_COLLECTION_CACHE is None:
        mapping = {}
        for prop in bpy.data.bl_rna.properties:
            if prop.type != "COLLECTION":
                continue
            fixed = getattr(prop, "fixed_type", None)
            if fixed is None:
                continue
            mapping.setdefault(fixed.identifier, prop.identifier)
        _ID_COLLECTION_CACHE = mapping
    return _ID_COLLECTION_CACHE


def refresh():
    """Drop derived caches (after enabling/disabling addons, loading a file...)."""
    global _ID_COLLECTION_CACHE, _OPERATOR_MODULES_CACHE
    _ID_COLLECTION_CACHE = None
    _OPERATOR_MODULES_CACHE = None
    _OPERATOR_METADATA_CACHE.clear()


# ---------------------------------------------------------------------------
# Property introspection
# ---------------------------------------------------------------------------


def _bounds(prop):
    mn = getattr(prop, "hard_min", None)
    mx = getattr(prop, "hard_max", None)
    if mn is not None and abs(mn) >= _SENTINEL:
        mn = None
    if mx is not None and abs(mx) >= _SENTINEL:
        mx = None
    return mn, mx


def prop_default(prop):
    try:
        if getattr(prop, "is_array", False):
            arr = getattr(prop, "default_array", None)
            return jsonable(arr) if arr is not None else None
        return jsonable(prop.default)
    except Exception:
        return None


def prop_info(prop) -> dict:
    """Full RNA description of a property (the adaptive payload)."""
    info = {
        "identifier": prop.identifier,
        "name": prop.name,
        "description": (prop.description or "").strip(),
        "type": prop.type,
        "subtype": getattr(prop, "subtype", "NONE"),
        "is_required": bool(getattr(prop, "is_required", False)),
        "is_readonly": bool(prop.is_readonly),
        "is_array": bool(getattr(prop, "is_array", False)),
        "array_length": int(getattr(prop, "array_length", 0) or 0),
    }
    default = prop_default(prop)
    if default is not None and prop.type not in ("POINTER", "COLLECTION"):
        info["default"] = default
    if prop.type == "ENUM":
        info["is_enum_flag"] = bool(getattr(prop, "is_enum_flag", False))
        info["enum"] = [item.identifier for item in prop.enum_items]
        info["enum_items"] = [
            {
                "identifier": item.identifier,
                "name": item.name,
                "description": (item.description or "").strip(),
            }
            for item in prop.enum_items
        ]
    if prop.type in ("INT", "FLOAT"):
        mn, mx = _bounds(prop)
        if mn is not None:
            info["minimum"] = mn
        if mx is not None:
            info["maximum"] = mx
        smn = getattr(prop, "soft_min", None)
        smx = getattr(prop, "soft_max", None)
        if smn is not None and abs(smn) < _SENTINEL:
            info["x-soft-minimum"] = smn
        if smx is not None and abs(smx) < _SENTINEL:
            info["x-soft-maximum"] = smx
    if prop.type in ("POINTER", "COLLECTION"):
        fixed = getattr(prop, "fixed_type", None)
        if fixed is not None:
            info["fixed_type"] = fixed.identifier
    return info


def prop_schema(prop, *, include_default=True) -> dict:
    """Convert a single RNA property to a JSON-Schema fragment."""
    t = prop.type
    is_array = bool(getattr(prop, "is_array", False))
    length = int(getattr(prop, "array_length", 0) or 0)

    if t == "ENUM":
        items = list(prop.enum_items)
        if items:
            schema = {"type": "string", "enum": [i.identifier for i in items]}
            schema["x-enum-labels"] = {i.identifier: i.name for i in items}
            descs = {i.identifier: (i.description or "").strip() for i in items if i.description}
            if descs:
                schema["x-enum-descriptions"] = descs
        else:
            # Dynamic menu sockets (e.g. NodeSocketMenu) expose no static items.
            schema = {"type": "string", "x-dynamic-enum": True}
    elif t == "BOOLEAN":
        schema = {"type": "boolean"}
    elif t in ("INT", "FLOAT"):
        base = {"type": "integer" if t == "INT" else "number"}
        mn, mx = _bounds(prop)
        if mn is not None:
            base["minimum"] = mn
        if mx is not None:
            base["maximum"] = mx
        if is_array:
            schema = {"type": "array", "items": base}
            if length:
                schema["minItems"] = length
                schema["maxItems"] = length
        else:
            schema = base
    elif t == "STRING":
        schema = {"type": "string"}
        subtype = getattr(prop, "subtype", "NONE")
        if subtype and subtype != "NONE":
            schema["x-subtype"] = subtype
    elif t == "POINTER":
        schema = {"type": ["string", "null"]}
        fixed = getattr(prop, "fixed_type", None)
        if fixed is not None:
            schema["x-pointer-type"] = fixed.identifier
    elif t == "COLLECTION":
        schema = {"type": "array", "items": {"type": "string"}}
        fixed = getattr(prop, "fixed_type", None)
        if fixed is not None:
            schema["x-pointer-type"] = fixed.identifier
    else:
        schema = {}

    desc = (prop.description or "").strip()
    if desc:
        schema["description"] = desc
    if getattr(prop, "is_readonly", False):
        schema["readOnly"] = True
    if include_default:
        default = prop_default(prop)
        if default is not None and t not in ("POINTER", "COLLECTION"):
            schema["default"] = default
    return schema


def properties_of(srna):
    """Iterate the *direct* properties of an RNA struct (skip ``rna_type``)."""
    for prop in srna.properties:
        if prop.identifier == "rna_type":
            continue
        yield prop


def describe_struct(srna, *, include_schema=True) -> dict:
    props = [prop_info(p) for p in properties_of(srna)]
    result = {
        "identifier": srna.identifier,
        "name": srna.name,
        "description": (srna.description or "").strip(),
        "properties_count": len(props),
        "properties": props,
    }
    if include_schema:
        result["input_schema"] = {
            "type": "object",
            "properties": {p.identifier: prop_schema(p) for p in properties_of(srna)},
            "required": [p.identifier for p in properties_of(srna) if getattr(p, "is_required", False)],
        }
    return result


# ---------------------------------------------------------------------------
# Property matching / coercion / application
# ---------------------------------------------------------------------------


def _prop_table(source):
    if isinstance(source, dict):
        return source
    srna = getattr(source, "bl_rna", source)
    return {p.identifier: p for p in properties_of(srna)}


def find_property(source, key):
    """Resolve a user supplied key against RNA identifiers and English labels.

    Returns ``(prop, identifier, score)`` or ``(None, None, 0)``.  Exact
    identifier wins, then label, then normalised variants.  This is the only
    matching logic used by every tool.
    """
    table = _prop_table(source)
    if not table:
        return None, None, 0
    key_s = str(key)
    if key_s in table:
        return table[key_s], key_s, 100

    nk = norm(key_s)
    candidates = []
    for identifier, prop in table.items():
        if norm(identifier) == nk:
            return prop, identifier, 90
        if norm(prop.name) == nk:
            return prop, identifier, 80
        if nk and (nk in norm(identifier) or nk in norm(prop.name)):
            candidates.append((prop, identifier))
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1], 40
    return None, None, 0


def _enum_lookup(prop, value):
    raw = str(value)
    # Exact identifier first (fast path).
    for item in prop.enum_items:
        if item.identifier == raw:
            return item.identifier
    low = raw.lower()
    for item in prop.enum_items:
        if item.identifier.lower() == low:
            return item.identifier
    nv = norm(raw)
    for item in prop.enum_items:
        if norm(item.identifier) == nv or norm(item.name) == nv:
            return item.identifier
    valid = [item.identifier for item in prop.enum_items]
    raise ValueError(f"Invalid enum value {value!r}. Valid values: {valid}")


def coerce_value(prop, value):
    """Coerce a JSON value into whatever ``setattr`` expects for this RNA prop."""
    t = prop.type
    if value is None:
        if t in ("POINTER", "COLLECTION", "STRING"):
            return None
        raise ValueError(f"Property '{prop.identifier}' does not accept null")

    if t == "ENUM":
        if isinstance(value, (list, tuple, set)):
            return {_enum_lookup(prop, v) for v in value}
        return _enum_lookup(prop, value)

    if t == "BOOLEAN":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off", ""):
                return False
        raise ValueError(f"Property '{prop.identifier}' expects a boolean, got {value!r}")

    if t in ("INT", "FLOAT"):
        cast = int if t == "INT" else float
        if getattr(prop, "is_array", False):
            if t == "FLOAT" and getattr(prop, "subtype", "") == "COLOR":
                if isinstance(value, str) and value.startswith("#"):
                    rgba = hex_to_rgba(value)
                    length = int(getattr(prop, "array_length", 0) or 0)
                    value = rgba[:length] if length else rgba
            length = int(getattr(prop, "array_length", 0) or 0)
            if isinstance(value, (int, float)):
                value = [value] * (length or 1)
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"Property '{prop.identifier}' expects an array")
            values = [cast(v) for v in value]
            if length and len(values) != length:
                raise ValueError(
                    f"Property '{prop.identifier}' expects {length} values, got {len(values)}"
                )
            return values
        return cast(value)

    if t == "STRING":
        return str(value)

    if t == "POINTER":
        fixed = getattr(prop, "fixed_type", None)
        fixed_type = fixed.identifier if fixed is not None else None
        if hasattr(value, "bl_rna") and value.bl_rna.identifier == fixed_type:
            return value
        if isinstance(value, str):
            return resolve_id(fixed_type, value)
        raise ValueError(
            f"Property '{prop.identifier}' expects a {fixed_type or 'datablock'} name, got {value!r}"
        )

    if t == "COLLECTION":
        fixed = getattr(prop, "fixed_type", None)
        fixed_type = fixed.identifier if fixed is not None else None
        if not isinstance(value, (list, tuple)):
            value = [value]
        out = []
        for item in value:
            if hasattr(item, "bl_rna"):
                out.append(item)
            elif isinstance(item, str):
                out.append(resolve_id(fixed_type, item))
            else:
                out.append(item)
        return out

    # Unknown RNA types: pass through and let Blender validate.
    return value


def resolve_id(fixed_type, name):
    """Resolve a datablock name generically using ``bpy.data`` RNA metadata."""
    if fixed_type is None:
        raise ValueError(f"Cannot resolve datablock '{name}': unknown RNA type")
    collection_name = id_collections().get(fixed_type)
    if not collection_name:
        raise ValueError(f"No bpy.data collection registered for RNA type '{fixed_type}'")
    collection = getattr(bpy.data, collection_name, None)
    if collection is None:
        raise ValueError(f"bpy.data.{collection_name} is not available")
    item = collection.get(str(name))
    if item is None:
        available = [item.name for item in collection][:20]
        raise KeyError(
            f"{fixed_type} '{name}' not found in bpy.data.{collection_name}. "
            f"Available (first 20): {available}"
        )
    return item


def _report_value(prop, value):
    t = prop.type
    if t == "POINTER":
        return getattr(value, "name", None)
    if t == "COLLECTION":
        return [getattr(v, "name", str(v)) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return jsonable(value)


def apply_properties(owner, values, *, source=None, strict=False) -> dict:
    """Apply a mapping of RNA properties with coercion and structured feedback.

    ``owner`` can be any RNA struct instance.  Unknown keys are never silently
    ignored: they are returned with suggestions so the caller (agent) can
    self-correct.
    """
    source = source or owner
    table = _prop_table(source)
    applied, warnings, errors, unknown = {}, [], [], []

    for key, value in (values or {}).items():
        prop, identifier, _score = find_property(table, key)
        if prop is None:
            unknown.append(key)
            warnings.append(
                f"Unknown property '{key}'. Did you mean: {suggest(key, table.keys())}"
            )
            continue
        if prop.is_readonly:
            warnings.append(f"Property '{identifier}' is read-only and was skipped")
            continue
        try:
            coerced = coerce_value(prop, value)
            setattr(owner, identifier, coerced)
            applied[identifier] = _report_value(prop, coerced)
        except Exception as ex:
            errors.append(f"Failed to set '{identifier}'={value!r}: {ex}")

    result = {"applied": applied, "warnings": warnings}
    if errors:
        result["errors"] = errors
    if unknown:
        result["unknown"] = unknown
    if strict and (errors or unknown):
        result["strict_failed"] = True
    return result


# ---------------------------------------------------------------------------
# Operator introspection / execution
# ---------------------------------------------------------------------------


def find_operator_function(path):
    """Resolve ``mesh.primitive_cube_add`` / ``MESH_OT_primitive_cube_add``."""
    raw = strip_bpy_ops(path)
    if "_OT_" in raw:
        module, name = raw.split("_OT_", 1)
        module, name = module.lower(), name.lower()
        parent = getattr(bpy.ops, module, None)
        fn = getattr(parent, name, None) if parent is not None else None
        if fn is None:
            raise KeyError(f"Operator '{path}' not found (module '{module}', op '{name}')")
        return module, name, fn

    if "." in raw:
        module, name = raw.split(".", 1)
        parent = getattr(bpy.ops, module, None)
        fn = getattr(parent, name, None) if parent is not None else None
        if fn is None:
            raise KeyError(f"Operator '{path}' not found")
        return module, name, fn

    matches = []
    for module in operator_modules():
        parent = getattr(bpy.ops, module, None)
        if parent is not None and hasattr(parent, raw):
            matches.append((module, raw))
    if len(matches) == 1:
        module, name = matches[0]
        return module, name, getattr(getattr(bpy.ops, module), name)
    if not matches:
        raise KeyError(f"Operator '{path}' not found in any bpy.ops module")
    raise KeyError(f"Operator name '{path}' is ambiguous: {matches}. Use 'module.operator'.")


def operator_idname(fn):
    try:
        return fn.idname()
    except Exception:
        return None


def describe_operator(path) -> dict:
    module, name, fn = find_operator_function(path)
    rt = fn.get_rna_type()

    props = []
    readonly = []
    for prop in properties_of(rt):
        info = prop_info(prop)
        props.append(info)
        if prop.is_readonly:
            readonly.append(prop.identifier)

    required = [p.identifier for p in properties_of(rt) if getattr(p, "is_required", False)]

    poll = None
    poll_error = None
    try:
        poll = bool(fn.poll())
    except Exception as ex:  # context dependent operators may raise
        poll_error = str(ex)

    input_schema = {
        "type": "object",
        "properties": {
            p.identifier: prop_schema(p) for p in properties_of(rt) if not p.is_readonly
        },
        "required": required,
    }

    return {
        "status": "ok",
        "operator": f"{module}.{name}",
        "idname": operator_idname(fn) or rt.identifier,
        "name": rt.name,
        "description": (rt.description or "").strip(),
        "poll": poll,
        "poll_error": poll_error,
        "properties_count": len(props),
        "properties": props,
        "readonly_properties": readonly,
        "input_schema": input_schema,
    }


def list_operators(query="", module=None, prefix=None, limit=50) -> dict:
    query = (query or "").strip()
    nquery = norm(query)
    cache = _OPERATOR_METADATA_CACHE

    results = []
    modules = [module] if module else operator_modules()
    for mod_name in modules:
        parent = getattr(bpy.ops, mod_name, None)
        if parent is None:
            continue
        for op_name in dir(parent):
            if op_name.startswith("_"):
                continue
            if prefix and not op_name.startswith(prefix):
                continue
            path = f"{mod_name}.{op_name}"
            if query and nquery not in norm(path):
                # Metadata lookup is cheap enough; still avoid it when the
                # path already cannot match.
                key = path
                meta = cache.get(key)
                if meta is None:
                    try:
                        fn = getattr(parent, op_name)
                        rt = fn.get_rna_type()
                        meta = {
                            "name": rt.name,
                            "description": (rt.description or "").strip(),
                            "idname": operator_idname(fn) or rt.identifier,
                        }
                    except Exception:
                        meta = {"name": op_name, "description": "", "idname": path}
                    cache[key] = meta
                haystack = norm(meta["name"]) + norm(meta["description"]) + norm(path)
                if nquery not in haystack:
                    continue
            else:
                meta = cache.get(path)
                if meta is None:
                    try:
                        fn = getattr(parent, op_name)
                        rt = fn.get_rna_type()
                        meta = {
                            "name": rt.name,
                            "description": (rt.description or "").strip(),
                            "idname": operator_idname(fn) or rt.identifier,
                        }
                    except Exception:
                        meta = {"name": op_name, "description": "", "idname": path}
                    cache[path] = meta
            results.append({"operator": path, **meta})

    results.sort(key=lambda item: (len(item["operator"]), item["operator"]))
    return {
        "status": "ok",
        "query": query,
        "count": len(results),
        "operators": results[: max(1, int(limit))],
        "truncated": len(results) > int(limit),
    }


def _operator_schema_table(rt):
    table = {}
    for prop in properties_of(rt):
        if prop.is_readonly:
            continue
        table[prop.identifier] = prop
    return table


def operator_property_table(path):
    """Public: writable RNA properties of an operator, keyed by identifier."""
    _module, _name, fn = find_operator_function(path)
    return _operator_schema_table(fn.get_rna_type())


def move_to_collection(obj, collection_name):
    """Move an object into a collection, creating the collection if needed."""
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for owner in list(obj.users_collection):
        if owner != collection:
            owner.objects.unlink(obj)
    return collection.name


def object_summary(obj):
    """Compact object report shared by run_operator and primitive creation."""
    if obj is None:
        return None
    if obj.rotation_mode == "QUATERNION":
        euler = obj.rotation_quaternion.to_euler()
    elif obj.rotation_mode == "AXIS_ANGLE":
        quat = Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
        euler = quat.to_euler()
    else:
        euler = obj.rotation_euler
    return {
        "name": obj.name,
        "type": obj.type,
        "location": [round(value, 4) for value in obj.location],
        "rotation_euler_deg": [round(math.degrees(value), 2) for value in euler],
        "scale": [round(value, 4) for value in obj.scale],
        "dimensions": [round(value, 4) for value in obj.dimensions],
        "collection": obj.users_collection[0].name if obj.users_collection else None,
    }


def _apply_post_properties(obj, values):
    """Apply post-creation properties to an object or its data."""
    applied, warnings, unresolved = {}, [], []
    remaining = dict(values or {})

    if "text" in remaining or "body" in remaining:
        body = remaining.pop("text", remaining.pop("body", None))
        if hasattr(obj.data, "body"):
            obj.data.body = str(body)
            applied["body"] = str(body)
        else:
            warnings.append("Parameter 'text'/'body' ignored: object has no text body")

    object_props, data_props = {}, {}
    for key, value in list(remaining.items()):
        if find_property(obj, key)[0] is not None:
            object_props[key] = remaining.pop(key)
        elif obj.data is not None and find_property(obj.data, key)[0] is not None:
            data_props[key] = remaining.pop(key)

    if object_props:
        result = apply_properties(obj, object_props)
        applied.update(result.get("applied", {}))
        warnings.extend(result.get("warnings", []))
        warnings.extend(result.get("errors", []))
    if data_props:
        result = apply_properties(obj.data, data_props)
        applied.update(result.get("applied", {}))
        warnings.extend(result.get("warnings", []))
        warnings.extend(result.get("errors", []))

    unresolved = sorted(remaining.keys())
    return applied, warnings, unresolved


def run_operator(
    path,
    parameters=None,
    *,
    undo=True,
    select=None,
    active=None,
    context=None,
    name=None,
    collection=None,
    properties=None,
    location=None,
    rotation=None,
    scale=None,
) -> dict:
    """Invoke any Blender operator with RNA validation and post-processing.

    ``name``/``collection``/``properties`` apply to the created object, which
    makes this tool a superset of the old primitive wrapper.  ``location``,
    ``rotation`` (degrees) and ``scale`` are merged into operator parameters
    when supported, otherwise applied to the created object afterwards.
    """
    parameters = dict(parameters or {})
    module, op_name, fn = find_operator_function(path)
    rt = fn.get_rna_type()
    table = _operator_schema_table(rt)

    poll = None
    poll_error = None
    try:
        poll = bool(fn.poll())
    except Exception as ex:
        poll_error = str(ex)

    deferred = {}
    for key, value in (("location", location), ("rotation", rotation), ("scale", scale)):
        if value is None:
            continue
        if key == "rotation":
            value = [math.radians(float(item)) for item in value]
        # Creation operators interpret `scale` by scaling mesh data; the tool's
        # convenience contract is object scale, so always apply it post-hoc.
        if key == "scale":
            deferred[key] = value
        elif key in table:
            parameters[key] = value
        else:
            deferred[key] = value

    warnings, unknown = [], []
    kwargs = {}
    for key, value in parameters.items():
        prop, identifier, _score = find_property(table, key)
        if prop is None:
            unknown.append(key)
            warnings.append(
                f"Unknown parameter '{key}'. Valid parameters: {sorted(table.keys())}. "
                f"Did you mean: {suggest(key, table.keys())}"
            )
            continue
        try:
            kwargs[identifier] = coerce_value(prop, value)
        except Exception as ex:
            return {
                "status": "error",
                "operator": f"{module}.{op_name}",
                "message": f"Invalid value for '{identifier}': {ex}",
                "unknown": unknown,
                "warnings": warnings,
            }

    if unknown:
        return {
            "status": "error",
            "operator": f"{module}.{op_name}",
            "message": "Operator call rejected because of unknown parameters.",
            "unknown": unknown,
            "warnings": warnings,
            "valid_parameters": sorted(table.keys()),
        }

    if poll is False:
        return {
            "status": "error",
            "operator": f"{module}.{op_name}",
            "message": (
                "Operator poll() returned False: the current Blender context does not "
                "allow it. Select the right object/mode or use blender_execute_script "
                "with a context override."
            ),
            "poll": poll,
            "poll_error": poll_error,
        }

    # Optional target selection (helps operators that act on the active object).
    if select or active:
        try:
            names = [] if select is None else (select if isinstance(select, (list, tuple)) else [select])
            for obj in bpy.context.view_layer.objects:
                obj.select_set(False)
            for obj_name in names:
                obj = resolve_id("Object", obj_name)
                obj.select_set(True)
            if active:
                bpy.context.view_layer.objects.active = resolve_id("Object", active)
        except Exception as ex:
            return {"status": "error", "message": f"Could not select target: {ex}"}

    if undo:
        try:
            bpy.ops.ed.undo_push(message=f"MCP {module}.{op_name}")
        except Exception:
            pass

    before_objects = set(bpy.data.objects.keys())
    try:
        if context:
            override = _build_context_override(context)
            with bpy.context.temp_override(**override):
                result = fn(**kwargs)
        else:
            result = fn(**kwargs)
    except Exception as ex:
        import traceback

        return {
            "status": "error",
            "operator": f"{module}.{op_name}",
            "message": f"Operator raised: {ex}",
            "traceback": traceback.format_exc(),
            "parameters": {k: jsonable(v) for k, v in kwargs.items()},
            "poll": poll,
        }

    created = sorted(set(bpy.data.objects.keys()) - before_objects)
    result_set = sorted(str(item) for item in result) if result is not None else []
    active_obj = bpy.context.view_layer.objects.active
    created_obj = bpy.data.objects.get(created[0]) if created else active_obj

    if name and created_obj is not None:
        created_obj.name = str(name)
    if collection and created_obj is not None:
        try:
            move_to_collection(created_obj, str(collection))
        except Exception as ex:
            warnings.append(f"Could not move object to collection '{collection}': {ex}")

    post_applied, post_warnings, unresolved = _apply_post_properties(
        created_obj, {**deferred, **(properties or {})}
    ) if created_obj is not None else ({}, [], sorted((properties or {}).keys()) + sorted(deferred.keys()))
    warnings.extend(post_warnings)

    response = {
        "status": "ok",
        "operator": f"{module}.{op_name}",
        "result": result_set,
        "parameters": {k: jsonable(v) for k, v in kwargs.items()},
        "created_objects": created,
        "active_object": active_obj.name if active_obj else None,
        "created_object": object_summary(created_obj),
        "post_properties": post_applied,
        "warnings": warnings,
    }

    if unresolved:
        response["status"] = "error"
        response["message"] = (
            f"Operator ran, but these post properties were not found on the created "
            f"object or its data: {unresolved}."
        )
        response["unresolved_properties"] = unresolved

    return response


def _build_context_override(context):
    """Resolve a small, JSON friendly context override description."""
    override = {}
    if not isinstance(context, dict):
        return override
    for key in ("object", "active_object"):
        if key in context:
            value = context[key]
            override[key] = resolve_id("Object", value) if isinstance(value, str) else value
    if "selected_objects" in context:
        values = context["selected_objects"]
        if not isinstance(values, (list, tuple)):
            values = [values]
        override["selected_objects"] = [
            resolve_id("Object", v) if isinstance(v, str) else v for v in values
        ]
    if "area_type" in context and bpy.context.screen:
        area = next(
            (a for a in bpy.context.screen.areas if a.type == str(context["area_type"]).upper()),
            None,
        )
        if area is not None:
            override["area"] = area
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is not None:
                override["region"] = region
            if bpy.context.window is not None:
                override["window"] = bpy.context.window
    return override


# ---------------------------------------------------------------------------
# Path resolution (used by blender_set and other generic tools)
# ---------------------------------------------------------------------------


def parse_path(path):
    """Parse ``a.b[Key].c[0]`` into ``["a", "b", "Key", "c", "0"]``."""
    tokens = []
    buf = []
    i = 0
    path = str(path or "")
    while i < len(path):
        char = path[i]
        if char == ".":
            if buf:
                tokens.append("".join(buf))
                buf = []
        elif char == "[":
            if buf:
                tokens.append("".join(buf))
                buf = []
            end = path.find("]", i)
            if end < 0:
                raise ValueError(f"Unclosed '[' in path: {path}")
            key = path[i + 1 : end].strip()
            if len(key) >= 2 and key[0] in ("'", '"') and key[-1] == key[0]:
                key = key[1:-1]
            tokens.append(key)
            i = end
        else:
            buf.append(char)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def _path_child(current, token):
    if current is None:
        raise KeyError(f"Cannot resolve '{token}': parent is null")
    try:
        if hasattr(current, token):
            return getattr(current, token)
    except Exception:
        pass
    if isinstance(current, dict) and token in current:
        return current[token]
    try:
        if str(token).lstrip("-").isdigit():
            return current[int(token)]
    except Exception:
        pass
    try:
        if hasattr(current, "get"):
            value = current.get(token)
            if value is not None:
                return value
        return current[token]
    except Exception as ex:
        raise KeyError(f"Cannot resolve path segment '{token}': {ex}")


def resolve_path(root, path):
    """Resolve a full relative path from ``root``."""
    current = root
    for token in parse_path(path):
        current = _path_child(current, token)
    return current


def resolve_path_with_leaf(root, path):
    """Resolve the parent of the final path segment; returns ``(parent, leaf)``."""
    tokens = parse_path(path)
    if not tokens:
        return root, None
    current = root
    for token in tokens[:-1]:
        current = _path_child(current, token)
    return current, tokens[-1]


def resolve_target(target, create=False):
    """Resolve a root target expression.

    Examples:
      scene, render, world, view_layer
      object:RustCube
      object_data:RustCube
      modifier:RustCube/Subsurf
      material:MetallicBlue
      node:MetallicBlue/Principled BSDF
      nodetree:MyGroup
      light:KeyLight, camera:Camera, collection:Props
      mesh:Name ... any bpy.data collection
    """
    text = str(target or "").strip()
    key = text.lower()
    if key in ("", "scene"):
        return bpy.context.scene
    if key in ("render", "scene.render"):
        return bpy.context.scene.render
    if key in ("world", "scene.world"):
        world = bpy.context.scene.world
        if world is None and create:
            world = bpy.data.worlds.new("World")
            bpy.context.scene.world = world
        return world
    if key in ("view_layer", "viewlayer"):
        return bpy.context.view_layer

    if ":" in text:
        kind, name = text.split(":", 1)
        nk = norm(kind)

        if nk in ("object", "obj"):
            return resolve_id("Object", name)
        if nk in ("objectdata", "objdata", "data"):
            return resolve_id("Object", name).data
        if nk in ("modifier", "mod"):
            obj_name, _, mod_name = name.partition("/")
            if not mod_name:
                raise ValueError("modifier target must be 'Object/ModifierName'")
            obj = resolve_id("Object", obj_name)
            modifier = obj.modifiers.get(mod_name)
            if modifier is None:
                raise KeyError(f"Modifier '{mod_name}' not found on '{obj_name}'")
            return modifier
        if nk in ("node",):
            owner_name, _, node_name = name.partition("/")
            if not node_name:
                raise ValueError("node target must be 'MaterialOrNodeGroup/NodeName'")
            owner = bpy.data.materials.get(owner_name) or bpy.data.node_groups.get(owner_name)
            if owner is None:
                raise KeyError(f"Material/NodeGroup '{owner_name}' not found")
            tree = getattr(owner, "node_tree", owner)
            node = tree.nodes.get(node_name)
            if node is None:
                raise KeyError(f"Node '{node_name}' not found in '{owner_name}'")
            return node
        if nk in ("nodetree", "nodegroup"):
            return resolve_id("NodeTree", name)
        if nk in ("pose_bone", "posebone", "bone"):
            obj_name, _, bone_name = name.partition("/")
            if not bone_name:
                raise ValueError("pose_bone target must be 'ArmatureObject/BoneName'")
            obj = resolve_id("Object", obj_name)
            if not getattr(obj, "pose", None):
                raise ValueError(f"Object '{obj_name}' is not an armature or has no pose data")
            pbone = obj.pose.bones.get(bone_name)
            if pbone is None:
                raise KeyError(f"Pose bone '{bone_name}' not found on '{obj_name}'")
            return pbone
        if nk in ("pose",):
            obj_name, _, bone_name = name.partition("/")
            obj = resolve_id("Object", obj_name)
            if not getattr(obj, "pose", None):
                raise ValueError(f"Object '{obj_name}' is not an armature or has no pose data")
            if bone_name:
                pbone = obj.pose.bones.get(bone_name)
                if pbone is None:
                    raise KeyError(f"Pose bone '{bone_name}' not found on '{obj_name}'")
                return pbone
            return obj.pose

        for fixed_type, collection_name in id_collections().items():
            if nk in (
                norm(collection_name),
                norm(fixed_type),
                norm(collection_name.rstrip("s")),
                norm(fixed_type.rstrip("s")),
            ):
                try:
                    return resolve_id(fixed_type, name)
                except KeyError:
                    if not create:
                        raise
                    collection = getattr(bpy.data, collection_name, None)
                    if collection is None:
                        raise
                    try:
                        if fixed_type == "Light":
                            return collection.new(name=name, type="POINT")
                        return collection.new(name=name)
                    except TypeError as ex:
                        raise ValueError(
                            f"Cannot create {fixed_type} '{name}' generically: {ex}. "
                            "Use blender_run_operator or blender_execute_script."
                        )

        raise KeyError(
            f"Unknown target kind '{kind}'. Use scene, render, world, object:NAME, "
            "object_data:NAME, modifier:OBJECT/MODIFIER, material:NAME, "
            "node:OWNER/NODE, nodetree:NAME, or a bpy.data ID type."
        )

    if text in bpy.data.objects:
        return bpy.data.objects[text]
    for fixed_type, collection_name in id_collections().items():
        collection = getattr(bpy.data, collection_name, None)
        if collection is not None and text in collection:
            return collection[text]
    raise KeyError(f"Target '{target}' not found")


# ---------------------------------------------------------------------------
# Shared material / node socket helpers (replaces per-tool copies)
# ---------------------------------------------------------------------------


def hex_to_rgba(hex_str):
    text = str(hex_str).lstrip("#")
    try:
        if len(text) == 6:
            return [int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4)] + [1.0]
        if len(text) == 8:
            return [int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4, 6)]
    except ValueError:
        pass
    return [1.0, 1.0, 1.0, 1.0]


def find_socket(node, socket_name, is_output=False):
    """Find a socket by identifier, name, normalised name or socket type."""
    sockets = node.outputs if is_output else node.inputs
    wanted = str(socket_name)
    for sock in sockets:
        if sock.identifier == wanted or sock.name == wanted:
            return sock
    nw = norm(wanted)
    for sock in sockets:
        if norm(sock.identifier) == nw or norm(sock.name) == nw:
            return sock
    type_matches = [s for s in sockets if norm(getattr(s, "type", "")) == nw]
    if len(type_matches) == 1:
        return type_matches[0]
    return None


def set_socket_value(sock, value):
    """Set a socket default using the socket's own RNA ``default_value`` type.

    No hardcoded socket type switch: colors, vectors, ints, pointers, menus and
    future socket types all go through the generic property kernel.
    """
    prop = sock.bl_rna.properties.get("default_value")
    if prop is None:
        raise ValueError(f"Socket '{sock.name}' has no default_value")
    if prop.type == "STRING" and isinstance(value, str) and value.startswith("#"):
        value = "#" + value.lstrip("#")
    if prop.type == "ENUM":
        try:
            sock.default_value = coerce_value(prop, value)
            return
        except Exception:
            # Menu sockets can have dynamic enum items not exposed as static
            # RNA items; fall back to assigning the raw value.
            if isinstance(value, str):
                sock.default_value = value
                return
            raise
    if prop.type == "FLOAT" and getattr(prop, "subtype", "") == "COLOR":
        if isinstance(value, str):
            value = hex_to_rgba(value)
        elif isinstance(value, (list, tuple)) and len(value) == 3:
            value = list(value) + [1.0]
    sock.default_value = coerce_value(prop, value)


def apply_sockets(node, values, *, strict=False):
    """Apply a mapping of socket name -> value to a node."""
    applied, warnings = {}, []
    for key, value in (values or {}).items():
        sock = find_socket(node, key, is_output=False)
        if sock is None:
            available = [s.name for s in node.inputs]
            warnings.append(
                f"Unknown input socket '{key}'. Available: {available}. "
                f"Did you mean: {suggest(key, available)}"
            )
            continue
        try:
            set_socket_value(sock, value)
            applied[sock.name] = jsonable(value)
        except Exception as ex:
            warnings.append(f"Could not set socket '{sock.name}'={value!r}: {ex}")
    result = {"applied": applied, "warnings": warnings}
    if strict and warnings:
        result["strict_failed"] = True
    return result


def socket_info(sock):
    prop = sock.bl_rna.properties.get("default_value")
    info = {
        "name": sock.name,
        "identifier": sock.identifier,
        "type": getattr(sock, "type", None),
        "is_linked": bool(getattr(sock, "is_linked", False)),
        "is_multi_input": bool(getattr(sock, "is_multi_input", False)),
    }
    if prop is not None:
        info["rna_type"] = prop.type
        if prop.type == "ENUM":
            info["enum"] = [item.identifier for item in prop.enum_items]
        if prop.type == "POINTER":
            fixed = getattr(prop, "fixed_type", None)
            info["pointer_type"] = fixed.identifier if fixed is not None else None
        default = prop_default(prop)
        if default is not None:
            info["default"] = default
    return info


__all__ = [
    "norm",
    "jsonable",
    "suggest",
    "prop_info",
    "prop_schema",
    "prop_default",
    "describe_struct",
    "find_property",
    "coerce_value",
    "resolve_id",
    "apply_properties",
    "find_operator_function",
    "operator_idname",
    "describe_operator",
    "list_operators",
    "operator_property_table",
    "run_operator",
    "hex_to_rgba",
    "parse_path",
    "resolve_path",
    "resolve_path_with_leaf",
    "resolve_target",
    "find_socket",
    "set_socket_value",
    "apply_sockets",
    "socket_info",
    "id_collections",
    "refresh",
]
