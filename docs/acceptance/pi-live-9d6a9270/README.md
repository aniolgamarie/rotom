# Linux live 验收准备（候选 9d6a9270，2026-09-23 修订 v2）

> 2026-09-24 用户最终决定：真实账号/服务验收移出 spec 001，未来实际使用时另行处理，不阻塞本 spec 正常验收完成；这取代同日先前的“暂缓但仍留在本 spec”说明。下文作为[后续工作](../../follow-ups/pi-platform-and-live-validation.md)的接续入口，所有未执行 live 项仍为 not-run，不视为未选或通过。其他三平台实机验证同样转出。

基线：mock/native 已按 `pi-cold-9d6a9270/` 独立复核（81 passed / 283 not-run，
release_approved=false）。本目录是 10 项 live 的准备层。当前状态：**结构正确 +
离线检查通过**；未到“凭据就绪”，未“允许调用”。

## 1. 身份层次（勿混用）

| 层 | 值/来源 | 说明 |
|---|---|---|
| 软件候选 | lock `9d6a9270…` / recipe `85fc15c3…` | 本仓库源码+锁，已复核匹配 |
| 部署 generation | `diagnostic_identity(workspace)` | apply 后按 local+profile+lock+runtime 计算；live 前用 `register-pi-evidence.py --freeze-live` 按项冻结 |
| 策略/资源/机器契约 | diagnostic_identity 分量 | 真实部署单独核验；不从合成夹具复制 |
| runtime | `public_identity()` 七元组 | profile/engine/platform/runtime_identity/lock_identity/slice_identity/toolchains——**不含安装目录** |

### native 前提的正确语义（v1 本文错误已更正）

`native_prerequisite()` 只比较 `public_identity()` 七元组与 case/状态：
- 同一软件运行包**安装在不同路径不影响复用**；
- 真实 apply 后用 `inspect_runtime` 读密封运行包，与归档 native 报告七元组比对；
  **完全一致且 case/transport/service 覆盖满足时，直接复用 `pi-cold-9d6a9270/` 的
  native 报告**（回归：`test_native_prerequisite_is_sealed_identity_equality_not_install_path`）；
- 任一字段失配或覆盖不足才补跑对应 native，并列明失配字段；不放宽比较规则。
- 注意：合成夹具的 runtime 身份产生于夹具 profile 配置投影；真实 live 部署的
  toolchains/slice 一致即可能匹配——以实际 `inspect_runtime` 结果为准，不预设必须重跑。

## 2. 已自动确定的机械配置（无需逐项决策）

| 项 | 决定 | 依据/核验 |
|---|---|---|
| 私人配置路径 | `~/.config/agentcfg-pi/live.toml` | 目录当前不存在，无覆盖风险；存在即拒绝覆盖 |
| 专用项目 | `~/.local/share/agentcfg-pi-live-9d6a9270/probe-001` | 生产 `--prepare-live-project` 已建立；marker `37ed2a1b…`；main 干净；0 模型调用 |
| machine id | `obrde.dev-xd3-pi-live` | 主机名派生，符合 schema（无斜杠/控制字符） |
| 实例/状态/缓存根 | `~/.local/share/agentcfg-pi-live/…`、`~/.local/state/agentcfg-pi-live`、`~/.cache/agentcfg-pi-live` | 与 dsh 的 `~/.local/state/agentcfg` 分离；0700；/home 现有 23G 需执行前复核空间 |
| 检查 Python | 仓库 `.venv/bin/python`（pytest 9.1.1） | 路径受信、含 pytest；随 probe 以 `-m pytest -q -p no:cacheprovider test_live_fixture.py` 执行 |
| Git | `/usr/bin/git`（2.43.5） | PATH 前置的 obdev git 2.17 不支持 `--initial-branch`；prepare 时显式 PATH |
| 建议预算（TK） | active_children=2、parallel_readers=1、writers_per_job=1、model_requests=24、model_turns=12、wall_seconds=1800 | 规模取合成夹具上界的余量；**待用户确认**；超限按契约 BLOCKED/拒绝，不自动放宽 |
| delegate | max_run_seconds=1800、modes review/investigate、7 presets | 与配方默认一致 |

模型绑定依据：`pi.py` 的 `pi-model-mapping-ambiguous` 只禁止**不同 model 条目**映射到
同一 (route, remote_id)；main/scout/reviewer 可共用一个 model 条目，
`second_view` 必须独立绑定（examples/pi-managed.toml 契约注释）。因此最少需要
2 个真实远程模型 ID（普通 + second-view）+ cursor/codex 各 1 个。

## 3. 10 项 live 前提矩阵（v2：修正 case 映射）

live CLI 的 `--case` 与 native 前提 case 不同：mcp/web/terminal 的 live 参数是
`--case host-resources`，但代码要求的 native 报告 case 是 **optional-services**
（`pi_validation_live.native_case`）。取报告时以 optional-services 为准。

