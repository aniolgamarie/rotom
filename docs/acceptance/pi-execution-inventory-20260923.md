# Pi 迁移实际执行清单（2026-09-23 接手重建）

本文是接手工具按原始证据重建的执行清单，不继承上一工具自报统计。真实 profile 只有
pi-default、pi-cursor、pi-codex、pi-managed 四个；`pi-default-second`、`pi-managed-second`
只是历史尝试/重试标签。`41/72`、`剩余31场景` 的口径作废（把 case 组与组内 scenario 混算）。

## 候选身份核验（2026-09-23 实测）

- 锁 `locks/pi/manifest.json`：identity=ed34c4e7…、recipe_digest=4374fea4…
- 修改前重新实算 `recipe_digest(仓库)` = 4374fea4…，与锁匹配（本轮修改源码后必须按正式
  resolve_lock 流程冻结新候选，历史 passed 不迁移）。
- 前后台作业：无归属明确的运行中 native/cold 长作业；仅余两个 /tmp pytest-120/pytest-122
  残留 `fake-helper.py supervise` 测试进程（9/22 起，来源为 mock 测试替身，未动）。
- 工具链实测：node v24.14.0、bun 1.4.0（agentcfg-pi-tools）、uv 0.12.13；默认 PATH 的 nvm
  也是 v24.14.0。/data≈291GB、/home≈23GB、/≈11GB 可用。
- 上一工具自报 “1839 pytest + 7 subtests、325 Node”：原始报告为
  `/tmp/mock-test-ed34c4e7-{v3,v5,v6}.json(.artifacts)`（通过轮），实数 **1836 passed +
  3 skipped + 7 subtests、325 node pass 0 fail**；v1/v2/v4 为 failed 历史轮。均在 /tmp，
  未入仓库归档，且不含候选身份字段——新候选必须以入档原始报告替代。

## 历史冷重建归档（只作历史，不改标签）

| 归档 | profile | 状态 | 备注 |
|---|---|---|---|
| pi-cold-32da4799 | 4 profile 双目标 | 名义 passed | 复核确认混入 4c043f8f 候选材料（pi-review-32da4799），不属 32da4799 身份证明 |
| pi-cold-4c043f8f | 4 profile 双目标 | 名义 passed | 旧候选，identity 不匹配当前锁 → stale |
| pi-cold-484f07e9 | cursor/default passed；codex/managed failed(first 过、第二目标 target-preparation-failed) | stale | 旧候选 |
| pi-cold-ed34c4e7 | 仅 pi-default：failed（first verified+7 组全过；第二目标 target-preparation-failed；引用的 native 子报告未随档） | 当前身份唯一归档，未完成 | 第二目标目录名即 “第二组 空格路径”，挂载视图已消失，无法核验其准备失败具体阶段 |

## 每 profile 两个干净目标的达成度（对任何候选均按当前契约重算）

- pi-default：ed34c4e7 下 1/2 目标（仅 first，7 case）。其余 0。
- pi-cursor：0/8 目标组完整（历史 5/5 均缺 readseek-tools 组合，属预期集缺口，不算验收）。
- pi-codex：0（历史 7 组属混候选归档）。
- pi-managed：0（历史 5 组属混候选归档）。

## 预期 case 集合（由生产 `native_cases()`/`scenarios()` + capability matrix 推导）

- pi-default：host-resources, migration-conflicts, model-delegate-replacement,
  budget-permissions, termination-recovery, readseek-tools, optional-services（7）
- pi-cursor：同 default 除 optional-services，**含 readseek-tools**（6）
  ——本轮修复 `pi_cold_rebuild.native_cases()` 与 `pi_validation_native` 的一致性
- pi-codex：host-resources, migration-conflicts, model-delegate-replacement,
  budget-permissions, termination-recovery, readseek-tools, codex-receipts（7）
- pi-managed：host-resources, migration-conflicts, taskkeeper-lifecycle,
  budget-permissions, termination-recovery（5）

## 接手核对确认的实现缺口（本轮集中修复）

1. `pi_cold_rebuild.native_cases()` 未给 pi-cursor 加 readseek-tools（与 validation 映射冲突）。
2. `pi_validation_sandbox.sandbox_argv()` 只读绑定 engine/git 的发行目录；Bun 宿主下独立
   Node worker 绑定目录未入 reads → Cursor 下 ReadSeek 必然不可见。
