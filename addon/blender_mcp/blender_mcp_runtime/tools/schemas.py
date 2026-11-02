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
                                                                                   'image to disk.'}}}},
 'blender_transform_object': {'name': 'blender_transform_object',
                              'description': 'Translate, rotate (Euler degrees, quaternion, or axis-angle), '
                                             'or scale an existing object. Supports absolute or relative '
                                             'mode, fine-grained transform applying, and origin manipulation '
                                             '(geometry, bottom, cursor).',
                              'inputSchema': {'type': 'object',
                                              'required': ['name'],
                                              'properties': {'name': {'type': 'string',
                                                                      'description': 'Name of the target '
                                                                                     'object.'},
                                                             'location': {'type': 'array',
                                                                          'items': {'type': 'number'},
                                                                          'minItems': 3,
                                                                          'maxItems': 3,
                                                                          'description': 'Location [x, y, '
                                                                                         'z].'},
                                                             'rotation': {'type': 'array',
                                                                          'items': {'type': 'number'},
                                                                          'minItems': 3,
                                                                          'maxItems': 3,
                                                                          'description': 'Rotation in '
                                                                                         'degrees [rx, ry, '
                                                                                         'rz]. Automatically '
                                                                                         'adapts to object '
                                                                                         'rotation_mode '
                                                                                         '(Euler, '
                                                                                         'Quaternion, or '
                                                                                         'Axis-Angle).'},
                                                             'scale': {'type': 'array',
                                                                       'items': {'type': 'number'},
                                                                       'minItems': 3,
                                                                       'maxItems': 3,
                                                                       'description': 'Scale [sx, sy, sz].'},
                                                             'mode': {'type': 'string',
                                                                      'enum': ['absolute', 'relative'],
                                                                      'default': 'absolute',
                                                                      'description': 'Whether transforms are '
                                                                                     'absolute world '
                                                                                     'coordinates or '
                                                                                     'relative offsets.'},
                                                             'origin_to': {'type': 'string',
                                                                           'enum': ['GEOMETRY',
                                                                                    'BOTTOM',
                                                                                    'CURSOR',
                                                                                    'CENTER_OF_MASS'],
                                                                           'description': 'Set object origin '
                                                                                          "point: 'GEOMETRY' "
                                                                                          '(center of '
                                                                                          "bounds), 'BOTTOM' "
                                                                                          '(bottom center of '
                                                                                          'bounding box, '
                                                                                          'ideal for placing '
                                                                                          'objects on '
                                                                                          "floor), 'CURSOR', "
                                                                                          'or '
                                                                                          "'CENTER_OF_MASS'."},
                                                             'apply_transform': {'type': 'boolean',
                                                                                 'default': False,
                                                                                 'description': 'Whether to '
                                                                                                'permanently '
                                                                                                'apply '
                                                                                                'location, '
                                                                                                'rotation, '
                                                                                                'and scale '
                                                                                                'to object '
                                                                                                'data.'},
                                                             'apply_location': {'type': 'boolean',
                                                                                'description': 'Whether to '
                                                                                               'permanently '
                                                                                               'apply '
                                                                                               'location '
                                                                                               'only.'},
                                                             'apply_rotation': {'type': 'boolean',
                                                                                'description': 'Whether to '
                                                                                               'permanently '
                                                                                               'apply '
                                                                                               'rotation '
                                                                                               'only.'},
                                                             'apply_scale': {'type': 'boolean',
                                                                             'description': 'Whether to '
                                                                                            'permanently '
                                                                                            'apply scale '
                                                                                            'only.'}}}},
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
 'blender_manage_material': {'name': 'blender_manage_material',
                             'description': 'High-level semantic material and slot asset management for '
                                            'Blender: create and assign materials across multiple slots, '
                                            'inspect material slots, assign existing materials, and '
                                            'configure OpenPBR Principled BSDF v2 surface properties (Base '
                                            'Color, Metallic, Roughness, IOR, Coat, Sheen, Subsurface, Thin '
                                            'Film, Emission, Transmission) via dynamic socket mapping.',
                             'inputSchema': {'type': 'object',
                                             'required': ['object_name'],
                                             'properties': {'object_name': {'type': 'string',
                                                                            'description': 'Target object '
                                                                                           'name.'},
                                                            'action': {'type': 'string',
                                                                       'enum': ['create_and_assign',
                                                                                'assign_existing',
                                                                                'update_principled',
                                                                                'inspect',
                                                                                'remove_slot'],
                                                                       'default': 'create_and_assign',
                                                                       'description': 'Material action: '
                                                                                      "'create_and_assign', "
                                                                                      "'assign_existing', "
                                                                                      "'update_principled', "
                                                                                      "'inspect' (read all "
                                                                                      'slots and PBR '
                                                                                      'values), or '
                                                                                      "'remove_slot'."},
                                                            'material_name': {'type': 'string',
                                                                              'description': 'Material name '
                                                                                             'to create or '
                                                                                             'assign.'},
                                                            'slot_index': {'description': 'Target material '
                                                                                          'slot index (0, 1, '
                                                                                          '2...) or '
                                                                                          "'new'/'append' to "
                                                                                          'add a new slot to '
                                                                                          'the object.'},
                                                            'pbr_properties': {'type': 'object',
                                                                               'description': 'Arbitrary '
                                                                                              'key-value map '
                                                                                              'of Principled '
                                                                                              'BSDF socket '
                                                                                              'properties to '
                                                                                              'set (e.g. '
                                                                                              "{'coat_weight': "
                                                                                              '1.0, '
                                                                                              "'coat_roughness': "
                                                                                              "0.05, 'ior': "
                                                                                              '1.45, '
                                                                                              "'thin_film_thickness': "
                                                                                              '400.0}). '
                                                                                              'Sockets are '
                                                                                              'dynamically '
                                                                                              'matched.'},
                                                            'base_color': {'description': 'Base color: '
                                                                                          'either hex string '
                                                                                          "like '#FF5500' or "
                                                                                          '[r, g, b, a] '
                                                                                          'numbers (0.0 - '
                                                                                          '1.0).'},
                                                            'metallic': {'type': 'number',
                                                                         'minimum': 0.0,
                                                                         'maximum': 1.0,
                                                                         'description': 'Metallic value (0.0 '
                                                                                        'to 1.0).'},
                                                            'roughness': {'type': 'number',
                                                                          'minimum': 0.0,
                                                                          'maximum': 1.0,
                                                                          'description': 'Roughness value '
                                                                                         '(0.0 to 1.0).'},
                                                            'ior': {'type': 'number',
                                                                    'description': 'Index of Refraction '
                                                                                   '(IOR) for dielectric '
                                                                                   'reflection and '
                                                                                   'transmission (e.g. 1.45 '
                                                                                   'for plastics, 1.5 for '
                                                                                   'glass, 1.33 for water).'},
                                                            'coat': {'type': 'number',
                                                                     'minimum': 0.0,
                                                                     'maximum': 1.0,
                                                                     'description': 'Coat layer weight (0.0 '
                                                                                    'to 1.0) for clear coat '
                                                                                    'on car paint, lacquer, '
                                                                                    'or varnished '
                                                                                    'materials.'},
                                                            'coat_roughness': {'type': 'number',
                                                                               'minimum': 0.0,
                                                                               'maximum': 1.0,
                                                                               'description': 'Coat '
                                                                                              'roughness '
                                                                                              '(0.0 to '
                                                                                              '1.0).'},
                                                            'sheen': {'type': 'number',
                                                                      'minimum': 0.0,
                                                                      'maximum': 1.0,
                                                                      'description': 'Sheen layer weight '
                                                                                     '(0.0 to 1.0) for '
                                                                                     'cloth, velvet, or '
                                                                                     'peach fuzz.'},
                                                            'subsurface': {'type': 'number',
                                                                           'minimum': 0.0,
                                                                           'maximum': 1.0,
                                                                           'description': 'Subsurface '
                                                                                          'scattering weight '
                                                                                          '(0.0 to 1.0) for '
                                                                                          'skin, marble, '
                                                                                          'wax, or milk.'},
                                                            'thin_film': {'type': 'number',
                                                                          'description': 'Thin film '
                                                                                         'thickness in '
                                                                                         'nanometers for '
                                                                                         'iridescent soap '
                                                                                         'bubbles or oil '
                                                                                         'slicks (e.g. 400.0 '
                                                                                         '- 600.0).'},
                                                            'emission_color': {'description': 'Emission '
                                                                                              'color: hex or '
                                                                                              '[r, g, b].'},
                                                            'emission_strength': {'type': 'number',
                                                                                  'description': 'Emission '
                                                                                                 'intensity.'},
                                                            'transmission': {'type': 'number',
                                                                             'minimum': 0.0,
                                                                             'maximum': 1.0,
                                                                             'description': 'Transmission / '
                                                                                            'glass weight '
                                                                                            '(0.0 to 1.0).'},
                                                            'alpha': {'type': 'number',
                                                                      'minimum': 0.0,
                                                                      'maximum': 1.0,
                                                                      'description': 'Alpha transparency '
                                                                                     '(0.0 to 1.0).'}}}},
 'blender_setup_scene': {'name': 'blender_setup_scene',
                         'description': 'Configure camera (target look-at, focal length), lighting (type, '
                                        'power, color), render engine (EEVEE Next, Cycles), resolution, and '
                                        'world background.',
                         'inputSchema': {'type': 'object',
                                         'properties': {'camera': {'type': 'object',
                                                                   'properties': {'location': {'type': 'array',
                                                                                               'items': {'type': 'number'},
                                                                                               'minItems': 3,
                                                                                               'maxItems': 3},
                                                                                  'look_at': {'description': 'Target '
                                                                                                             'point '
                                                                                                             '[x, '
                                                                                                             'y, '
                                                                                                             'z] '
                                                                                                             'or '
                                                                                                             'target '
                                                                                                             'object '
                                                                                                             'name '
                                                                                                             'string '
                                                                                                             'to '
                                                                                                             'point '
                                                                                                             'camera '
                                                                                                             'at.'},
                                                                                  'focal_length': {'type': 'number',
                                                                                                   'description': 'Lens '
                                                                                                                  'focal '
                                                                                                                  'length '
                                                                                                                  'in '
                                                                                                                  'mm '
                                                                                                                  '(e.g. '
                                                                                                                  '50.0, '
                                                                                                                  '35.0, '
                                                                                                                  '85.0).'}}},
                                                        'light': {'type': 'object',
                                                                  'properties': {'name': {'type': 'string',
                                                                                          'default': 'KeyLight'},
                                                                                 'type': {'type': 'string',
                                                                                          'enum': ['POINT',
                                                                                                   'SUN',
                                                                                                   'SPOT',
                                                                                                   'AREA'],
                                                                                          'default': 'POINT'},
                                                                                 'location': {'type': 'array',
                                                                                              'items': {'type': 'number'},
                                                                                              'minItems': 3,
                                                                                              'maxItems': 3},
                                                                                 'energy': {'type': 'number',
                                                                                            'description': 'Light '
                                                                                                           'power '
                                                                                                           '/ '
                                                                                                           'energy '
                                                                                                           'in '
                                                                                                           'Watts.'},
                                                                                 'color': {'type': 'array',
                                                                                           'items': {'type': 'number'},
                                                                                           'minItems': 3,
                                                                                           'maxItems': 3}}},
                                                        'render_engine': {'type': 'string',
                                                                          'description': 'Render engine '
                                                                                         'identifier. Live '
                                                                                         'enum: '
                                                                                         "blender_describe(target='render_engines'). "
                                                                                         'Only engines '
                                                                                         'registered in this '
                                                                                         'session are '
                                                                                         'accepted.'},
                                                        'resolution': {'type': 'array',
                                                                       'items': {'type': 'integer'},
                                                                       'minItems': 2,
                                                                       'maxItems': 2,
                                                                       'description': 'Render resolution '
                                                                                      '[width, height].'},
                                                        'samples': {'type': 'integer',
                                                                    'description': 'Render sampling count.'},
                                                        'world_color': {'type': 'array',
                                                                        'items': {'type': 'number'},
                                                                        'minItems': 3,
                                                                        'maxItems': 3,
                                                                        'description': 'World environment '
                                                                                       'background color [r, '
                                                                                       'g, b].'}}}},
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
                                                                                     "'remove_nodes'."}}}},
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
                                                                                        'to execution.'}}}},
 'blender_undo': {'name': 'blender_undo',
                  'description': 'Undo the last operation in Blender.',
                  'inputSchema': {'type': 'object', 'properties': {}}}}



