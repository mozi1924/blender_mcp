pub mod capture;
pub mod helper;
pub mod inspect;
pub mod material;
pub mod modifier;
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
            description: "Translate, rotate (Euler degrees), or scale an existing object. Supports absolute or relative mode, and applying transforms.".to_string(),
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
                        "description": "Euler rotation in degrees [rx, ry, rz]."
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
                    "apply_transform": {
                        "type": "boolean",
                        "default": false,
                        "description": "Whether to permanently apply location, rotation, and scale to object data."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_manage_modifier".to_string(),
            description: "Add, configure, apply, or remove modifiers (Subdivision Surface, Bevel, Boolean, Mirror, Array, Solidify, Remesh, Decimate) on an object.".to_string(),
            input_schema: json!({
                "type": "object",
                "required": ["object_name", "action"],
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "Target object name."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["add", "configure", "apply", "remove"],
                        "description": "Modifier action."
                    },
                    "modifier_type": {
                        "type": "string",
                        "enum": ["SUBSURF", "BEVEL", "BOOLEAN", "MIRROR", "ARRAY", "SOLIDIFY", "REMESH", "DECIMATE", "CURVE"],
                        "description": "Modifier type (required for 'add', optional lookup for other actions)."
                    },
                    "modifier_name": {
                        "type": "string",
                        "description": "Specific modifier name (required for 'apply'/'remove' if multiple exist)."
                    },
                    "properties": {
                        "type": "object",
                        "description": "Key-value properties to set on modifier (e.g. {'levels': 2, 'width': 0.05, 'thickness': 0.1, 'operation': 'DIFFERENCE', 'object': 'Cutter'})."
                    }
                }
            }),
        },
        ToolDefinition {
            name: "blender_manage_material".to_string(),
            description: "Create, assign, and tweak Principled BSDF material properties (color, metallic, roughness, emission, transmission) for an object.".to_string(),
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
                        "enum": ["create_and_assign", "assign_existing", "update_principled"],
                        "default": "create_and_assign",
                        "description": "Material action."
                    },
                    "material_name": {
                        "type": "string",
                        "description": "Material name to create or assign."
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
                        "enum": ["BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"],
                        "description": "Render engine: BLENDER_EEVEE_NEXT (Blender 5.x real-time) or CYCLES (path tracing)."
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
        "blender_execute_script" => script::execute_script(py, args),
        "blender_undo" => undo::undo(py, args),
        _ => ToolCallResponse::error(format!("Unknown tool: {}", name)),
    }
}
