# GEMINI.md - Blender MCP (Rust Core + Python Adaptive Runtime) 架构与开发规范

本文档是 `blender_mcp` 工作区的核心架构准则与开发铁律。全局通用开发规范与 CLI 工具偏好遵循用户全局规则。

---

## 1. 项目定位与协同拓扑

- **本工作区职责**：基于 **Blender 5.1+** 原生扩展体系的高性能、内嵌式 MCP (Model Context Protocol) 服务端。
- **目标宿主**：Blender 5.1+（当前基准环境：`Blender 5.2.3 LTS`，最低要求 `blender_version_min = "5.1.0"`）。
- **权威源码事实源 (SSOT)**：`/Volumes/Data/code_projects/mtk/blender`（当前分支 `blender-v5.2-release`）。
- **技术栈拓扑**：
  1. **Rust 原生核心 (`crates/blender_mcp_core`)**：PyO3 cdylib (`blender_mcp_core.so`)，提供嵌入式 Tokio / Axum 异步 HTTP & SSE 服务（支持 Streamable HTTP / JSON-RPC 2.0），负责主线程非阻塞无锁通道调度 (`bridge`)、Panic 隔离与协议信封包装。
  2. **Python 自适应运行时 (`addon/blender_mcp/blender_mcp_runtime`)**：常驻内存的单例运行时，依托 Blender **RNA** 深度内省体系实现 9 大收敛工具的动态自适应、参数反射、属性路径解析与执行。

---

## 2. 核心架构规约与铁律 (Golden Rules)

### 规则 1：工具层零硬编码与 RNA 势能自适应 (Zero Hardcoding & RNA-Driven Adaptivity)
> [!IMPORTANT]
> **开发核心第一铁律：严禁在工具与协议层内硬编码任何 Blender 业务实体！**
- **严禁硬编码的内容包括但不限于**：
  - 修改器类型名称与枚举列表（如 `SUBSURF`, `BOOLEAN`, `ARRAY` 等）；
  - 材质节点类型、着色器插槽名称、几何节点套件名称；
  - 操作符参数名、类型、默认值与有效取值范围；
  - 渲染引擎名称、数据块类型、物体几何图元类型；
  - 任何随 Blender 版本迭代而变动的属性枚举。
- **必须通过 RNA 动态自适应**：
  - 工具的入参 Schema、属性校验、可用性探测必须完全基于 `bpy.types.*.bl_rna`、`RNA_access` 及其衍生元数据实时反射生成；
  - 依托 `blender_mcp_runtime.rna` 与 `blender_mcp_runtime.catalogs`，在运行时查询当前 Blender 实例的实时可用项；
  - 当 Blender 新增一个修改器、节点类型或操作符参数时，插件必须做到**零代码修改即可天然支持**。

### 规则 2：Blender 本地源码唯一事实源与严禁硬猜 (Blender Source Code as SSOT - Zero Guessing)
> [!IMPORTANT]
> **开发核心第二铁律：凡有未知或不确定，直接去查阅 Blender 源码，严禁凭空硬猜或使用旧版过时代码！**
- **源码检索绝对路径**：`/Volumes/Data/code_projects/mtk/blender`（当前分支为 `blender-v5.2-release`）。
- **查阅规范**：
  - 遇到未知 API、属性结构、数据拓扑、操作符内部调用或行为歧义时，**严禁猜测、硬试或参考网络过时教程**；
  - 必须直接使用 `rg` 检索本地 Blender 源码中的 RNA 定义、DNA 结构或 C++ 算子实现；
  - 确认底层真实语义（例如属性是属于 Object 还是 Mesh、枚举项的标识符到底是小写还是大写、特定上下文需要哪些预设条件等）后再编写代码。

### 规则 3：严格面向 Blender 5.1+ 现代化语义 (Strictly Blender 5.1+ Modern Standards)
- **严禁使用旧版已弃用或过渡期实现**：
  - 严禁使用任何 Blender 2.8x / 3.x / 4.x 的历史弃用模式；
  - **材质节点树**：严禁使用 `mat.use_nodes = True`（5.x 弃用警告，6.0 移除），直接操作 `mat.node_tree`；
  - **混合节点**：严禁使用 `ShaderNodeMixRGB`，必须统一使用现代 `ShaderNodeMix`（并根据数据类型正确指定 `data_type='RGBA'` 等）；
  - **上下文与活动物体**：严格遵循现代化上下文与 ViewLayer 体系（`context.view_layer.objects.active` 与 `context.active_object`）；
  - **几何节点系统**：拥抱 5.x 现代几何节点与节点工具规范（Repeat Zone、Bundle Sockets、Matrix Sockets 等现代化特性）。
- **Manifest 规范**：扩展配置严格遵循 `blender_manifest.toml` 现代化扩展包标准，不再依赖旧版 `bl_info` 字典。

