# Pi 迁移最终报告 — 候选 9d6a9270（2026-09-23）

接手自 `docs/handoffs/pi-resume-without-loopguard-2026-09-23.md`。执行清单与过程记录见
`pi-execution-inventory-20260923.md`；全部原始证据归档于 `pi-cold-9d6a9270/`
（sha256 索引 `pi-cold-9d6a9270/index.json`）。

## 1. 最终候选与源码身份

- lock identity `9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`
- recipe_digest `85fc15c3babf58e768e2b09c25f7eac031644cac220c60c16d093c87cbb9257b`（正式
  `resolve_lock` 重建 vendor/切片/身份；locks/dsh 逐文件未动）
- 工具链 Node v24.14.0 / npm 11.19.1 / Bun 1.4.0；接手起点 ed34c4e7 当时与源码匹配属实。
- 本轮代码修改（每次修改后按正式流程重新冻结）：
  1. `pi_cold_rebuild.native_cases()` 为 pi-cursor 补 readseek-tools；冷报告增加真实
     started/finished/command；copy_source 摘要归一（可自快照重算）；
  2. 原生沙箱只读绑定独立 Node 发行目录（Bun 宿主 ReadSeek worker 可见性）；场景 PATH
     补系统 bin 目录（rg 前提可发现）；
  3. ReadSeek 九工具执行语义：search 改可命中 Python 带体模式；view 改用夹具内合成
     `sample.pdf` 真实文档（**证实历史各轮 “view_verified” 为弱断言假通过**——服务端对
     txt 返回非错误的“不支持文档格式”）；def/refs/rename 在真实 Python 文件 `notes.py`
     上执行并逐结果断言；越界写拒绝与残留检查保留；
  4. 夹具 readseek 分支不再整表替换插件（保留 cursor provider 所有者 pi-cursor）；
  5. 登记器重写：复用生产 `validate_run_report`/`scenarios()`/`native_cases()`、cold
     精确目标/步骤/case 集合与递归核验、源码快照摘要信任锚点、真实 command/时间
     （废除 mtime 冒充与 `--case a+b`/占位 runtime）、逐 case 覆盖按配方适用集过滤并
     记录 limitations。

## 2. 对上一工具自报统计的纠正

| profile | 上一工具自报 | 核实结果 |
|---|---|---|
| Codex | 两目标各 7 组通过 | 属混候选归档（32da4799 目录混入 4c043f8f），对任何后续候选均 stale |
| default/managed 重试 | 部分完整通过 | ed34c4e7 default 顶层实际 failed（first 7 组过、第二目标 target-preparation-failed）；managed 从未有双目标同候选证明 |
| Cursor 5+2 组 | 通过 | cursor 预期集当时缺 readseek-tools，5/5 不构成完整验收 |
| ReadSeek | default/Codex 若干目标通过 | view 步骤从未真正核验结果（假通过）；search/def/refs 弱断言 |
| “41/72、剩 31 场景” | — | 口径作废：case 组与组内 scenario 混算；真实 profile 只有 4 个 |
| “1839 pytest” | — | 原始报告为 1836 passed+3 skipped+7 subtests、325 Node（/tmp v6 轮，未归档） |

## 3. 最终候选的八目标实际结果（全部 passed）

每目标：独立 HOME/checkout、`uv sync --locked` + `agentcfg sync/apply` 三步 exit 0、
`installation=verified`、生产 `verify_native_target` 逐 case 调 `verify-pi --tier native
--allow-host`（真实 argv 已入档）。

| profile | 目标 | 必需 case | 结果 |
|---|---|---|---|
| pi-default | first / 第二组(空格路径) | host-resources, migration-conflicts, model-delegate-replacement, budget-permissions, termination-recovery, readseek-tools, optional-services（7）| 双目标 passed |
| pi-cursor | 同上两目标 | 上述除 optional-services（6，**含 readseek-tools**）| 双目标 passed |
| pi-codex | 同上两目标 | 上述除 optional-services、含 codex-receipts（7）| 双目标 passed |
| pi-managed | 同上两目标 | host-resources, migration-conflicts, taskkeeper-lifecycle, budget-permissions, termination-recovery（5）| 双目标 passed |

- 归档 native 报告共 **110 个 scenario 行，110 行均有 exit_code+termination_confirmed
  证明**（parent-loss 以 137+撤销观察为合格）；无 escaped/unknown 污染，登记器递归核验
  全部引用一致。
- 证据链：候选输入→安装收据→顶层 cold 报告→各 native 报告→场景 facts/终止证明→
  138 条 EvidenceRecord→scope r2→report-only/check-release 快照，逐层 lock/runtime/
  source/profile/platform 匹配（登记器强制，非人工拼装）。

## 4. Cursor ReadSeek、九工具与 Task Keeper 生命周期实际覆盖

