pub mod capture;
pub mod helper;
pub mod inspect;
pub mod material;
pub mod modifier;
pub mod nodes;
pub mod primitive;
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
            description: "Unified inspection tool for Blender: inspect scene collections hierarchy, object details (transforms, dimensions, vertices, materials, modifiers), file save/library status, or datablock counts.".to_string(),
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
            description: "Render or take a snapshot of the current 3D viewport or camera view. Directly returns Base64 PNG image content for instant visual feedback, or saves to output_path.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["camera", "viewport"],
                        "default": "camera",
                        "description": "Which view to render: 'camera' (active scene camera) or 'viewport' (interactive OpenGL viewport)."
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
            description: "Create a 3D primitive object (cube, sphere, cylinder, cone, torus, plane, circle, text, curve, empty, camera, light) with transform, custom name, and target collection.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["primitive_type"],
                "properties": {
                    "primitive_type": {
                        "type": "string",
                        "enum": ["cube", "sphere", "cylinder", "cone", "torus", "plane", "circle", "text", "curve_bezier", "curve_circle", "empty", "camera", "light"],
                        "description": "Type of primitive to create."
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
                        "description": "Name of collection to place the object in. Automatically created if it doesn't exist."
                    },
                    "extra": {
                        "type": "object",
                        "description": "Extra creation parameters (e.g. {'radius': 1.0, 'depth': 2.0, 'text': 'Hello', 'light_type': 'SUN'})."
                    }
                }
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
            description: "Full-stack adaptive modifier tool for Blender: search catalog (50+ modifiers including Geometry Nodes, Weighted Normal, Subsurf, Boolean, Bevel), introspect RNA properties ('query_type'), inspect object modifier stacks ('inspect'), add, configure, apply, or remove modifiers with automatic pointer resolution (objects, collections, node groups).".to_string(),
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
                        "enum": ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"],
                        "description": "Render engine: BLENDER_EEVEE (real-time EEVEE / EEVEE Next), CYCLES (path tracing), or BLENDER_WORKBENCH."
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
            description: "Execute arbitrary Python code in Blender's main thread. Automatically wraps execution in an Undo step, captures stdout/stderr, and returns result.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["code"],
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute via bpy. Assign to 'result' to return structured data."
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
        "blender_create_primitive" => primitive::create_primitive(py, args),
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