### 规则 4：Transport-Only Rust 架构边界 (Transport-Only Rust Policy)
- **Rust 层的职责边界**：
  - Rust 层（`blender_mcp_core`）必须保持纯粹的高性能通信与跨线程调度管道角色；
  - 严禁在 Rust 层中编写任何具体的 Blender 业务逻辑或维护私有工具模式；
  - 工具列表（`tools/list`）与工具调用（`tools/call`）通过 `tools/runtime.rs` 直接动态向 Python 运行时物化与派发；
- **内存安全与 Panic 隔离**：
  - 主线程调度通道中必须严密防护 `catch_unwind` 与 GIL 同步；
  - 胶水层严禁滥用 `.unwrap()` / `.expect()` 导致宿主进程崩溃，统一通过 `Result` 冒泡转化为标准的 JSON-RPC 2.0 错误响应。

### 规则 5：九大收敛工具矩阵与收敛边界 (The 9 Consolidated Tools)
- 工作区工具层严格收敛为以下 9 个通用、自适应工具，**坚决杜绝工具膨胀与历史冗余工具回潮**：
  1. `blender_describe`：自适应内省之眼。动态查询实时 operator、struct、property、modifier_types、node_types、render_engines、id_types 等 RNA 元数据。
  2. `blender_inspect`：统一只读探测器。检查场景层级（`scene`）、物体拓扑（`object`）、工程文件（`file`）、数据块计数（`datablocks`）。
  3. `blender_run_operator`：自适应算子执行器。执行任意 `bpy.ops` 操作符，具备动态 RNA 参数校验与强制转换；统一吸收语义图元创建与后处理变换（位置、旋转、缩放、材质命名、集合收敛）。
  4. `blender_set`：泛型 RNA 属性写入器。通过通用路径解析器（`object:...`, `modifier:...`, `material:...`, `scene...`）递归定位并赋值，支持相对变换、目标朝向（`look_at`）与角度旋转。
  5. `blender_manage_modifier`：修改器生命周期管理。基于实时修改器 RNA 目录完成修改器的增加、配置、应用与移除。
  6. `blender_manage_nodes`：多类型节点树管理。统一管理 Shader、Geometry、Compositor、World 节点树，插槽与连线探测基于实时树类型校验。
  7. `blender_manage_hierarchy`：场景与集合层级管理。负责物体父子级关系（含变换保持与骨骼挂载）、集合创建/嵌套/重命名、物体在集合间的移动/链接、视图层排除与可见性控制。
  8. `blender_capture`：多模态视觉反馈。支持相机与视口抓取，返回 Base64 编码的无损 PNG 图像。
  9. `blender_execute_script`：脚本沙箱执行。具备自动 Undo 恢复保护、执行耗时统计与标准流（stdout/stderr）重定向捕获。
- **已物理剔除的旧工具红线**：
  - 严禁重新引入已废弃的单功能工具：`blender_create_primitive`、`blender_transform_object`、`blender_manage_material`、`blender_setup_scene`、`blender_undo`。

### 规则 6：单模块驻留与元数据缓存治理 (Single Instance & Cache Lifecycle)
- `addon/blender_mcp/blender_mcp_runtime` 在首次被导入后常驻于 Python `sys.modules`，严禁通过每次调用 `PyModule::from_code` 造成无界重复解析；
- 昂贵的全局元数据发现（节点有效性探测表、修改器枚举清单、渲染引擎目录）由 `catalogs.py` 在模块级常驻缓存；
- 当场景状态或插件环境发生变更时，通过 `blender_describe(target="refresh")` 显式热刷新缓存。

### 规则 7：无头自动化测试门禁 (Headless CI & Testing Standards)
- 任何工具层或 Rust 核心修改，必须通过无头 Blender 自动化测试验证：
  ```bash
  make test
  ```
  或者分别执行：
  ```bash
  blender -b --python tests/test_adaptive_tools.py
  blender -b --python tests/test_transport.py
  blender -b --python tests/test_rust_mcp_integration.py
  ```
- 严格遵循 Rust 质量规范：
  ```bash
  cargo fmt --all -- --check
  cargo clippy -p blender_mcp_core -- -D warnings
  ```

---

## 3. Blender 本地源码查阅速查手册 (Source Code Navigation)

当在实现自适应或排查 RNA 属性疑难时，优先通过 `rg` 检索本地源码 `/Volumes/Data/code_projects/mtk/blender`：

