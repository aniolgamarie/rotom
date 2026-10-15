# rotom 工程约定

个人 Agent 配置管理仓库。通过 `./agentcfg` 管理公共配置来源、机器覆盖、原生转换、完整依赖、部署与启动。
已实现 DSH + `ccch1mneyyy/dsh-TUI`、Pi 和 OMP 适配；Pi 通过 model-delegate 调用官方 Codex CLI，Codex 不是独立配置适配器。`./termcfg` 独立管理 zsh/tmux；旧 mihomo 所有权仅保留显式元数据迁移和历史恢复入口。实现、历史验收与当前平台支持须分别判断，见 `docs/architecture.md` 和各工具支持矩阵。

## 基本原则：不修改 agent 上游源码

- 所有 agent 均使用未改动的上游实现。集成只通过官方配置、公开插件/扩展 API、官方 CLI 和仓库自有适配代码完成。
- 禁止给 agent 上游源码或其 vendor/缓存副本打补丁，禁止发布补丁重编译的宿主、修改官方二进制，或通过 monkey patch/私有接口改写宿主内部实现。
- 公开接口不足时，明确说明能力限制，调整功能设计或等待上游支持；不得以实现某项功能、已有 spec 或历史验收为由绕过此原则。
- 已存在的宿主补丁属于历史方案，必须记录偏离与迁移状态，不新增、扩展或继续构建发布。迁移到官方运行包须保留账号、会话、配置所有权与恢复边界，不能自动终止活动实例。
- 该原则适用于当前和以后接入的全部 agent，不仅限于 OMP；完整治理规则见 `.specify/memory/constitution.md`。

## 技术栈

- Python 3.11+，使用 `uv` 管理依赖
- 依赖：PyYAML、jsonschema、Jinja2、pytest
- 入口：`./agentcfg`（直接使用仓库 `.venv`，不走 `uv run`）
- 配置格式：TOML（registry/profiles/local），JSON/YAML（各适配器原生产物）

## 目录结构

```
src/agentcfg/       # Python 模块
src/termcfg/        # 终端配置、插件依赖与恢复管理
shared/             # 公共 rules/skills
profiles/           # profile 定义 (TOML)
agents/            # DSH/Pi/OMP 默认值、资源、schema 和适配配方
locks/             # 各工具完整依赖锁与 vendor
terminals/         # zsh/tmux 公开文件和逐文件来源清单
schemas/            # JSON Schema 定义
examples/           # 本地配置示例
tests/              # pytest 测试
docs/               # 文档
```

## 测试边界（DSH-10）

- **默认测试只允许仓库内和临时 HOME 目录**
- 默认测试使用临时 HOME/DSH_HOME/XDG、网络阻断、假子进程、虚构 provider/model 和文件哨兵
- **默认测试不启动第三方宿主**（DSH、Pi、Codex 等）
- 真实 smoke 为独立显式步骤，需用户明确授权
- 不以无账号 smoke 或 CI 文件代替通过证据

## 开发规范

- 双引号字符串，2 空格缩进
- 中文注释
- 原子提交，conventional commit 格式
- 仅使用用户明确批准的公开 Git 身份（包括批准的 noreply 或 bot 身份）；`user.name`、`user.email`、`user.useConfigOnly=true` 仅设于仓库本地 Git 配置，不在共享规则中固定真实姓名或邮箱。提交前核对 `git config --local --get user.name`、`git config --local --get user.email`、`git config --local --get user.useConfigOnly` 与 `git var GIT_AUTHOR_IDENT`、`git var GIT_COMMITTER_IDENT`，并检查环境身份覆盖；作者与提交者均须匹配批准身份，不沿用全局值或系统自动推导。
- 不提交 secrets 或凭据
- 未知字段失败，不静默丢弃或修复
- 秘密值不进入通用配置/摘要/日志/异常

## 公开发布与所有工作树合并

- 公开代码、文档、提交消息和报告不得包含真实用户名、私人绝对路径或业务路径、主机元数据、个人邮箱、认证链接/验证码、token、密钥、会话正文或私有端点。使用通用路径、保留域名和虚构测试数据；保留法定许可、上游署名、公开来源标识及必要工具链事实。
- 不读取真实密钥、认证或会话文件来验证公开清理；扫描命中仅记录脱敏位置与类别，不输出原值。备份必须置于公开仓库外的私人存储，目录 `0700`、文件 `0600`；确认凭据泄露时由所有者先撤销或轮换，清理不证明历史没有凭据。
- 每个分支和工作树将来合入 `main` 前均适用同一门禁：盘点目标 `main`、候选 HEAD、状态和文件所有权；审阅稳定最终差异、私密信息、作者/提交者与历史、来源/依赖/锁一致性；执行与范围匹配的隔离、原生和平台验证并记录候选、锁、实际 argv、退出码和结果。
- 写入结束后才做最终审查；验证后再修改须重跑受影响检查。使用干净且准备完成的提交，未验证不能记为通过，已知失败必须明确说明并取得对应范围的接受；目标 `main` 前进时重新评估。仅在授权范围内快进或合入已审阅合并，不强推或丢弃用户工作。
- 历史切换只清理明确授权的引用。仅清理 `main` 不等于全仓库擦除，保留的私人分支/工作树仍有旧历史。旧谱系不得普通合并回清理后的 `main`；从干净 `main` 重放自身变更，谨慎挑选提交并规范化身份，重新完成门禁。仅合入新 `main` 或通过祖先检查不证明旧父提交已清理。远端更新需独立授权。
- 执行细则见 `docs/publication-policy.md`、`docs/worktrees.md`；任务记录区分已完成、进行中、失败待决策、环境不足未验证，环境不足不能记为通过或阻塞无关工作。

## 退出码

- 0: 成功（可有漂移/待登录提示）
- 2: 参数或配置/锁校验错误
- 3: 所需凭据缺失
- 4: 所有权冲突、活动实例或恢复待处理
- 5: 依赖/原生检查失败或缺必要运行包
- 6: 文件系统/内部操作失败