3. `pi_validation_native.execute()` 的沙箱 PATH 不含系统 bin 目录，fixture 的 `which("rg")`
   在 bwrap 内无法命中只读绑定的 /usr/bin/rg。
4. ReadSeek 场景 search/view/def/refs 仅查 `!isError`，未核验实际结果；search 的 JS 模式
   在 Python 夹具中不可能命中。
5. 登记器 `register-pi-evidence.py`：预期集合为自造常量（且 pi-cursor 同样缺 readseek），
   未复用生产 `validate_run_report`/`scenarios()`/`native_cases()`；不核对 scenario 集合
   完整性/顺序；cold 必需 case 集合过弱；主命令仍构造 `--case a+b` 与 `<installed-runtime>`
   占位、以 mtime 冒充时间；无真实格式正例与主入口测试。
6. 生产报告（native/standalone cold）不落真实 command；validation-run schema 无 command 字段。
7. tasks.md T098 备注“完整实现需要添加只停 owner 的 helper 命令”已过时——
   `scripts/pi-supervisor-macos.c` 已实现 OWNER 动作（只 SIGKILL owner、worker 存活、
   恢复路径带收据），macOS 实机缺机器保持 T108/T109 not-run；T106 备注中的 digest
   （1be31f1c/123979a7）同属 32da4799 时代旧事实。

## 仍保持的外部阻塞（不冒充通过）

- Linux live 10 项（4 required Task Keeper + 6 selected_optional）：selected_optional/
  not-run；`Pi --local`、专用项目与账号/服务绑定未准备。
- linux-arm64、macOS arm64/x86_64：无测试入口，保持 not-run（不是 not-selected）。
- macOS 原生恢复：仅替身测试与真实语义的完整协议实现，无实机证据。

## 2026-09-23 实际推进（本轮接手后）

- 第一批修复（cursor readseek 预期集、沙箱 Node 绑定、场景 PATH、九工具结果核验、
  登记器重写、报告 command 字段）后冻结 **fe140442 / 4374…→29ca0b48**：
  - mock 全量：1857 passed + 3 skipped + 7 subtests；325 Node pass 0 fail
    （`/tmp/mock-test-fe140442-r1.json(.artifacts)`，后移卷内暂存）。
  - 冷重建卷 `/data/1/weixiaoxian.wxx/pi-cold-fe140442-20260923`（预检通过后四路并行）：
    - pi-cursor 双目标：安装 verified、各 5/6 case 通过，**readseek-tools 两目标均 failed**；
      诊断（全新 HOME 复现）：`pi_validation_fixture.prepare_configuration` 的 readseek 分支
      整表替换插件列表，剥离 cursor provider 所有者插件 `pi-cursor`，适配器以
      `pi-authentication-owner` 拒绝（对外表现为 wrapped `adapter`）→ 属实现缺陷，非环境/磁盘。
    - 其余三路在报告写出前被主动终止（修复必然产生新候选，旧证据按契约 stale）。
    - 该卷整体保留为中止轮历史（含 `run-fe140442-aborted/`、readseek 失败报告与复现工件），
      不删除、不改写。
- 第二批修复（fixture readseek 分支改为“追加 pi-readseek 并保留 pi-cursor”+ 回归测试
  `tests/test_pi_cursor_readseek_binding.py::test_cursor_readseek_keeps_cursor_plugin_and_endpoint`；
  tests 不入 recipe digest）后冻结最终候选：

  **d3e0ea80e3e78f4e0417746fd69bc6c62765333c849b489f1a64b3313211daba**
  **recipe 8861251dd6295400cf115043ead75d21e374ea5d1e2817281d8fc15613edd793**

  - 最终 mock：1857 passed+4 skipped → 修复绑定测试假跳过后 5/5 通过、预期回到 3 skipped；
    正式 mock 以冷跑结束后的重跑报告归档。
  - 冷重建卷 `/data/1/weixiaoxian.wxx/pi-cold-d3e0ea80-20260923`：四 profile 双目标运行中，
    结果与登记在完成后逐项记录于本报告配套 final-report。

### d3e0ea80 轮（也已中止）

