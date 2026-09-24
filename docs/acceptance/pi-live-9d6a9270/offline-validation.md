# 草案离线校验记录（2026-09-23，候选 9d6a9270）

## 修订 v3（2026-09-24：live 登记闭环）

- `register_live`：scenario 与 scope 项一一精确绑定（同身份也不可跨 scenario）；
  `--live-register` 强制单个 `--live-item`；结构合法但执行失败的报告如实登记
  `failed`；未执行拒绝登记；证据文件名内嵌报告摘要 attempt；live 报告/native/sidecar
  以规范副本归档进 evidence root；相同材料幂等（无新 revision）；显示状态完全交给
  生产 `report()` 的最新匹配选择规则。
- 回归：登记器 44 项（新增跨 scenario 双向拒绝、多 item 拒绝、failed→success 历史
  闭环含“无效材料不覆盖有效结果”）；live/报告相关 75 项；全量 mock
  `/tmp/mock-9d6a9270-livprep-20260924.json`：**1870 passed + 7 subtests、325/325
  Node、0 skipped、0 failed**（09-23 曾见 1 例 recovery-surrogate 负载时序偶发，
  本轮全量零失败；该失败与复验记录保留于当轮输出，不追认为零失败历史）。
- 所有测试证据写在临时目录，未触碰正式 `pi-cold-9d6a9270/` 归档与 scope；正式矩阵
  复验仍为 81 passed / 283 not-run、10 项 Linux live not-run、release_approved=false。
- 候选复核：recipe 与源码继续匹配（9d6a9270/85fc15c3；本轮改动仅 scripts/tests/docs，
  均在 digest 输入之外），未重跑任何冷重建。
- tasks.md 未勾项恰为 6 个主任务：T107–T109（缺机器）、T110–T111（缺真实输入/授权）、
  T112（待全部条件）。

## 修订 v2（按复核意见）

1. **`--freeze-live` 真实路径修复**：`compute_live_identity` 原 `from agentcfg.schema import
   Conflict`（ImportError，此前测试用注入绕开未暴露）、`Tree` 未导入（NameError）、
   `digest(json_bytes(x))` 双重编码错误——均已修复，并补**不经注入旁路**的真实函数回归：
   未安装/pending/current 三种不一致/generation 与 launch 不一致/实例活动中全部拒绝，合法
   部署成功；端到端 freeze 走真实 compute。
2. **冻结粒度**：`--freeze-live` 必须显式 `--live-item`（可多个），direct 与 proxy 分别
   冻结、互不波及；非本 profile/平台的项拒绝；回归覆盖两路线先后冻结共存。
3. **live 证据登记入口**：新增 `--live-register`（live 报告经生产 `validate_run_report`
   live 分支、identity 必须等于 scope 已冻结部署身份、native 前提按 digest+七元组复算、
   命令取执行 sidecar、失败报告拒绝登记）。正/负向（stale、native 篡改、failed）测试齐备。
   当前无任何真实 live 执行，未生成任何 live passed 记录。
4. **native 前提语义更正**（README v2 §1）：`native_prerequisite` 只比 `public_identity()`
   七元组，不含安装路径；同身份不同目录可复用归档报告——新增回归
   `test_native_prerequisite_is_sealed_identity_equality_not_install_path`（路径无关 +
   六类字段变化必拒）。
5. **MCP/web/terminal case 映射更正**：live `--case host-resources`，native 前提是
   **optional-services** case 报告；README 矩阵、流程与后续执行计划已按 `native_case`
   实际代码改正。
6. 草案 v2：machine id/根目录/probe/检查 Python/git/预算提案按 README §2 固化；
   模型绑定按 `pi-model-mapping-ambiguous` 依据收敛为 main-chat 共享 + second-view 独立；
   MCP 保留 stdio 形态说明。四配方 `validate` 重新全部 `valid=true`。
   登记器全量测试 42 项、live 准入测试 15 项通过。

## 已执行（全部不触网、不调模型、不写私人真实配置）

1. `agentcfg --local <draft> --profile <p> validate` ×4：
   pi-default / pi-managed / pi-codex / pi-cursor 均 `valid=true`，
   `credentials: not-checked-offline`（结构层通过；秘密未检查——本层不通过设计检查秘密）。
2. 专用测试项目：`verify-pi --prepare-live-project` 建立
   `~/.local/share/agentcfg-pi-live-9d6a9270/probe-001`
   （`status=prepared, model_calls=0`；main 分支干净；marker 校验通过）。
3. 登记器 `--freeze-live`：新增生产门槛同源实现（installed + deployment current +
   generation/launch 一致 + pending 拒绝 + 实例无活动），38 项回归通过（含只冻结
   所选 profile 的 linux-x86_64 live 项、平台/引擎过滤、幂等重跑与冲突拒绝）。
4. 补充全量 mock（含新增测试）：1863 passed + 7 subtests、325/325 Node、0 failed
   （`~/.cache/agentcfg-pi-live-9d6a9270/mock-liveprep-supplement.json`）。
   9d6a9270 已登记的 formal2 mock 报告保持原样，二者差集仅为本轮新增测试。

## 校验中发现并已修正的草案缺陷（记录以备审阅）

- `[machine]` 的路径必须放在 `[machine.paths]` 子表；
- `web.services.<id>` 必填 `type` + `network_route`；
- 选择 `openai-proxy` 插件必须设 `agent_options.network.openai_proxy_route` 指向
  mode=proxy 路线；
- `proxy_url` 必须是合法 http(s) 无凭据 URL；
- roots/checks 的路径/executable 必须为绝对路径样式（渲染层拒绝裸占位符）。

## 分层状态（勿混称）

| 层 | 状态 |
|---|---|
| 结构正确 | ✅ 四配方 validate 通过（占位符形式） |
| 仍缺输入 | ⬜ 下表 README §3 的 TODO_*（真实 URL/模型 ID/路径/预算） |
| 凭据就绪 | ⬜ 未开始（秘密由私人编辑器/登录流程填入，不经聊天/仓库） |
| 允许实际调用 | ⬜ 未授权；live 执行前还需 apply→freeze-live→同实例 native 前提重验 |

## 环境事实（本机）

- 系统 git 2.43.5 在 `/usr/bin/git`；PATH 前置的 obdev git 2.17 不支持
  `--initial-branch/--object-format`，运行 `--prepare-live-project` 时需
  `PATH=/usr/bin:/bin:/usr/local/bin` 优先（不改 digest 内源码）。
- `/data`、`/data/1` 非可信祖先：live 的 local/项目/输出根应放 `/home` 私人目录
  （probe 与校验副本均在 `~/.local/share`、`~/.cache`，0700/0600）。