- Cursor（Bun 1.4.0 宿主）readseek-tools 双目标 passed：九工具 grep/search/digest/
  view/write/edit/def/refs/rename 经监督控制器逐一真实调用，逐步结果断言（检索命中
  code.txt、AST 命中 test_bounded_change、PDF 结构含 Page 1、写入/编辑/重命名以文件
  终态校验、越界写 local.toml 被拒且无残留、项目无游离文件、活动清零）。
- ReadSeek worker 使用独立锁定 Node v24.14.0（版本核验 + 沙箱只读绑定），未回退 Bun。
- Task Keeper：managed 两目标各 11 scenario（inspect/fix/second-view/budget/quota/
  missing-result/pause-resume/stop/schedule/proxy-fix/proxy-second-view）全 passed。
- model-delegate：7 preset、batch 幂等、控制面 8 用户操作、（default 另含 proxy 控制）
  双目标通过；codex-receipts 三场景含官方 CLI 只读/写入/控制边界与 kernel namespace 证明。

## 5. 登记器关键正负向与主入口验证

`tests/test_register_pi_evidence_negative.py` 36 项全绿：生产格式正例（每配方全 case、
四配方 cold 递归）+ register-review 全部 8 类误收样本改判拒绝 + scenario 缺失/重复、
命令/时间缺失、无装饰历史 cold、跨身份、live 不借用等证据；主入口在临时输出根覆盖
合法登记、候选锚点失配 rc2、混候选 profile 跳过、引用缺失整 profile 拒登、幂等重跑、
内容冲突拒绝覆盖、live 保持 not-run。

## 6. 正式 scope 统计与发布结论

- report-only：生成成功（rc 0）；364 项 = passed 81 / failed 0 / not-run 283 /
  stale 0 / not-selected 0。Linux x86_64：81/91，缺口恰为 10 项 live。
- check-release：rc 1，`release_approved=false` —— 4 项 required Task Keeper live 与
  6 项 selected_optional live 未执行，其他三平台（各 91 项）无测试入口。
- 归档自足性已复验：对 `pi-cold-9d6a9270/` 直接 report-only，counts 与 input_digest 与
  快照完全一致。
- 结论：**报告生成成功 ≠ 交付批准**；本候选不满足完整迁移批准条件，缺口全部为外部
  前提（账号/live 配置/机器），Linux 侧 mock/native 已闭合。

## 7. 历史剩余任务与外部依赖（已于 2026-09-24 修订本 spec 范围）

用户随后明确将三平台与 live 验收移出本 spec。当前 spec 已按 Linux x86_64 软件范围正常验收完成，见 [关闭报告](pi-spec-closure-20260924/README.md)。以下清单与原 364 项不批准结论保留为历史事实和后续入口，不再代表本 spec 尚未完成。

1. T110/T111：10 项 live —— 需要 `Pi --local` 绑定、专用实网测试项目、Codex/Cursor
   账号与 MCP/web/代理/终端服务准备及逐项独立授权；对应平台 native 前提本候选已满足。
2. T107—T109：linux-arm64、macOS arm64/x86_64 实机 native+冷构建（含 T098 遗留的
   macOS helper OWNER 实机验证、readseek Intel Zig 源码构建）。
3. T112：以上全部闭合后以同流程重生成 scope revision 并 check-release。
4. 未批准的清理清单（等待用户确认，本轮未删除任何既有他人产物）：
   - `/data/1/weixiaoxian.wxx/...` 旧运行根 111GB（前工具时代，未审计）；
   - 本会话卷 `pi-cold-9d6a9270-20260923`（含 4 份 checkout/runtime 安装树 ~60GB；
     证据已归档，删除前需确认登记链不再需要视图内重放）；
   - `/data/1/weixiaoxian.wxx/pi-cold-aborted-evidence-20260923`（212KB，建议保留）；
   - /tmp 两个 9/22 pytest 残留 `fake-helper.py supervise` 进程（735696/755954，未动）。

## 层级声明（不混称）

- 代码修改：完成（4 批，均随候选冻结）。
- mock 通过：完成（正式轮 1861 passed + 7 subtests、325/325 Node、0 skipped、0 failed）。
- native 通过：完成（Linux x86_64 四配方×双目标，110 scenario 全终止证明）。
- live 通过：**未执行**（10 项 selected/required live 保持 not-run）。
- 其他平台：not-run（缺机器）。因此**不宣称完整迁移完成**。

## 过程更正（诚实记录）

- d3e0ea80 轮“驱动被外部回收”系我误读 `ps -ef` 截断；default/codex/managed 三路实为
  我误判后删除该卷时被中途终止（其终报本可作为补充证据）。教训已落实：后续用
  bracket-pgrep/监督器管理生命周期。
- 候选推进链 ed34c4e7→fe140442→d3e0ea80→97f9fbd4→9d6a9270 每一步都由源码修复触发；
  旧候选证据一律保留原样、不迁移通过。
- 中途两次清理仅针对本会话自建的失败卷（证据先摘存），未触碰旧运行根与他人产物。
