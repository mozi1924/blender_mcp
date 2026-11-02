# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP schemas for the migrated semantic tools.

Stable API fields (action names, target names) stay literal; Blender-owned
enums are refreshed from RNA in :func:`input_schema` so ``tools/list`` never
serves a stale value.
"""

import copy

TOOLS = {'blender_inspect': {'name': 'blender_inspect',
                     'description': 'inputSchema',
                     'inputSchema': {'type': 'object',
                                     'properties': {'target': {'type': 'string',
                                                               'enum': ['scene',
                                                                        'object',
                                                                        'file',
                                                                        'datablocks'],
                                                               'default': 'scene',
                                                               'description': "What to inspect: 'scene' "
                                                                              '(collection hierarchy & '
                                                                              "active state), 'object' (deep "
                                                                              "object details), 'file' "
                                                                              '(filepath, saved status, '
                                                                              'missing files), or '
                                                                              "'datablocks' (counts of "
                                                                              'meshes, materials, etc.).'},
                                                    'name': {'type': 'string',
                                                             'description': 'Object name to inspect. '
                                                                            'Required when target is '
                                                                            "'object'."},
                                                    'scene': {'type': 'string',
                                                              'description': 'Optional scene name to inspect '
                                                                             "when target is 'scene' (defaults "
                                                                             'to active scene).'},
                                                    'collection': {'type': 'string',
                                                                   'description': 'Optional collection name '
                                                                                  'to filter inspection when '
                                                                                  "target is 'scene'."},
                                                    'object_type': {'type': 'string',
                                                                    'description': 'Optional object type '
                                                                                   "filter (e.g. 'MESH', "
                                                                                   "'CAMERA', 'LIGHT') when "
                                                                                   "target is 'scene'."},
                                                    'depth': {'type': 'integer',
                                                              'default': 3,
                                                              'description': 'Max collection recursion depth '
                                                                             "for 'scene' hierarchy."}}}},
 'blender_capture': {'name': 'blender_capture',
                     'description': 'Render or take a snapshot of the current 3D viewport or camera view. '
                                    'Supports transparent film (alpha PNG), shading mode selection, custom '
                                    'camera targeting, and directly returns Base64 PNG image content for '
                                    'vision LLMs.',
                     'inputSchema': {'type': 'object',
                                     'properties': {'view': {'type': 'string',
                                                             'enum': ['camera', 'viewport'],
                                                             'default': 'camera',
                                                             'description': "Which view to render: 'camera' "
                                                                            '(active scene camera) or '
                                                                            "'viewport' (interactive 3D "
                                                                            'viewport angle).'},
                                                    'shading_type': {'type': 'string',
                                                                     'description': 'Viewport shading mode '
                                                                                    '(live enum: '
                                                                                    "blender_describe(target='struct', "
                                                                                    "path='View3DShading.type'))."},
                                                    'film_transparent': {'type': 'boolean',
                                                                         'description': 'Whether to render '
                                                                                        'with transparent '
                                                                                        'background (useful '
                                                                                        'for sprites, asset '
                                                                                        'cutouts, and '
                                                                                        'product renders).'},
                                                    'camera': {'type': 'string',
                                                               'description': 'Optional specific camera '
                                                                              'object name to render from '
                                                                              "when view is 'camera'."},
                                                    'resolution': {'type': 'array',
                                                                   'items': {'type': 'integer'},
                                                                   'minItems': 2,
                                                                   'maxItems': 2,
                                                                   'default': [800, 600],
                                                                   'description': 'Image resolution [width, '
                                                                                  'height].'},
                                                    'return_image': {'type': 'boolean',
                                                                     'default': True,
                                                                     'description': 'Whether to return image '
                                                                                    'content directly in MCP '
                                                                                    'response (Base64 PNG) '
                                                                                    'for vision LLMs.'},
                                                    'output_path': {'type': 'string',
                                                                    'description': 'Optional file path to '
                                                                                   'save the rendered PNG '
                                                                                   'image to disk.'},
                                                    'scene': {'type': 'string',
                                                              'description': 'Optional scene name to render '
                                                                             '(defaults to active scene).'},
                                                    'view_layer': {'type': 'string',
                                                                   'description': 'Optional view layer name '
                                                                                  'to render within the scene.'}}}},
 'blender_manage_modifier': {'name': 'blender_manage_modifier',
                             'description': 'Full-stack adaptive modifier tool for Blender: search the live '
                                            "modifier catalog, introspect RNA properties ('query_type'), "
                                            "inspect object modifier stacks ('inspect'), add, configure, "
                                            'apply, or remove modifiers with automatic pointer resolution '
                                            '(objects, collections, node groups).',
                             'inputSchema': {'type': 'object',
                                             'required': ['action'],
                                             'properties': {'action': {'type': 'string',
                                                                       'enum': ['search',
                                                                                'query_type',
                                                                                'inspect',
                                                                                'add',
                                                                                'configure',
                                                                                'apply',
                                                                                'remove'],
                                                                       'description': 'Modifier action: '
                                                                                      "'search' (catalog "
                                                                                      "search), 'query_type' "
                                                                                      '(introspect modifier '
                                                                                      'RNA properties & '
                                                                                      'valid enums), '
                                                                                      "'inspect' (list all "
                                                                                      'modifiers on object), '
                                                                                      "'add', 'configure', "
                                                                                      "'apply', or "
                                                                                      "'remove'."},
                                                            'object_name': {'type': 'string',
                                                                            'description': 'Target object '
                                                                                           'name. Required '
                                                                                           "for 'add', "
                                                                                           "'configure', "
                                                                                           "'apply', "
                                                                                           "'remove', and "
                                                                                           "'inspect'."},
                                                            'modifier_type': {'type': 'string',
                                                                              'description': 'Modifier type '
                                                                                             'identifier '
                                                                                             '(e.g. '
                                                                                             "'SUBSURF', "
                                                                                             "'BOOLEAN', "
                                                                                             "'NODES', "
                                                                                             "'BEVEL', "
                                                                                             "'MIRROR', "
                                                                                             "'SOLIDIFY', "
                                                                                             "'WEIGHTED_NORMAL', "
                                                                                             "'SHRINKWRAP', "
                                                                                             "'ARRAY', "
                                                                                             "'REMESH', "
                                                                                             "'DECIMATE', "
                                                                                             'etc.). '
                                                                                             'Required for '
                                                                                             "'add' and "
                                                                                             "'query_type'."},
                                                            'modifier_name': {'type': 'string',
                                                                              'description': 'Specific '
                                                                                             'modifier name '
                                                                                             '(required for '
                                                                                             "'apply'/'remove' "
                                                                                             'if multiple '
                                                                                             'exist, or '
                                                                                             'optional '
                                                                                             'custom name '
                                                                                             "for 'add')."},
                                                            'query': {'type': 'string',
                                                                      'description': 'Keyword to filter '
                                                                                     "modifiers in 'search' "
                                                                                     'action.'},
                                                            'properties': {'type': 'object',
                                                                           'description': 'Key-value '
                                                                                          'properties to set '
                                                                                          'on modifier (e.g. '
                                                                                          "{'levels': 2, "
                                                                                          "'solver': "
                                                                                          "'MANIFOLD', "
                                                                                          "'operation': "
                                                                                          "'DIFFERENCE', "
                                                                                          "'object': "
                                                                                          "'Cutter', "
                                                                                          "'node_group': "
                                                                                          "'MyGeometryNodes'}). "
                                                                                          'Pointer '
                                                                                          'properties '
                                                                                          '(Object, '
                                                                                          'Collection, '
                                                                                          'NodeTree) are '
                                                                                          'resolved '
                                                                                          'automatically.'}}}},
 'blender_manage_nodes': {'name': 'blender_manage_nodes',
                          'description': 'Unified Node Graph DAG tool for Blender: search, inspect, query, '
                                         'build, and wire Shader Nodes (materials, world, lights, line '
                                         'styles), Geometry Nodes (procedural modeling), and Compositor '
                                         'Nodes using declarative JSON without code.',
                          'inputSchema': {'type': 'object',
                                          'properties': {'tree_type': {'type': 'string',
                                                                       'enum': ['MATERIAL',
                                                                                'GEOMETRY',
                                                                                'COMPOSITING',
                                                                                'WORLD',
                                                                                'LINESTYLE',
                                                                                'LIGHT',
                                                                                'NODEGROUP'],
                                                                       'default': 'MATERIAL',
                                                                       'description': 'Which node tree to '
                                                                                      "target: 'MATERIAL' "
                                                                                      '(shader graph), '
                                                                                      "'GEOMETRY' (geometry "
                                                                                      'nodes procedural '
                                                                                      'modeling), '
                                                                                      "'COMPOSITING' "
                                                                                      '(post-processing), '
                                                                                      "'WORLD' (environment "
                                                                                      "shader), 'LINESTYLE' "
                                                                                      '(freestyle line '
                                                                                      "style), 'LIGHT' (lamp "
                                                                                      'shader), or '
                                                                                      "'NODEGROUP' (direct "
                                                                                      'node group by name).'},
                                                         'target': {'type': 'string',
                                                                    'description': 'Target name: object '
                                                                                   'name, material name, '
                                                                                   'world name, linestyle '
                                                                                   'name, or node group '
                                                                                   'name.'},
                                                         'action': {'type': 'string',
                                                                    'enum': ['search',
                                                                             'inspect',
                                                                             'query_type',
                                                                             'apply_dag',
                                                                             'remove_nodes',
                                                                             'disconnect'],
                                                                    'default': 'inspect',
                                                                    'description': 'Action to perform: '
                                                                                   "'search' (find node "
                                                                                   'types across 550+ '
                                                                                   'Blender nodes by keyword '
                                                                                   'in English or Chinese), '
                                                                                   "'inspect' (read full "
                                                                                   'node graph), '
                                                                                   "'query_type' (introspect "
                                                                                   'input/output sockets and '
                                                                                   'RNA properties of a node '
                                                                                   "type), 'apply_dag' "
                                                                                   '(declarative node '
                                                                                   'creation and link '
                                                                                   "wiring), 'remove_nodes', "
                                                                                   "or 'disconnect'."},
                                                         'query': {'type': 'string',
                                                                   'description': 'Search keyword for '
                                                                                  "'search' action (e.g. "
                                                                                  "'noise', 'extrude', "
                                                                                  "'boolean', 'blur', '噪波', "
                                                                                  "'挤出')."},
                                                         'limit': {'type': 'integer',
                                                                   'default': 15,
                                                                   'description': 'Maximum number of results '
                                                                                  "to return for 'search' "
                                                                                  'action.'},
                                                         'node_type': {'type': 'string',
                                                                       'description': 'Node bl_idname for '
                                                                                      "'query_type' (e.g. "
                                                                                      "'GeometryNodeMeshCube', "
                                                                                      "'ShaderNodeTexNoise', "
                                                                                      "'GeometryNodeExtrudeMesh')."},
                                                         'material_name': {'type': 'string',
                                                                           'description': 'Optional specific '
                                                                                          'material name '
                                                                                          'when tree_type is '
                                                                                          "'MATERIAL'."},
                                                         'modifier_name': {'type': 'string',
                                                                           'description': 'Optional geometry '
                                                                                          'nodes modifier '
                                                                                          'name when '
                                                                                          'tree_type is '
                                                                                          "'GEOMETRY'."},
                                                         'clear': {'type': 'boolean',
                                                                   'default': False,
                                                                   'description': 'Whether to clear existing '
                                                                                  'intermediate nodes before '
                                                                                  'applying DAG in '
                                                                                  "'apply_dag'."},
                                                         'nodes': {'type': 'array',
                                                                   'items': {'type': 'object',
                                                                             'required': ['type'],
                                                                             'properties': {'id': {'type': 'string',
                                                                                                   'description': 'Custom '
                                                                                                                  'node '
                                                                                                                  'identifier '
                                                                                                                  'or '
                                                                                                                  'existing '
                                                                                                                  'node '
                                                                                                                  'name.'},
                                                                                            'type': {'type': 'string',
                                                                                                     'description': 'Node '
                                                                                                                    'bl_idname '
                                                                                                                    '(e.g. '
                                                                                                                    "'ShaderNodeTexNoise', "
                                                                                                                    "'GeometryNodeMeshCube')."},
                                                                                            'location': {'type': 'array',
                                                                                                         'items': {'type': 'number'},
                                                                                                         'minItems': 2,
                                                                                                         'maxItems': 2,
                                                                                                         'description': 'Optional '
                                                                                                                        '[x, '
                                                                                                                        'y] '
                                                                                                                        'coordinates. '
                                                                                                                        'Auto-calculated '
                                                                                                                        'if '
                                                                                                                        'omitted.'},
                                                                                            'inputs': {'type': 'object',
                                                                                                       'description': 'Key-value '
                                                                                                                      'input '
                                                                                                                      'socket '
                                                                                                                      'defaults '
                                                                                                                      '(e.g. '
                                                                                                                      "{'Scale': "
                                                                                                                      '10.0, '
                                                                                                                      "'Base "
                                                                                                                      "Color': "
                                                                                                                      "'#FF5500', "
                                                                                                                      "'Material': "
                                                                                                                      "'Gold'})."},
                                                                                            'properties': {'type': 'object',
                                                                                                           'description': 'Key-value '
                                                                                                                          'node '
                                                                                                                          'properties '
                                                                                                                          '(e.g. '
                                                                                                                          "{'operation': "
                                                                                                                          "'MULTIPLY'})."}}},
                                                                   'description': 'List of nodes to create '
                                                                                  'or configure in '
                                                                                  "'apply_dag'."},
                                                         'links': {'type': 'array',
                                                                   'items': {'type': 'object',
                                                                             'required': ['from', 'to'],
                                                                             'properties': {'from': {'type': 'string',
                                                                                                     'description': 'Source '
                                                                                                                    'socket: '
                                                                                                                    "'node_id.SocketName' "
                                                                                                                    '(e.g. '
                                                                                                                    "'noise.Color')."},
                                                                                            'to': {'type': 'string',
                                                                                                   'description': 'Destination '
                                                                                                                  'socket: '
                                                                                                                  "'node_id.SocketName' "
                                                                                                                  '(e.g. '
                                                                                                                  "'bsdf.Base "
                                                                                                                  "Color')."}}},
                                                                   'description': 'List of link connections '
                                                                                  "in 'apply_dag'."},
                                                         'node_ids': {'type': 'array',
                                                                      'items': {'type': 'string'},
                                                                      'description': 'List of node ids to '
                                                                                     'remove in '
                                                                                     "'remove_nodes'."},
                                                         'scene': {'type': 'string',
                                                                   'description': 'Optional scene name when '
                                                                                  "tree_type is 'COMPOSITING' "
                                                                                  "or 'WORLD' (defaults to "
                                                                                  'active scene).'}}}},
 'blender_manage_hierarchy': {'name': 'blender_manage_hierarchy',
                             'description': 'Comprehensive scene hierarchy and collection management tool for '
                                            'Blender: parent and unparent objects with transform preservation '
                                            '(keep_transform), bone parenting, create/nest/reparent collections, '
                                            'move or link objects between collections, configure collection '
                                            'visibility, renderability, color tags and view-layer exclusion, and '
                                            'inspect outliner hierarchies.',
                             'inputSchema': {'type': 'object',
                                             'required': ['action'],
                                             'properties': {'action': {'type': 'string',
                                                                       'enum': ['set_parent',
                                                                                'clear_parent',
                                                                                'create_collection',
                                                                                'move_to_collection',
                                                                                'unlink_from_collection',
                                                                                'remove_collection',
                                                                                'configure_collection',
                                                                                'inspect'],
                                                                       'description': 'Hierarchy action to perform.'},
                                                            'children': {'oneOf': [{'type': 'string'},
                                                                                   {'type': 'array',
                                                                                    'items': {'type': 'string'}}],
                                                                         'description': "Child object name(s) for 'set_parent'."},
                                                            'parent': {'type': 'string',
                                                                       'description': "Parent object name for 'set_parent'."},
                                                            'parent_type': {'type': 'string',
                                                                            'default': 'OBJECT',
                                                                            'description': 'Parenting type (live RNA enum: OBJECT, ARMATURE, BONE, VERTEX, etc.).'},
                                                            'parent_bone': {'type': 'string',
                                                                            'description': "Specific bone name on parent armature when parent_type is 'BONE'."},
                                                            'objects': {'oneOf': [{'type': 'string'},
                                                                                  {'type': 'array',
                                                                                   'items': {'type': 'string'}}],
                                                                        'description': "Object name(s) for 'clear_parent', 'move_to_collection', or 'unlink_from_collection'."},
                                                            'keep_transform': {'type': 'boolean',
                                                                               'default': True,
                                                                               'description': 'Whether to maintain world transform when parenting or unparenting.'},
                                                            'collection': {'type': 'string',
                                                                           'description': 'Target or subject collection name.'},
                                                            'parent_collection': {'type': 'string',
                                                                                  'description': "Parent collection name for nesting during 'create_collection' or 'configure_collection'."},
                                                            'color_tag': {'type': 'string',
                                                                          'description': 'Collection color tag identifier (live RNA enum: NONE, COLOR_01..COLOR_08).'},
                                                            'mode': {'type': 'string',
                                                                     'enum': ['move', 'link'],
                                                                     'default': 'move',
                                                                     'description': "For 'move_to_collection': 'move' (unlink from other collections) or 'link' (keep multi-collection membership)."},
                                                            'new_name': {'type': 'string',
                                                                         'description': "New name for renaming in 'configure_collection'."},
                                                            'hide_viewport': {'type': 'boolean',
                                                                              'description': 'Set viewport visibility on collection.'},
                                                            'hide_render': {'type': 'boolean',
                                                                            'description': 'Set render visibility on collection.'},
                                                            'exclude': {'type': 'boolean',
                                                                        'description': 'Set active view layer collection exclusion.'},
                                                            'keep_objects': {'type': 'boolean',
                                                                             'default': True,
                                                                             'description': 'When removing collection, whether to preserve its objects by moving to parent collection.'},
                                                            'delete_hierarchy': {'type': 'boolean',
                                                                                  'default': False,
                                                                                  'description': 'When removing collection, whether to recursively delete child collections.'},
                                                            'target': {'type': 'string',
                                                                       'enum': ['all', 'collections', 'parents'],
                                                                       'default': 'all',
                                                                       'description': "Inspection target for 'inspect' action."},
                                                            'depth': {'type': 'integer',
                                                                      'default': 5,
                                                                      'description': "Maximum recursion depth for 'inspect' action."},
                                                            'undo': {'type': 'boolean',
                                                                     'default': True,
                                                                     'description': 'Push an undo step before applying changes.'}}}},
 'blender_execute_script': {'name': 'blender_execute_script',
                            'description': "Execute arbitrary Python code in Blender's main thread with "
                                           'pre-injected utilities (bpy, context as C, data as D, mathutils '
                                           'Vector, Matrix, Euler, Quaternion, Color, radians, degrees, pi). '
                                           'Automatically wraps execution in an Undo step, captures '
                                           'stdout/stderr, and returns result.',
                            'inputSchema': {'type': 'object',
                                            'required': ['code'],
                                            'properties': {'code': {'type': 'string',
                                                                    'description': 'Python code to execute. '
                                                                                   'Pre-injected: bpy, C, D, '
                                                                                   'math, mathutils, Vector, '
                                                                                   'Matrix, Euler, '
                                                                                   'Quaternion, Color, '
                                                                                   'radians, degrees, pi. '
                                                                                   "Assign to 'result' to "
                                                                                   'return structured data.'},
                                                           'auto_undo': {'type': 'boolean',
                                                                         'default': True,
                                                                         'description': 'Whether to '
                                                                                        'automatically push '
                                                                                        'an undo step prior '
                                                                                        'to execution.'}}}}}



# MCP safety hints per tool.
ANNOTATIONS = {
    "blender_inspect": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "blender_capture": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "blender_manage_modifier": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_manage_nodes": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_manage_hierarchy": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_execute_script": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
}


def _live(schema, name):
    """Patch Blender-owned enums from the live session."""
    props = schema.get("properties", {})
    try:
        if name == "blender_inspect":
            import bpy
            prop = bpy.types.Object.bl_rna.properties.get("type")
            if prop is not None:
                props["object_type"]["enum"] = [i.identifier for i in prop.enum_items]

        elif name == "blender_capture":
            import bpy
            prop = bpy.types.View3DShading.bl_rna.properties.get("type")
            if prop is not None:
                props["shading_type"]["enum"] = [i.identifier for i in prop.enum_items]

        elif name == "blender_manage_modifier":
            from .. import catalogs
            props["modifier_type"]["enum"] = [
                item["identifier"] for item in catalogs.modifier_types()["modifiers"]
            ]

        elif name == "blender_manage_nodes":
            props.setdefault(
                "ensure",
                {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "For 'inspect': create/initialize the tree if missing. "
                        "Default false keeps inspection read-only."
                    ),
                },
            )

        elif name == "blender_manage_hierarchy":
            import bpy
            p_prop = bpy.types.Object.bl_rna.properties.get("parent_type")
            if p_prop is not None:
                props["parent_type"]["enum"] = [i.identifier for i in p_prop.enum_items]
            c_prop = bpy.types.Collection.bl_rna.properties.get("color_tag")
            if c_prop is not None:
                props["color_tag"]["enum"] = [i.identifier for i in c_prop.enum_items]

    except Exception:
        # Introspection is best effort; the literal schema remains a fallback.
        pass
    return schema


def input_schema(name):
    schema = copy.deepcopy(TOOLS[name]["inputSchema"])
    return _live(schema, name)


def register_tool(register_fn, name, handler):
    register_fn(
        name=name,
        handler=handler,
        description=TOOLS[name]["description"],
        input_schema=lambda: input_schema(name),
        annotations=ANNOTATIONS.get(name, {}),
    )
