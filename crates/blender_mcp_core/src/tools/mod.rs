pub mod adaptive;
pub mod capture;
pub mod helper;
pub mod inspect;
pub mod material;
pub mod modifier;
pub mod nodes;
pub mod scene_setup;
pub mod script;
pub mod transform;
pub mod undo;

use crate::bridge::channel::ToolCallResponse;
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: serde_json::Value,
}

pub fn get_tool_definitions() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "blender_inspect".to_string(),
            description: "Unified inspection tool for Blender: inspect scene metadata (active camera, render engine, frame range, FPS, resolution, AgX view transform, units, collection hierarchy), deep object details (transforms, mesh stats, camera optics/DOF, light parameters, curves/hair, grease pencil v3, armature bones, slotted actions/animation, full modifier stacks, material slots, custom properties), blend file libraries/status, or comprehensive datablock counts.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["scene", "object", "file", "datablocks"],
                        "default": "scene",
                        "description": "What to inspect: 'scene' (collection hierarchy & active state), 'object' (deep object details), 'file' (filepath, saved status, missing files), or 'datablocks' (counts of meshes, materials, etc.)."
                    },
                    "name": {
                        "type": "string",
                        "description": "Object name to inspect. Required when target is 'object'."
                    },
                    "collection": {
                        "type": "string",
                        "description": "Optional collection name to filter inspection when target is 'scene'."
                    },
                    "object_type": {
                        "type": "string",
                        "description": "Optional object type filter (e.g. 'MESH', 'CAMERA', 'LIGHT') when target is 'scene'."
                    },
                    "depth": {
                        "type": "integer",
                        "default": 3,
                        "description": "Max collection recursion depth for 'scene' hierarchy."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_capture".to_string(),
            description: "Render or take a snapshot of the current 3D viewport or camera view. Supports transparent film (alpha PNG), shading mode selection, custom camera targeting, and directly returns Base64 PNG image content for vision LLMs.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["camera", "viewport"],
                        "default": "camera",
                        "description": "Which view to render: 'camera' (active scene camera) or 'viewport' (interactive 3D viewport angle)."
                    },
                    "shading_type": {
                        "type": "string",
                        "description": "Viewport shading mode (live enum: blender_describe(target='struct', path='View3DShading.type'))."
                    },
                    "film_transparent": {
                        "type": "boolean",
                        "description": "Whether to render with transparent background (useful for sprites, asset cutouts, and product renders)."
                    },
                    "camera": {
                        "type": "string",
                        "description": "Optional specific camera object name to render from when view is 'camera'."
                    },
                    "resolution": {
                        "type": "array",
                        "items": { "type": "integer" },
                        "minItems": 2,
                        "maxItems": 2,
                        "default": [800, 600],
                        "description": "Image resolution [width, height]."
                    },
                    "return_image": {
                        "type": "boolean",
                        "default": true,
                        "description": "Whether to return image content directly in MCP response (Base64 PNG) for vision LLMs."
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional file path to save the rendered PNG image to disk."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_create_primitive".to_string(),
            description: "Adaptive primitive creation. 'primitive_type' is a semantic alias (cube, sphere, ico_sphere, cylinder, cone, torus, plane, circle, grid, monkey, text, curve_bezier, curve_circle, empty, camera, light, or any operator-derived kind). All geometric parameters are validated against the live creation operator RNA, so new Blender parameters work without updating this tool. Use blender_describe(target='primitives') to list kinds and blender_describe(target='operator', path=...) for the full parameter schema.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "primitive_type": {
                        "type": "string",
                        "description": "Semantic kind (live list: blender_describe(target='primitives'))."
                    },
                    "operator": {
                        "type": "string",
                        "description": "Explicit creation operator, e.g. 'mesh.primitive_grid_add'. Overrides primitive_type."
                    },
                    "name": {
                        "type": "string",
                        "description": "Custom name for the newly created object."
                    },
                    "location": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "default": [0.0, 0.0, 0.0],
                        "description": "World location [x, y, z]."
                    },
                    "rotation": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "default": [0.0, 0.0, 0.0],
                        "description": "Euler rotation in degrees [rx, ry, rz]."
                    },
                    "scale": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "default": [1.0, 1.0, 1.0],
                        "description": "Scale [sx, sy, sz]."
                    },
                    "collection": {
                        "type": "string",
                        "description": "Target collection; created automatically if missing."
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Operator-specific RNA parameters, e.g. {'radius': 1.5, 'segments': 48}. Unknown keys are rejected with suggestions."
                    },
                    "extra": {
                        "type": "object",
                        "description": "Deprecated alias for 'parameters'."
                    },
                    "undo": { "type": "boolean", "default": true }
                },
                "anyOf": [{ "required": ["primitive_type"] }, { "required": ["operator"] }]
            }),
        },
        ToolDefinition {
            name: "blender_transform_object".to_string(),
            description: "Translate, rotate (Euler degrees, quaternion, or axis-angle), or scale an existing object. Supports absolute or relative mode, fine-grained transform applying, and origin manipulation (geometry, bottom, cursor).".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the target object."
                    },
                    "location": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "Location [x, y, z]."
                    },
                    "rotation": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "Rotation in degrees [rx, ry, rz]. Automatically adapts to object rotation_mode (Euler, Quaternion, or Axis-Angle)."
                    },
                    "scale": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "Scale [sx, sy, sz]."
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["absolute", "relative"],
                        "default": "absolute",
                        "description": "Whether transforms are absolute world coordinates or relative offsets."
                    },
                    "origin_to": {
                        "type": "string",
                        "enum": ["GEOMETRY", "BOTTOM", "CURSOR", "CENTER_OF_MASS"],
                        "description": "Set object origin point: 'GEOMETRY' (center of bounds), 'BOTTOM' (bottom center of bounding box, ideal for placing objects on floor), 'CURSOR', or 'CENTER_OF_MASS'."
                    },
                    "apply_transform": {
                        "type": "boolean",
                        "default": false,
                        "description": "Whether to permanently apply location, rotation, and scale to object data."
                    },
                    "apply_location": {
                        "type": "boolean",
                        "description": "Whether to permanently apply location only."
                    },
                    "apply_rotation": {
                        "type": "boolean",
                        "description": "Whether to permanently apply rotation only."
                    },
                    "apply_scale": {
                        "type": "boolean",
                        "description": "Whether to permanently apply scale only."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_manage_modifier".to_string(),
            description: "Full-stack adaptive modifier tool for Blender: search the live modifier catalog, introspect RNA properties ('query_type'), inspect object modifier stacks ('inspect'), add, configure, apply, or remove modifiers with automatic pointer resolution (objects, collections, node groups).".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "query_type", "inspect", "add", "configure", "apply", "remove"],
                        "description": "Modifier action: 'search' (catalog search), 'query_type' (introspect modifier RNA properties & valid enums), 'inspect' (list all modifiers on object), 'add', 'configure', 'apply', or 'remove'."
                    },
                    "object_name": {
                        "type": "string",
                        "description": "Target object name. Required for 'add', 'configure', 'apply', 'remove', and 'inspect'."
                    },
                    "modifier_type": {
                        "type": "string",
                        "description": "Modifier type identifier (e.g. 'SUBSURF', 'BOOLEAN', 'NODES', 'BEVEL', 'MIRROR', 'SOLIDIFY', 'WEIGHTED_NORMAL', 'SHRINKWRAP', 'ARRAY', 'REMESH', 'DECIMATE', etc.). Required for 'add' and 'query_type'."
                    },
                    "modifier_name": {
                        "type": "string",
                        "description": "Specific modifier name (required for 'apply'/'remove' if multiple exist, or optional custom name for 'add')."
                    },
                    "query": {
                        "type": "string",
                        "description": "Keyword to filter modifiers in 'search' action."
                    },
                    "properties": {
                        "type": "object",
                        "description": "Key-value properties to set on modifier (e.g. {'levels': 2, 'solver': 'MANIFOLD', 'operation': 'DIFFERENCE', 'object': 'Cutter', 'node_group': 'MyGeometryNodes'}). Pointer properties (Object, Collection, NodeTree) are resolved automatically."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_manage_material".to_string(),
            description: "High-level semantic material and slot asset management for Blender: create and assign materials across multiple slots, inspect material slots, assign existing materials, and configure OpenPBR Principled BSDF v2 surface properties (Base Color, Metallic, Roughness, IOR, Coat, Sheen, Subsurface, Thin Film, Emission, Transmission) via dynamic socket mapping.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["object_name"],
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "Target object name."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["create_and_assign", "assign_existing", "update_principled", "inspect", "remove_slot"],
                        "default": "create_and_assign",
                        "description": "Material action: 'create_and_assign', 'assign_existing', 'update_principled', 'inspect' (read all slots and PBR values), or 'remove_slot'."
                    },
                    "material_name": {
                        "type": "string",
                        "description": "Material name to create or assign."
                    },
                    "slot_index": {
                        "description": "Target material slot index (0, 1, 2...) or 'new'/'append' to add a new slot to the object."
                    },
                    "pbr_properties": {
                        "type": "object",
                        "description": "Arbitrary key-value map of Principled BSDF socket properties to set (e.g. {'coat_weight': 1.0, 'coat_roughness': 0.05, 'ior': 1.45, 'thin_film_thickness': 400.0}). Sockets are dynamically matched."
                    },
                    "base_color": {
                        "description": "Base color: either hex string like '#FF5500' or [r, g, b, a] numbers (0.0 - 1.0)."
                    },
                    "metallic": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Metallic value (0.0 to 1.0)."
                    },
                    "roughness": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Roughness value (0.0 to 1.0)."
                    },
                    "ior": {
                        "type": "number",
                        "description": "Index of Refraction (IOR) for dielectric reflection and transmission (e.g. 1.45 for plastics, 1.5 for glass, 1.33 for water)."
                    },
                    "coat": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Coat layer weight (0.0 to 1.0) for clear coat on car paint, lacquer, or varnished materials."
                    },
                    "coat_roughness": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Coat roughness (0.0 to 1.0)."
                    },
                    "sheen": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Sheen layer weight (0.0 to 1.0) for cloth, velvet, or peach fuzz."
                    },
                    "subsurface": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Subsurface scattering weight (0.0 to 1.0) for skin, marble, wax, or milk."
                    },
                    "thin_film": {
                        "type": "number",
                        "description": "Thin film thickness in nanometers for iridescent soap bubbles or oil slicks (e.g. 400.0 - 600.0)."
                    },
                    "emission_color": {
                        "description": "Emission color: hex or [r, g, b]."
                    },
                    "emission_strength": {
                        "type": "number",
                        "description": "Emission intensity."
                    },
                    "transmission": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Transmission / glass weight (0.0 to 1.0)."
                    },
                    "alpha": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Alpha transparency (0.0 to 1.0)."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_setup_scene".to_string(),
            description: "Configure camera (target look-at, focal length), lighting (type, power, color), render engine (EEVEE Next, Cycles), resolution, and world background.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "camera": {
                        "type": "object",
                        "properties": {
                            "location": { "type": "array", "items": { "type": "number" }, "minItems": 3, "maxItems": 3 },
                            "look_at": { "description": "Target point [x, y, z] or target object name string to point camera at." },
                            "focal_length": { "type": "number", "description": "Lens focal length in mm (e.g. 50.0, 35.0, 85.0)." }
                        }
                    },
                    "light": {
                        "type": "object",
                        "properties": {
                            "name": { "type": "string", "default": "KeyLight" },
                            "type": { "type": "string", "enum": ["POINT", "SUN", "SPOT", "AREA"], "default": "POINT" },
                            "location": { "type": "array", "items": { "type": "number" }, "minItems": 3, "maxItems": 3 },
                            "energy": { "type": "number", "description": "Light power / energy in Watts." },
                            "color": { "type": "array", "items": { "type": "number" }, "minItems": 3, "maxItems": 3 }
                        }
                    },
                    "render_engine": {
                        "type": "string",
                        "description": "Render engine identifier. Live enum: blender_describe(target='render_engines'). Only engines registered in this session are accepted."
                    },
                    "resolution": {
                        "type": "array",
                        "items": { "type": "integer" },
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Render resolution [width, height]."
                    },
                    "samples": {
                        "type": "integer",
                        "description": "Render sampling count."
                    },
                    "world_color": {
                        "type": "array",
                        "items": { "type": "number" },
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "World environment background color [r, g, b]."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_execute_script".to_string(),
            description: "Execute arbitrary Python code in Blender's main thread with pre-injected utilities (bpy, context as C, data as D, mathutils Vector, Matrix, Euler, Quaternion, Color, radians, degrees, pi). Automatically wraps execution in an Undo step, captures stdout/stderr, and returns result.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["code"],
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Pre-injected: bpy, C, D, math, mathutils, Vector, Matrix, Euler, Quaternion, Color, radians, degrees, pi. Assign to 'result' to return structured data."
                    },
                    "auto_undo": {
                        "type": "boolean",
                        "default": true,
                        "description": "Whether to automatically push an undo step prior to execution."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_manage_nodes".to_string(),
            description: "Unified Node Graph DAG tool for Blender: search, inspect, query, build, and wire Shader Nodes (materials, world, lights, line styles), Geometry Nodes (procedural modeling), and Compositor Nodes using declarative JSON without code.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "tree_type": {
                        "type": "string",
                        "enum": ["MATERIAL", "GEOMETRY", "COMPOSITING", "WORLD", "LINESTYLE", "LIGHT", "NODEGROUP"],
                        "default": "MATERIAL",
                        "description": "Which node tree to target: 'MATERIAL' (shader graph), 'GEOMETRY' (geometry nodes procedural modeling), 'COMPOSITING' (post-processing), 'WORLD' (environment shader), 'LINESTYLE' (freestyle line style), 'LIGHT' (lamp shader), or 'NODEGROUP' (direct node group by name)."
                    },
                    "target": {
                        "type": "string",
                        "description": "Target name: object name, material name, world name, linestyle name, or node group name."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["search", "inspect", "query_type", "apply_dag", "remove_nodes", "disconnect"],
                        "default": "inspect",
                        "description": "Action to perform: 'search' (find node types across 550+ Blender nodes by keyword in English or Chinese), 'inspect' (read full node graph), 'query_type' (introspect input/output sockets and RNA properties of a node type), 'apply_dag' (declarative node creation and link wiring), 'remove_nodes', or 'disconnect'."
                    },
                    "query": {
                        "type": "string",
                        "description": "Search keyword for 'search' action (e.g. 'noise', 'extrude', 'boolean', 'blur', '噪波', '挤出')."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 15,
                        "description": "Maximum number of results to return for 'search' action."
                    },
                    "node_type": {
                        "type": "string",
                        "description": "Node bl_idname for 'query_type' (e.g. 'GeometryNodeMeshCube', 'ShaderNodeTexNoise', 'GeometryNodeExtrudeMesh')."
                    },
                    "material_name": {
                        "type": "string",
                        "description": "Optional specific material name when tree_type is 'MATERIAL'."
                    },
                    "modifier_name": {
                        "type": "string",
                        "description": "Optional geometry nodes modifier name when tree_type is 'GEOMETRY'."
                    },
                    "clear": {
                        "type": "boolean",
                        "default": false,
                        "description": "Whether to clear existing intermediate nodes before applying DAG in 'apply_dag'."
                    },
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "id": { "type": "string", "description": "Custom node identifier or existing node name." },
                                "type": { "type": "string", "description": "Node bl_idname (e.g. 'ShaderNodeTexNoise', 'GeometryNodeMeshCube')." },
                                "location": { "type": "array", "items": { "type": "number" }, "minItems": 2, "maxItems": 2, "description": "Optional [x, y] coordinates. Auto-calculated if omitted." },
                                "inputs": { "type": "object", "description": "Key-value input socket defaults (e.g. {'Scale': 10.0, 'Base Color': '#FF5500', 'Material': 'Gold'})." },
                                "properties": { "type": "object", "description": "Key-value node properties (e.g. {'operation': 'MULTIPLY'})." }
                            }
                        },
                        "description": "List of nodes to create or configure in 'apply_dag'."
                    },
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["from", "to"],
                            "properties": {
                                "from": { "type": "string", "description": "Source socket: 'node_id.SocketName' (e.g. 'noise.Color')." },
                                "to": { "type": "string", "description": "Destination socket: 'node_id.SocketName' (e.g. 'bsdf.Base Color')." }
                            }
                        },
                        "description": "List of link connections in 'apply_dag'."
                    },
                    "node_ids": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "List of node ids to remove in 'remove_nodes'."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_describe".to_string(),
            description: "Adaptive introspection of Blender's live RNA: operator/modifier/node parameters, enum identifiers, defaults, ranges, valid node tree types, render engines and primitive kinds. Use this before guessing any parameter name or enum value.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["target"],
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["operator", "operators", "struct", "property", "modifier_types", "modifier", "node_types", "node", "primitives", "render_engines", "id_types", "tool_schemas", "refresh"],
                        "description": "What to introspect."
                    },
                    "path": {
                        "type": "string",
                        "description": "Operator path ('mesh.primitive_cube_add'), struct ('Object') or struct property ('RenderSettings.engine')."
                    },
                    "property": { "type": "string" },
                    "modifier_type": { "type": "string" },
                    "node_type": { "type": "string" },
                    "tree_type": { "type": "string" },
                    "query": { "type": "string" },
                    "module": { "type": "string" },
                    "prefix": { "type": "string" },
                    "limit": { "type": "integer", "default": 50, "minimum": 1, "maximum": 500 }
                }
            }),
        },
        ToolDefinition {
            name: "blender_run_operator".to_string(),
            description: "Run ANY Blender operator by path (e.g. 'object.shade_smooth', 'mesh.primitive_grid_add'). Parameters are validated and coerced against the operator's live RNA; unknown keys are rejected with suggestions, enums accept identifiers or display names, and datablock pointers accept names. Use blender_describe(target='operator') first to discover parameters.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["operator"],
                "properties": {
                    "operator": { "type": "string", "description": "Operator path, e.g. 'mesh.primitive_ico_sphere_add'." },
                    "parameters": { "type": "object", "description": "Operator RNA parameters." },
                    "undo": { "type": "boolean", "default": true },
                    "select": {
                        "oneOf": [{ "type": "string" }, { "type": "array", "items": { "type": "string" } }]
                    },
                    "active": { "type": "string" },
                    "context": { "type": "object" }
                }
            }),
        },
        ToolDefinition {
            name: "blender_undo".to_string(),
            description: "Undo the last operation in Blender.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {}
            }),
        },
    ]
}

pub fn execute_tool(py: Python<'_>, name: &str, args: serde_json::Value) -> ToolCallResponse {
    match name {
        "blender_inspect" => inspect::inspect(py, args),
        "blender_capture" => capture::capture(py, args),
        // Adaptive path: primitive creation is driven by operator RNA.
        "blender_create_primitive" => adaptive::create_primitive(py, args),
        "blender_describe" => adaptive::describe(py, args),
        "blender_run_operator" => adaptive::run_operator(py, args),
        // Internal: live tool catalog for tools/list.
        "__list_tools__" => adaptive::list_tools_response(py),
        "blender_transform_object" => transform::transform_object(py, args),
        "blender_manage_modifier" => modifier::manage_modifier(py, args),
        "blender_manage_material" => material::manage_material(py, args),
        "blender_setup_scene" => scene_setup::setup_scene(py, args),
        "blender_manage_nodes" => nodes::manage_nodes(py, args),
        "blender_execute_script" => script::execute_script(py, args),
        "blender_undo" => undo::undo(py, args),
        _ => ToolCallResponse::error(format!("Unknown tool: {}", name)),
    }
}
