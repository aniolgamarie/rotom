# Pi 诊断与验证结果

## 分层 doctor

`agentcfg doctor` 为 Pi 增加 `capabilities`，分别报告选择、配置、部署、依赖、加载证据、认证观测和执行证据。包已安装不会自动变成加载或执行已验证；bootstrap 未绑定模型会显示 `PI_MODEL_UNBOUND`。

- 必要运行包缺失或损坏：输出诊断后返回 5。
- 原生认证未检查：`not-inspected`，不会读取 Pi/Codex 的账号文件来猜测是否登录。
- 匹配的历史认证观测：`observed-ready`，同时显示观测时间。
- 匹配的“需要登录”记录：`pending-login`。
- 不需要认证的能力：`not-required`。

可通过私人配置列出允许读取的证据文件：

```toml
[overrides.profiles.pi-default.agent_options.diagnostics]
evidence_root = "/absolute/private/evidence"
evidence_paths = ["load.json", "authentication.json", "execution.json"]
```

每份证据遵守 `agents/pi/schemas/evidence.schema.json`。doctor 的阶段观测使用 `test_case_id = load | authentication | execution`。只有身份和目标平台匹配的 native/live 证据可以显示 verified。mock 记录不冒充原生加载或真实认证。

身份包括锁、运行包、策略、渲染内容、完整选中技能、角色／模型和机器契约；修改策略、模型、规则内容、路线等会使旧观测失效。诊断文件清单本身不属于执行身份，补充证据不会使已有证据自动过期。

`doctor --live` 对 Pi 只发送明确 provider、MCP HTTP 服务及 Web API origin／路线的 HEAD 可达性探测，不调用模型，不检查原生账号，不跟随重定向。环境代理和 NO_PROXY 不改变该路线；未绑定路线会显示 `explicit-route-required`。当前探测支持直连和无认证 HTTP 代理，需代理凭据或 HTTPS 代理时明确显示未验证，不回退直连。HTTP 401/403 只证明服务器响应，不能证明登录或模型可用。公共 Web 抓取没有预先选定目标时报告 `public-target-not-selected`，不会自行选择站点；只选公共抓取且没有凭据或订阅模型的 Web 配置显示认证 `not-required`。

## 固定范围报告与发布检查

```sh
.venv/bin/python scripts/verify-pi.py --report-only \
  --scope /absolute/pi-scope.json --evidence-root /absolute/private/evidence \
  --output /tmp/pi-status-new.json

.venv/bin/python scripts/verify-pi.py --check-release \
  --scope /absolute/pi-scope.json --evidence-root /absolute/private/evidence \
  --output /tmp/pi-release-new.json
```

- `report-only` 的 0 只表示报告生成成功。零证据也能生成报告。
- `check-release` 只有当前固定范围内所有必需和已选可选项的要求层级均通过才返回 0；缺失、失败、过期返回 1。
- 损坏 schema、非法路径、身份摘要错误等返回 2。
- 报告是新的 0600 文件，并发同名创建也不会覆盖原报告。每次使用新文件名。
- 只读取 scope 列出的相对证据路径，不扫描旁边的账号文件、旧报告或其他 scope。
- `not-selected` 是用户选择状态，不是执行通过；尚未登录、没有机器或没有授权不等于未选择。
- scope 或证据内容改变后，旧批准不再匹配。自动修订不能删减必需范围。

## 执行隔离测试

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/pi-mock-new.json
```

此入口使用新临时 HOME，运行默认 pytest 和受限 Node mock 套件。原始输出保存到相邻的私人 `.artifacts` 目录，报告保留执行命令与退出状态。任何一个套件失败或无法运行，整体不会返回通过。

native/live 运行器已实现。2026-09-24 的候选锁摘要 `9d6a9270…` 在约定的 Linux x86_64 软件范围内取得 81/81 通过及四配方双路径冷重建证据，见 [历史关闭报告](acceptance/pi-spec-closure-20260924/README.md)。其他平台与真实账号/服务仍在[后续清单](follow-ups/pi-platform-and-live-validation.md)，未运行的场景保持 `not-run`。

历史关闭不等于当前 checkout 的原生验证通过。锁、源码、运行包或策略变化后，需要匹配新身份的证据；版本探测和 Python/mock 测试不能替代 native/cold 验证。当前版本与历史候选的边界统一记录在 [Pi 支持矩阵](acceptance/pi-support-matrix.md)。