| # | --live-item | profile/引擎 | native 前提（真实 runtime 比对后可复用） | 还缺的真实输入 |
|---|---|---|---|---|
| 1 | pi-managed.live-direct.inspect-fix-review | pi-managed/node | `pi-managed/*/native/taskkeeper-lifecycle.json`（含 direct 场景） | 主 provider base_url、main 模型 ID、预算确认、路线=direct 确认 |
| 2 | pi-managed.live-direct.second-view | pi-managed/node | 同上 | + second-view 独立模型 ID |
| 3 | pi-managed.live-proxy.inspect-fix-review | pi-managed/node | 同上（含 taskkeeper-proxy-* 场景） | 代理地址+认证凭据（私人填入） |
| 4 | pi-managed.live-proxy.second-view | pi-managed/node | 同上 | 2+3 |
| 5 | pi-codex.live-codex | pi-codex/node | `pi-codex/*/native/codex-receipts.json` | Codex 模型 ID + 实例 CODEX_HOME 登录 + 路线；受信边界声明 |
| 6 | pi-cursor.live-cursor | pi-cursor/bun | `pi-cursor/*/native/model-delegate-replacement.json` | cursor 模型 ID + 实例登录 |
| 7 | pi-default.live-mcp | pi-default/node | `pi-default/*/native/optional-services.json` | 真实 MCP 端点/协议 + 凭据 |
| 8 | pi-default.live-web | pi-default/node | 同上 | web 提供方与 origin 白名单 |
| 9 | pi-default.live-proxy | pi-default/node | `pi-default/*/native/model-delegate-replacement.json`（含 delegate-proxy-control） | 代理地址/认证 |
| 10 | pi-default.live-terminal | pi-default/node | `pi-default/*/native/optional-services.json` | 终端服务程序绝对路径 |

注：MCP 不必是 HTTP+bearer——stdio+command_ref（external_tools 绑定）同样是受支持形态；
按真实服务提供的协议择一。

## 4. 执行流程（输入就绪后；同实例按序，不并行改同一部署/scope）

```
validate → plan → sync/apply
  → register --freeze-live --scope S --local L --profile P --live-item <逐项>   # direct 与 proxy 分别冻结
  → inspect_runtime 真实部署 → 与 §3 native 报告七元组比对（一致则复用；不一致按字段补跑）
  → scripts/verify-pi.py --tier live --allow-host --allow-live --local L --profile P \
      --project <probe> --runtime <真实runtime> --scope <冻结revision> \
      --native-report <匹配报告> --live-item <SID> --case <case> --output <报告>
    （外层 wrapper 记录真实 argv 到 sidecar；live 结果无论成败原样保存）
  → register --live-register --live-item <SID> --live-report R --native-report N \
      --command-sidecar C --evidence-root E --scope S' --lock <候选>
  → report-only / check-release（新文件名，历史不覆盖）
```

## 6. 失败、重试与登记的正式处理（register-pi-evidence v3）

- **三类材料区别对待**：不可信/结构非法/身份或 scenario 不匹配 → 拒绝登记且不写任何
  文件；结构合法、身份与 scenario 精确匹配、确实执行失败 → 如实登记 `failed`；
  未执行 → 保持 not-run，不生成记录。
- **精确绑定**：报告内 `results[0].scenario_id` 必须等于目标 scope 项（Task Keeper
  普通流程与 second-view 不能互登，即使部署身份相同）；`--live-register` 只接受一个
  `--live-item`。
- **attempt 标识**：证据文件名内嵌报告摘要前 12 位；同一 item 的失败与后续成功各自
  留档，互不覆盖；相同材料重复登记幂等（skip identical，不产生新 scope revision）。
- **正式选择规则**：显示状态由生产报告器 `report()` 既有规则（同 level 中最新
  finished_at 的匹配记录）决定，登记器不另造“取最新”逻辑；失败记录文件永久保留。
- **材料归档**：live 报告、native 前提、命令 sidecar 以规范化副本写入 evidence root
  （`live-reports/`、`native-prereqs/`、`live-provenance/`），命令 sidecar 只含非秘密
  argv；scope 按链式头文件递进登记（每次传入当前最新 revision）。
- 闭环回归：failed 登记 → 该项显示 failed 且不批准发布；随后合法成功 → 显示 passed
  且失败材料仍在；stale/跨 scenario/无效报告不覆盖有效结果；重复登记零变化。

## 5. 当前分层状态

| 层 | 状态 |
|---|---|
| 结构草案 | ✅ 四配方 `validate` valid=true（`draft-linux-live.toml` v2 含 §2 值） |
| 离线检查 | ✅ 见 `offline-validation.md`（含 freeze-live 真实路径 42 项登记器测试、live 登记入口） |
| 凭据就绪 | ⬜ 等待 §3“还缺的真实输入”（秘密只经私人 0600 文件/登录流程） |
| 允许实际调用 | ⬜ 每项 live 需在执行计划确认后逐项执行；无一项记为通过 |
