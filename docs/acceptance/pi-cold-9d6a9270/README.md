# pi-cold-9d6a9270 证据归档（2026-09-23）

最终候选：lock `9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`
recipe `85fc15c3babf58e768e2b09c25f7eac031644cac220c60c16d093c87cbb9257b`，
工具链 Node v24.14.0 / npm 11.19.1 / Bun 1.4.0。
生产执行器：`agentcfg.pi_cold_rebuild.cold_rebuild`（冻结源码双目标）、
`scripts/verify-pi.py`、`scripts/register-pi-evidence.py`；本目录是原始产物的忠实拷贝，
未做任何手工修补。

## 布局

- `pi-<profile>-cold.json` — 每配方双目标顶层冷重建报告（含真实 command/时间）。
- `pi-<profile>/<target>/native/*.json` — 各 case 顶层 native 报告（scenario 集合与
  `scenarios(case, profile)` 精确一致；含 termination_confirmed 与逐场景 facts）。
- `pi-<profile>/<target>/steps/` — python-environment/sync/apply 三步原始 stdout/stderr。
- `mock-test-9d6a9270-formal2.json(+artifacts)` — 登记前与最终源码树同一时刻重跑的完整
  mock（1861 passed + 7 subtests、325/325 Node、0 skipped、0 failed）。
- `evidence/*.json` — 138 条 EvidenceRecord（每 V 项 mock/native 各一，命令与时间逐份
  取自被引用报告）。
- `pi-scope-9d6a9270-r1.json` / `pi-scope-9d6a9270-r1-r2.json` — 固定 scope 基线与登记后
  revision（Codex/Cursor/MCP/web/代理/终端为 selected_optional，未借账号）。
- `pi-report-9d6a9270-only.json` / `pi-report-9d6a9270-release.json` — report-only 与
  check-release 快照（rc 0/1）。
- `index.json` — 全部文件 sha256。

## 状态摘要（本候选）

- Linux x86_64：91 项中 81 passed（四配方 mock+native 双目标全链闭合）；
  其余 10 项 = 4 required Task Keeper live + 6 selected_optional live，均 not-run
  （`Pi --local`、专用项目、账号/服务绑定未准备）。
- linux-arm64、darwin-arm64、darwin-x86_64：各 91 项 not-run（无测试入口，非未选择）。
- release_approved=false；报告生成与交付批准为两个独立结果。

## 独立复验

```
.venv/bin/python -B scripts/verify-pi.py --report-only \
  --scope docs/acceptance/pi-cold-9d6a9270/pi-scope-9d6a9270-r1-r2.json \
  --evidence-root docs/acceptance/pi-cold-9d6a9270 --output <可信私人目录>/report.json
```

已实测：counts 与 input_digest 与本目录快照完全一致（归档自足）。

## 读法注意

- sha256 索引证明文件完整，不证明内容属于同一候选；候选归属以各报告内
  lock_identity/source_digest/runtime 身份字段为准（登记器已逐层交叉核验）。
- pi-managed 的 V05/V13 native 记录中 readseek-tools 属映射不适用项，limitations 已
  声明由配方适用 case 覆盖；managed 配方本就不启用 ReadSeek worker。
