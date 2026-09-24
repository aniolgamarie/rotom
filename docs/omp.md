# 使用 agentcfg 管理 OMP

OMP 管理器集成已实现，固定基线为 OMP v18.3.0、提交 `62bc57be1b03ef0802a33cf7f5f530e534527531`。本文描述受管使用方式；隔离验收、Linux x64 smoke 与其他未验证平台/账号项见[实施记录](../specs/002-manage-omp-config/implementation-progress.md)，原生支持声明以[验证证据](omp-support.md)为准。

## 配方和原生 profile

rotom 配方定义选用的公共模型、角色、规则、技能和 OMP 资源；OMP 原生 profile 保存该配方独立的配置、登录及会话。每个配方使用新建的原生命名 profile，名字由配方 ID 的 UTF-8 SHA256 前 24 位确定，并始终核对完整 ID 和完整哈希。

每个实例还有独立 HOME，因为 OMP 的部分设施位于原生 profile 之外。原生配置放在 `<instance>/user-home/.omp/profiles/<native-name>/agent`。管理器设置 HOME/XDG，不接受使用者指定原生 profile 名、旧 agentDir 或任意设置路径；不复制现有登录或会话。

修改同一个实例的命令和受管启动共用物理实例锁；更换管理状态目录不能接管已有实例。切换配方会切换账号和会话范围，原配方的数据保留原位。

## 配置来源

| 内容 | 来源 |
|---|---|
| 公共 provider/model、MCP | `shared/` registry，精确 ID 与引用 |
| 规则与完整技能 | `shared/`，技能包含脚本、资源及执行位 |
| OMP 默认与 prompt/theme catalog | `agents/omp/` |
| 扩展及本地 MCP 包 | `agents/omp/packages/`，完整内容进入依赖锁 |
| 能力组合 | `profiles/omp-*.toml` |
| 本机路径与非秘密覆盖 | 私人机器文件的 `overrides` |
| API key 或完整 Authorization header | 私人 SecretStore，通过 `secret:名称` 引用 |
| 原生登录与运行状态 | 新建实例 HOME，排除于配置备份和 capture |

对象逐层合并，数组整体替换；`false` 与空数组保留。未知字段、未声明引用、模糊模型 ID 和包含凭据的 URL 均拒绝。公共模型 `main` 角色映射到 OMP `default`；还可声明 `smol`、`slow`、`vision`、`plan`、`advisor`。静态自定义模型必须提供准确容量，不补造价格。

## 操作顺序

全局选择参数位于子命令之前。先准备仓库 `.venv` 与权限为 0600 的私人机器文件，再使用统一入口：

```sh
./agentcfg --local /private/local.toml --profile omp-default validate
./agentcfg --local /private/local.toml --profile omp-default render
./agentcfg --local /private/local.toml --profile omp-default plan
./agentcfg --local /private/local.toml --profile omp-default sync
./agentcfg --local /private/local.toml --profile omp-default apply
./agentcfg --local /private/local.toml --profile omp-default doctor
./agentcfg --local /private/local.toml --profile omp-default run omp --cwd /absolute/project
```

`validate/render/plan/apply` 与默认 `doctor` 离线，不启动 OMP。`sync` 消费已审阅锁，取得并验证运行包，不部署、登录或启动宿主。维护依赖时才显式执行 `./agentcfg lock --agent omp`。`run` 不隐式安装或部署，也不回退到 PATH 的全局 OMP。

`omp-default` 是无静态模型的 bootstrap 配方。重新登录使用同一受管身份：

```sh
./agentcfg --local /private/local.toml --profile omp-default run omp -- login openai-codex
```

首版登录映射为 `openai-codex`；登录不要求补齐无关 MCP/API key。真实登录与模型使用是用户显式操作，不属于默认测试。

## 来源检查和运行参数

默认关闭外部发现、项目技能/MCP 与自动更新；对无法用原生设置完全关闭的来源，管理器检查 cwd 及其祖先、隔离 HOME、active/default profile、dotenv 和 direct helper 路径。发现未声明来源时报告路径和类别，不读取认证明细或显示秘密。

项目资源须显式设置 `agent_options.discovery.project_resources=true`，并在私人 local 声明非空绝对 `project_roots`。首版仅允许范围内经过校验的只读项目技能和 MCP；不因此接纳项目规则、prompt、扩展或任意 settings。policy/根列表变化需要重新部署，内容变化在每次启动前重新校验。

原生参数放在 `run omp --` 之后。受管入口拒绝身份/配置目录覆盖、额外扩展、secret/broker 控制、安装升级子命令和其他 cwd 来源；模型参数只能选已声明的精确模型。普通会话增加 `--no-title`，信息命令和登录使用实例 HOME 作为 cwd。

固定版本的会话恢复可能在启动内部重新选择 cwd，因此首版拒绝 `--continue/-c`、`--resume/-r`、`--session`、`--fork`、跨工具会话导入和 `--add-dir`。已保存会话仍保留。原生 `--` 后的普通提示文本按文本传递，不因包含参数字样被拒绝。

来源检查不提供操作系统沙箱，也不限制宿主会话内使用者主动执行的任意代码。

## 漂移、回滚与退出码

`plan` 使用当前值、上次部署基线和新意图比较；已有未受管原生字段保留。没有变化的 apply 不重写目标或轮换备份。双方修改同一受管字段时先报告冲突，不覆盖。`capture` 仅对 theme、已声明快捷键和可唯一反查的 modelRoles 生成私人非秘密提案。

`rollback` 恢复上一轮配置并消费备份，不降级软件或迁移认证数据库。pending 由后续显式 apply/rollback 恢复；run 和 usage 遇 pending 返回 4。

| 退出码 | 管理器启动前含义 |
|---|---|
| 0 | 成功，可有漂移或待登录提示 |
| 2 | 参数、配置或锁错误 |
| 3 | 实际启动需要的秘密缺失 |
| 4 | 所有权、活动实例、恢复待处理或来源冲突 |
| 5 | 缺少运行包、不支持平台或依赖验证失败 |
| 6 | 文件系统或内部操作失败 |

子进程已启动后保留原生输出流与退出码。九行完整虚构验收配方及分层验证步骤见 [quickstart](../specs/002-manage-omp-config/quickstart.md)；假测试包不作为真实宿主证据。

专题说明：[profile与来源](omp-profiles.md)、[旧配置迁入](omp-migration.md)、[usage](omp-usage.md)、[依赖维护](omp-dependencies.md)、[支持与证据](omp-support.md)。