- pi-cursor 首目标 5/6 通过、**readseek-tools 仍 failed**。离线用锁内 readseek 原生 CLI
  在等价夹具上探查，确认真实缺口：
  1. `notes.txt` 是纯文本，无 AST → `def/refs/rename` 符号语义在其上不产生有效结果；
  2. search 的 `def $NAME($$$ARGS):` 单行模式匹配不到 Python 函数定义（需带体行
     `def $NAME($$$ARGS):\n  $$$BODY`，离线验证可命中 `test_bounded_change`）；
  3. view 对 code.txt 的 CLI 返回 “document format”拒绝，宿主扩展路径曾返回非错误行，
     断言收敛为 “投影含 original/code.txt 锚点”。
- 该轮四路驱动在 17:14–17:16 被外部机制整体回收（setsid 分离仍被清），非生产代码缺陷；
  关键 json 证据已摘存 `/data/1/weixiaoxian.wxx/pi-cold-aborted-evidence-20260923/`。

### 最终候选 97f9fbd4（进行中）

- **identity 97f9fbd47e7cdfca03975000bd771b433b6a75e07734f11ab70c8848a15528c8**
  **recipe beb61b1a26f0fff21c16e58c12d41d84d43d39790b0ad4d1d68da19d7abfe163**
- 第三批修复：provider 的 readseek 参数（notes.py + helper 符号 + 带体 search 模式）、
  TS 九步断言与 stray 白名单（含排除 `.readseek`）、mock 序列测试同步。
- mock：r1 因负载抖动 2 例失败（deployment mtime 秒边界、surrogate 读取竞态；隔离重跑通过）；
  **r2 干净：1861 passed + 7 subtests、325/325 Node、0 skipped**
  （`/tmp/mock-test-97f9fbd4-r2.json(.artifacts)`，将随登记归档）。
- 冷重建卷 `/data/1/weixiaoxian.wxx/pi-cold-97f9fbd4-20260923`；由会话内持久监督器串行
  监督：四路并行 cold → mock 暂存 → 视图内登记器 → report-only/check-release。

### 97f9fbd4 轮（也中止）与最终候选 9d6a9270

- 97f9fbd4 pi-cursor 双目标再次 5/6：readseek 在 **view 步骤**失败，失败工件实录
  `{'text': 'view does not support this document format', isError: false}` ——
  即历史 ed34c4e7/32da4799 的 “view_verified=true” 全是弱断言假通过：readSeek_view
  只支持真实文档（PDF 优先），对 txt 返回非错误的拒绝文本。
- 第四批修复（锁内 readseek CLI 离线逐项实证后落码）：夹具项目新增 603 字节确定性
  合成 `sample.pdf`（base64 内嵌，与离线实测字节一致）；view 步骤改为 sample.pdf 并
  断言 “sample + Page 1”；stray 白名单加 sample.pdf；相关 mock 179 项全绿。
- 监督器进程管理更正：此前 “驱动被外部回收” 的判断有误——`ps -ef` 长命令行截断导致
  误读；fe140442/d3e0ea80 中真正自然结束的只有写出终报的 cursor 路，其余路是被我在
  误判后 `rm -rf` 中止卷时终止的（并发写入者即其残留进程）。本轮监督器 + bracket 模式
  pgrep 已按真实进程状态核实。
- **最终候选 9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0**
  **recipe 85fc15c3babf58e768e2b09c25f7eac031644cac220c60c16d093c87cbb9257b**
  - mock 基线：1861 passed + 7 subtests、0 skipped、双 runner rc=0（冷跑前）；
    正式登记用 mock 在冷跑结束、系统空闲时重跑归档。
  - 卷 `/data/1/weixiaoxian.wxx/pi-cold-9d6a9270-20260923`，监督器四路并行冷重建运行中。

## 终态（2026-09-23 20:4x）

- 四路 cold 全部 `passed`（8/8 目标；110 scenario 行全带终止证明）；
- 正式 mock（与最终源码树同一时刻重跑 formal2）：1861 passed + 7 subtests、325/325
  Node、0 skipped；
- 登记：138 条 EvidenceRecord、scope r2；report-only rc0（81 passed/283 not-run/0 failed/
  0 stale），check-release rc1（release_approved=false，缺口=10 项 Linux live + 三平台）；
- 归档与自足复验：`docs/acceptance/pi-cold-9d6a9270/`（349 文件 + index.json sha256），
  对归档目录重跑 report-only 得 counts 与 input_digest 完全一致；
- 正式报告：`pi-final-report-9d6a9270.md`；支持矩阵已指向新快照；T098/T106 已按事实勾选。