| 关注领域 | Blender 本地源码核心目录 | 检索重点与关键词 |
| :--- | :--- | :--- |
| **RNA 属性与结构暴露** | `source/blender/makesrna/intern/` | `rna_*.cc`, `RNA_def_property`, `RNA_def_property_enum_items` |
| **RNA 核心调度与宏** | `source/blender/makesrna/` | `RNA_access.hh`, `RNA_define.hh`, `RNA_types.hh`, `RNA_path.hh` |
| **DNA 底层内存布局** | `source/blender/makesdna/` | `DNA_object_types.h`, `DNA_modifier_types.h`, `DNA_node_types.h` |
| **物体与变换算子** | `source/blender/editors/object/` | `object_transform.cc`, `object_ops.cc`, `object_modifier.cc` |
| **网格算子与基元** | `source/blender/editors/mesh/` | `mesh_ops.cc`, `editmesh_add.cc` (基元生成参数) |
| **着色器/几何节点拓扑**| `source/blender/nodes/` | `source/blender/nodes/shader/nodes/`, `source/blender/nodes/geometry/nodes/` |
| **修改器系统与求值** | `source/blender/modifiers/intern/`| `MOD_*.cc`, `MOD_util.cc` |
| **视口绘制与渲染捕获** | `source/blender/draw/`, `source/blender/render/` | `draw_manager.cc`, `render_ops.cc` |
| **官方 Python 启动逻辑**| `release/scripts/startup/` | `bl_ui/`, `bl_operators/` |

### 源码实用检索命令示例 (使用 `rg`)
```bash
# 1. 查找某个 RNA 结构体的属性定义 (如 Modifier 或 Object)
rg "RNA_def_struct.*Modifier" /Volumes/Data/code_projects/mtk/blender/source/blender/makesrna/intern/

# 2. 查找某个属性的枚举项定义 (如 RenderEngine 或 ShadingType)
rg "RNA_def_property_enum_items" /Volumes/Data/code_projects/mtk/blender/source/blender/makesrna/intern/rna_render.cc

# 3. 查找某个操作符的内部名称与参数定义 (如 mesh.primitive_cube_add)
rg "primitive_cube_add" /Volumes/Data/code_projects/mtk/blender/source/blender/editors/mesh/
```

---

## 4. 目录结构与架构分工

```text
blender_mcp/
├── Cargo.toml / Makefile      -> Rust 工作区与构建脚本
├── dist/                      -> 打包生成的 .zip 扩展包输出目录
├── tests/                     -> 无头 Blender 自动化集成测试与自适应测试
│   ├── test_adaptive_tools.py -> RNA 自适应内省与九大工具调用测试
│   ├── test_transport.py      -> HTTP / SSE / Session 传输协议测试
│   └── test_rust_mcp_integration.py
├── crates/
│   └── blender_mcp_core/      -> Rust cdylib 核心层 (Transport-Only)
│       └── src/
│           ├── lib.rs         -> PyO3 模块入口 (start_server, stop_server)
│           ├── bridge/        -> Tokio 异步通道与 Blender 主线程调度器
│           ├── server/        -> Axum Web 服务、SSE 事件流与 JSON-RPC 路由
│           └── tools/         -> 纯转发桥 (runtime.rs) 与工具模式反向解析
└── addon/
    └── blender_mcp/           -> Blender 5.1+ 现代化插件扩展包
        ├── blender_manifest.toml -> Blender 5.1+ 扩展清单文件
        ├── __init__.py        -> 扩展生命周期生命注册与主循环轮询驱动
        ├── blender_mcp_core.so -> Rust 编译产物 (软链或拷贝)
        └── blender_mcp_runtime/ -> Python 自适应运行时单例 (基于 RNA)
            ├── catalogs.py    -> 基于 RNA 的节点/修改器/引擎实时可用项缓存
            ├── rna.py         -> 核心 RNA 内省引擎、指针路径解析与类型强转
            ├── registry.py    -> 工具统一注册机与 Schema 动态物化
            └── tools/         -> 9 大通用工具实现
                ├── describe.py       -> blender_describe
                ├── inspect.py        -> blender_inspect
                ├── operator.py       -> blender_run_operator
                ├── set_property.py   -> blender_set
                ├── modifier.py       -> blender_manage_modifier
                ├── nodes.py          -> blender_manage_nodes
                ├── hierarchy.py      -> blender_manage_hierarchy
                ├── capture.py        -> blender_capture
                ├── script.py         -> blender_execute_script
                └── schemas.py        -> 动态 Schema 定义与枚举实时注入
```

---

## 5. 日常 CLI 开发工作流

1. **编译原生核心**：
   ```bash
   make build
   ```
2. **执行无头自适应工具集成测试**：
   ```bash
   make test-adaptive
   ```
3. **交互式启动 Blender 并自动加载 MCP 扩展**：
   ```bash
   make run-blender
   ```
4. **代码格式化与静态检查**：
   ```bash
   cargo fmt --all
   cargo clippy -p blender_mcp_core -- -D warnings
   ```
5. **打包分发扩展**：
   ```bash
   make extension
   ```