# Tool surface profiles. "core" is the orthogonal adaptive set; "full" also
# exposes compatibility wrappers that duplicate blender_run_operator/blender_set.
CORE = ("core", "full")
FULL = ("full",)

PROFILES = {
    "blender_inspect": CORE,
    "blender_capture": CORE,
    "blender_manage_modifier": CORE,
    "blender_manage_nodes": CORE,
    "blender_manage_material": CORE,
    "blender_transform_object": CORE,
    "blender_execute_script": CORE,
    "blender_setup_scene": FULL,
    "blender_undo": FULL,
}

# Deprecated compatibility wrappers and their adaptive replacements.
DEPRECATED = {
    "blender_setup_scene": (
        "blender_transform_object",
        "blender_set",
        "blender_run_operator",
    ),
    "blender_undo": ("blender_run_operator",),
}

# MCP safety hints per tool.
ANNOTATIONS = {
    "blender_inspect": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "blender_capture": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "blender_transform_object": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_manage_modifier": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_manage_material": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_setup_scene": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_manage_nodes": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "blender_execute_script": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    "blender_undo": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
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

        elif name == "blender_transform_object":
            import bpy
            fn = bpy.ops.object.origin_set
            prop = fn.get_rna_type().properties.get("type")
            values = [i.identifier for i in prop.enum_items] if prop else []
            # The tool also exposes semantic convenience values.
            for extra in ("GEOMETRY", "BOTTOM", "CURSOR", "CENTER_OF_MASS", "CENTER_OF_VOLUME"):
                if extra not in values:
                    values.append(extra)
            props["origin_to"]["enum"] = values
            props.setdefault(
                "look_at",
                {
                    "description": (
                        "Point the object at a world position [x, y, z] or an object name "
                        "(camera/look-at convenience)."
                    ),
                },
            )

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

        elif name == "blender_setup_scene":
            from .. import catalogs
            import bpy
            props["render_engine"]["enum"] = [
                item["identifier"] for item in catalogs.render_engines()["engines"]
            ]
            prop = bpy.types.Light.bl_rna.properties.get("type")
            if prop is not None:
                props["light"]["properties"]["type"]["enum"] = [
                    i.identifier for i in prop.enum_items
                ]
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
        profiles=PROFILES.get(name, CORE),
        deprecated=name in DEPRECATED,
        replaced_by=DEPRECATED.get(name),
    )
