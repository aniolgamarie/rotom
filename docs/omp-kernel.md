# 在 WSL 使用 omp-kernel

`omp-kernel` 是日常使用配方；`omp-default` 仍是无静态模型的 bootstrap 配方。本文给出从私人机器文件到受管启动的完整步骤。当前仓库已验证 Linux glibc x64 的通用 OMP 能力，但没有可用的 WSL 远程环境，因此本文步骤不能算作 WSL 实机通过证据。

## 配方内容

公共配方 [`profiles/omp-kernel.toml`](../profiles/omp-kernel.toml) 选择两个 provider 和九个模型，包含 `anthropic-messages`、provider compatibility、模型成本、thinking 等级和 fallback chain 的原生映射。它还部署：

- 76 条 Bash 审批 pattern 和 5 条 interceptor；
- 5 个 agent、4 个完整 skill，以及作为受管原生 `RULES.md` 原文部署的确认规则；
- Kanagawa 主题、状态栏及其他受支持的界面设置；
- `default/smol/slow/plan/task` 五个模型角色；
- 公共 `agent_options.tiny_model` 选择 `local/lfm2.5-230m`，渲染为原生 `modelRoles.tiny`。

这是按当前 adapter 支持字段重新表达的配置，不是原有 HOME 的逐字复制。迁入时已删除与 `mdLink` 重复且不符合固定 schema 的 Kanagawa `link`，排除 skill 中的 `.bak` 备份，把 codex skill 的 runner 示例改为相对已安装 skill 目录解析，并把验收 fixture 的假 token 标成明确的 `SYNTHETIC` 哨兵。

旧原生 kernel 配置、账号和会话保持原位。首次 `apply` 创建新的受管实例 HOME 和由 `omp-kernel` 完整 ID 哈希得到的原生命名 profile；管理器不会复制旧账号、会话或认证存储。

## WSL 前提

- WSL 发行版须是受支持架构上的 Linux glibc 环境，并有 Python 3.11+ 和仓库已准备好的 `.venv`。musl、Windows 原生环境和未知架构会返回 5。
- 仓库、私人 local、实例、状态和 cache 应放在 WSL 的 Linux 文件系统。不要把 `/mnt/c` 作为默认位置；其权限和原子文件行为不适合作为 0600/0700 私人状态的基础。
- 私人文件的父目录须为 0700，local 文件须为 0600。真实密钥不能写进仓库、命令行或公共 profile。
- 使用模型时，WSL 还须能访问公共 catalog 中登记的 `work.oceanbase-dev.com/tokensflow/...` 企业网关，并有对应 key。该连通性独立于 GitHub 上的 OMP standalone 下载。

先在仓库根目录创建私人机器文件：

```sh
OMP_LOCAL="$HOME/.config/agentcfg/machines/omp-kernel.toml"
install -d -m 700 "$(dirname "$OMP_LOCAL")"
install -m 600 examples/omp-kernel.local.toml "$OMP_LOCAL"
${EDITOR:-vi} "$OMP_LOCAL"
```

填写 `[secrets]` 中的 `omp_kimi_tf_key` 和 `omp_zhipu_tf_key`。公共 provider 只保存 `secret:` 引用；实际值只从这个私人文件按需解析。两者都是自定义 API provider key，不需要运行 `login openai-codex`。空值仍可执行离线检查，启动需要相应模型时会返回 3。

两个默认 `base_url` 是随非秘密 catalog 迁入的企业 TokensFlow 网关。机器需要使用其他兼容网关时，可在私人 local 的 `overrides.providers.kimi_tf.base_url` 或 `overrides.providers.zhipu_tf.base_url` 显式覆盖；示例文件附有注释模板。不要直接换成同名厂商官方端点：当前模型 ID、OpenAI-compatible/Anthropic Messages 协议及 key 语义未必兼容。

## 首次部署和启动

所有全局选择参数都放在子命令前。示例 local 已把 `default_profile` 设为 `omp-kernel`，这里仍显式写出 profile，便于审阅实际目标：

