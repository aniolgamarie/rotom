## ADDED Requirements

### Requirement: CFG-01 Versioned schemas and stable entity references

系统 SHALL 使用带 `schema_version` 的严格 schema 校验框架 registry、工具声明、profile 和本地文件；实体以稳定 ID 索引，未知字段、同层重复 ID、无效引用、不支持的映射与认证拥有者冲突 MUST 失败并报告脱敏字段位置。

#### Scenario: Invalid definitions fail without silently repairing input
- **WHEN** 输入分别包含重复 TOML 表、跨同层来源重复实体、拼错字段、缺失 model/provider 引用或同 provider 两个认证拥有者
- **THEN** validate 分别给出可区分的错误，不丢弃字段、不自动去重、不修改源文件或目标

### Requirement: CFG-02 Local machine format covers explicit machine differences

本地格式 SHALL 明确定义 `machine` 的 id/default_profile/editor、`machine.paths` 的 instances_root/state_root/cache_root、`machine.environment` 的 inherit/values、`overrides.providers/models/mcp/profiles` 和 `secrets`。系统 SHALL 支持本地新增 provider/model/MCP 和覆盖多个已声明 profile，工具参数使用各自 adapter schema；不得接受任意未校验的原生配置表。

#### Scenario: Private gateway and several profile overrides share one local file
- **WHEN** 本地文件新增私有 provider/model/MCP，覆盖两个已存在 profile 的选择与工具选项，并指定本机实例路径
- **THEN** 全部结构和引用被校验，仅当前选中的 profile 生效，私有实体不写入 Git，未选择的 MCP 不启用

#### Scenario: Invalid local keys and unsupported schema fail clearly
- **WHEN** 本地文件包含未知 schema_version、拼错 machine 路径键、不存在的 profile override 或当前 adapter 不认识的 agent_options
- **THEN** 校验失败并指出表/字段路径，不打印私有值，不静默迁移或重写文件

### Requirement: CFG-03 Local paths and environment values have literal semantics

路径 SHALL 仅接受绝对路径或以 `~/` 开头的路径，按当前 HOME 展开一次；系统 MUST 拒绝相对路径、`~user` 和插值表达式。editor SHALL 是单个程序名或路径。environment.values SHALL 为非秘密字符串表，inherit SHALL 为明确变量名数组，保留的实例/凭据环境名不得被本地覆盖。

#### Scenario: Chinese and space-containing paths remain intact
- **WHEN** 合法路径含中文与空格，且用户提供合法 editor 路径
- **THEN** 系统按字面解析路径并使用 argv，不拆词、不 eval、不改变用户工作目录

#### Scenario: Environment configuration cannot override isolation
- **WHEN** 本地配置尝试通过环境表覆盖 DSH_HOME 或凭据目标变量，或将路径写成环境插值/命令替换表达式
- **THEN** 校验失败，表达式不执行，错误只报告位置与原因

### Requirement: CFG-04 Layer merge preserves explicit values and provenance

系统 SHALL 按 registry 与工具默认值、profile、本地 overrides、受限本次参数顺序合并；对象递归、标量覆盖、数组整体替换。空数组与 false MUST 生效。每个结果字段 SHALL 记录来源，本地来源默认私有，实体仅按选择启用。

#### Scenario: Empty selection and false override defaults
- **WHEN** 默认配置选择两个 MCP 且开启终端图片，本地覆盖 mcp 为 `[]`、terminal_images 为 false，并只改一个嵌套角色
- **THEN** MCP 选择为空、图片预览关闭、其他嵌套字段保留，来源分别指向相应层，未选择 registry 不自动启用

### Requirement: CFG-05 Missing values and removal are distinct

系统 SHALL 区分字段缺失、空字符串、空数组和 false；覆盖中省略字段表示继承。取消实体选择 SHALL 生成受管删除意图；删除仍被引用的 registry 实体 MUST 校验失败。删除的执行仍受 manifest 和三方合并约束。

#### Scenario: Deselecting a skill plans only owned removals
- **WHEN** 新 profile 不再选择已部署技能，但技能目标中有不受管文件或资源被用户修改
- **THEN** plan 仅提出符合所有权的删除，对修改过的受管资源报告冲突，不递归删除其他内容

### Requirement: CFG-06 Secret values stay outside compilation and identifiers

系统 SHALL 首版实现 `secret:<name>` resolver；秘密值 MUST 与普通解析配置、渲染上下文、摘要、generation 输入和部署记录隔离。离线操作 SHALL 不要求真实密钥或登录。私有 endpoint/model ID 的计划和错误 SHALL 默认脱敏。

#### Scenario: Synthetic canary never enters outputs or generation inputs
- **WHEN** 本地 secrets 含引号、换行、`$()`、反引号组成的合成 canary，执行 validate/render/plan/apply/sync/错误路径，并仅更换 secret 值后重复 render
- **THEN** 产物、日志、异常、diff、argv、锁、备份、journal 和 generation 输入均不含秘密值，其值变化不改变渲染字节或 generation，表达式不执行

#### Scenario: Missing credentials do not invalidate a deployable configuration
- **WHEN** schema 与引用合法，但所引用 secret 尚未填写
- **THEN** validate/render/plan/apply/sync 可以完成其非认证工作，凭据缺失单独报告，不当作 schema 错误

### Requirement: CFG-07 Rendering is deterministic and text-safe

同一非秘密输入、锁、机器路径及 adapter 版本 SHALL 得到相同产物集合、字节与模式。普通规则 Markdown SHALL 按选择顺序原样组合；只有明确文本模板使用 Jinja2 StrictUndefined。JSON/YAML SHALL 通过序列化器生成。

#### Scenario: Literal braces and special characters survive rendering
- **WHEN** 规则含 `{{example}}`，普通值含换行、引号、中文、`$()` 和反引号，连续 render 两次
- **THEN** 普通文本不被当模板执行，结构化输出能重新解析，两次文件集合/字节/模式一致，未定义模板变量明确失败

### Requirement: CFG-08 Skills are complete attributed packages

系统 SHALL 完整复制所选技能资源、相对路径和必要执行位，保存来源与自定义修改说明，加载配置时不得执行脚本。shared 与 agent 的同名技能 SHALL 有显式覆盖声明，否则失败。首版 SHALL 提供实际可用的大仓库局部导航技能。

#### Scenario: Skill resources and collision handling are preserved
- **WHEN** 技能含可执行脚本、中文资源路径和相对引用，或 shared/agent 中出现同名技能
- **THEN** 合法技能完整复制且脚本未运行；同名冲突仅在显式覆盖声明后消除，资源来源可审查

### Requirement: CFG-09 Local examples are executable framework documentation

系统 SHALL 提供空密钥的本地示例、字段参考及 XDG/自定义路径/SSH/私有网关/多 profile 场景；例子 MUST 标为框架 TOML并经实际 schema 验证。虚构 fixture SHALL 使用 example.invalid 和虚构模型，与真实配方分开；禁止读取现有凭据填例子。

#### Scenario: Documented local example can be validated offline
- **WHEN** 在临时 HOME 中复制示例并使用对应虚构 fixture 执行文档里的 validate/render 流程
- **THEN** 例子通过真实解析器与 schema，不联网、不要求账号，文档不将虚构 provider 作为生产服务推荐