```sh
OMP_WORKSPACE="$HOME/src/your-project"

./agentcfg --local "$OMP_LOCAL" --profile omp-kernel validate
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel render
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel sync
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel plan
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel apply
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel doctor
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel run omp --cwd "$OMP_WORKSPACE"
```

`validate` 和 `render` 先检查公共来源及候选原生产物。`sync` 获取正式锁指定的 standalone，`plan` 展示部署差异，`apply` 才修改新实例，`doctor` 随后检查部署和运行包。`run` 不隐式下载、部署或读取 PATH 中的全局 OMP。普通受管会话自动加入 `--no-title`，因此不会启动自动标题模型请求。

日常可省略显式 `--profile omp-kernel`，因为私人 local 已设置默认值；故障排查和变更审阅时建议继续显式写出。

## 项目来源边界

在普通仓库内启动是允许的。`.agents/`、`.agent/`、`.claude/`、`.codex/`、`.gemini/` 以及顶层 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 属于已禁用兼容 provider 的容器或上下文，受管 OMP 不自动加载其正文，单纯存在不会导致拒绝。

真正可被原生 OMP 消费的来源仍严格检查，包括 `.omp` 下的 settings、agents、tools、hooks、skills、MCP，dotenv、SYSTEM/TITLE/APPEND_SYSTEM 等 direct helper。`omp-kernel` 默认没有开启项目资源；需要项目 skill 或 MCP 时，应按[来源政策](omp-profiles.md#来源政策)声明根并接受逐项校验，不能用目录级放行引入额外配置或凭据。来源检查是启动前配置边界，不是操作系统沙箱。

## codex-delegate 和 tiny model

`codex-delegate` 只在用户显式要求使用 Codex 时调用。在带 Pi 集成的宿主中使用 `codex_delegate` 工具；OMP 没有该工具时，skill 使用随包安装的 `scripts/run-codex.sh`。后者需要 Linux Bash、`jq`、util-linux `setsid`、`/proc` 和 `codex` 命令。Codex 使用独立 `CODEX_HOME` 认证，runner 不负责安装这些程序或登录账号。

runner 默认让 Codex child 直接连接，不继承调用者的 proxy 变量。需要机器代理时，在私人 local 的 `[machine.environment.values]` 设置不含 userinfo、token、query 或 fragment 的 `CODEX_DELEGATE_PROXY_URL`；该值只传给 Codex child，不导出到调用者，也不写入 receipt/stdout。是否需要代理和代理地址由机器自行决定，配方不再假定 `127.0.0.1:10808` 可用。跨机器缺少上述 Bash、`jq`、`setsid`、`/proc`、`codex` 或独立认证时，该 skill 不可执行；部署不会自动补装这些环境依赖。

`local/lfm2.5-230m` 只由公共 `agent_options.tiny_model` 选择并生成原生 `modelRoles.tiny`，不作为已验证主模型。显式触发 tiny model 的首次使用可能需要本机已有模型 cache，或需要网络获取模型；这与正式 OMP standalone 的 `sync` 缓存是两件事。

## 下载中断与复用

运行资产写入 profile 私人 cache 的内容寻址 `.part` 文件。管理器对瞬态超时、连接重置、HTTP 408/429/5xx 和短读最多尝试三次；服务端正确返回 206 与 `Content-Range` 时从安全偏移续传，返回 200 时从零重写。只有完整长度和 SHA256 都匹配才原子发布为可用缓存。

中断后保持同一个 local/profile 再执行 `sync`，会继续使用同一 cache 和安全 partial。不要手工把 `.part` 改名为完成文件，也不要绕过锁摘要。错误只报告类别、尝试次数和进度；诊断步骤见[依赖维护](omp-dependencies.md#下载中断诊断)。`sync` 下载失败与会话访问企业模型网关失败是两条独立路径，不能因模型网关公网不可达就归因于 OMP 下载器。

Linux x64 的既有宿主证据见[真实 smoke](../specs/002-manage-omp-config/evidence/linux-smoke.md)。它不证明 WSL、Linux arm64、macOS、真实账号或这些 API provider 的模型调用已经通过。
