# OMP permission-control 验收记录

> 当前已按维护者要求改为官方宿主与独立插件，仓库实现及隔离验收完成；本机日常实例已按后续明确授权完成独立插件迁移（见验收 Phase 13）。下文 patched runtime/bridge 的构建和验收为历史记录，不继续构建发布，也不作为新插件通过证据。当前需求见[独立插件修订](../../specs/004-omp-permission-control/standalone-plugin.md)。本机部署是否切换须单独登记。

Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。 T072/T079/T080/Phase 9历史记录保留各自身份，真实模型质量不推广到新GLM备用；102/102历史账本与冻结输入不变。

## 状态定义

| 状态 | 使用条件 |
|---|---|
| 完成 | 已执行并记录命令、隔离环境、结果、范围和未覆盖项 |
| 进行中 | 已开始，但尚未得到完整结果 |
| 失败待决策 | 关键不变量失败，常规修复不能安全解决，需要主代理决定 |
| 环境不足未验证 | 已实际发现缺少工具链、资产、账号或平台；只影响对应验证组 |
| 尚未执行 | 尚未尝试，或真实宿主/模型尚未获得授权；不得写成环境不足或通过 |

## 记录模板

### `<组名>`

- 状态：`完成 | 进行中 | 失败待决策 | 环境不足未验证 | 尚未执行`
- 时间：`YYYY-MM-DD HH:MM TZ`
- 命令：`<实际命令；未执行时写“未执行”>`
- 隔离环境：`<HOME/XDG/OMP home/cache、网络、假依赖与哨兵>`
- 结果：`<退出码、计数或失败原因>`
- 范围：`<实际证明的行为>`
- 未覆盖：`<未运行的宿主、模型、平台或其它边界>`
- 证据身份：`<fixture/plugin/patch/runtime/model 摘要；不含秘密>`

## Phase 12：官方 OMP 与独立插件（2026-09-30，当前交付）

状态：仓库实现与限定范围验收完成；日常实例仍为之前的 patched 部署，本轮没有 sync/apply 日常配置、访问账号库或停止用户会话。T088—T092 完成。实际实现由两个 `gpt-5.6-sol / medium` executor 分别完成，主代理负责接口取舍、锁和最终验收。

当前使用官方 v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`，插件入口 `standalone.ts`，独立工具 `permission_bash`。没有修改上游源码或官方二进制，没有使用 bridge、私有 tiny worker 或同名原生工具替换。普通锁 identity 为 `a24d84ccd1ebb138a147d39de2f33771dab602064f216a03ce612bd1b39f136a`，plugin tree 为 `5e145c13475d03554fcc8e191e08bbc34223c8452c9a5be886f5fb9ba6e1b29c`，Linux x64 官方二进制 SHA256 为 `d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3`；执行后再次计算相同。旧 manifest/patch/build-inputs/真实模型结果和冻结样本不刷新，13 项保护输入摘要保持不变。旧 patched lock CLI 已移除，旧 builder CLI 返回 `omp-host-patching-retired`/2，旧 source-patch 测试 fixture 无条件退休；历史 build 实现仅保留取证。

| 验证组 | 实际结果与范围 |
|---|---|
| 独立插件 Bun | 锁定 Bun 1.4.0 对 `standalone.test.ts`：24 pass、0 fail、67 assertions；fake UI/provider/exec，无宿主或外部模型。验证完整命令审查、显式主审优先、故障备用、有效 ask/deny 不复审、严格 JSON、规则边界、无 UI、人工命令脱敏与控制字符转义、取消、模式切换、串行并发、加载期 API 限制、非零结果。 |
| 官方 SDK | 原版锁定 SDK 的 strict `tsgo --noEmit` 通过；Bun bundle 通过。只检查仓库插件代码，不应用历史宿主补丁。 |
| Python 管理器 | permission/schema+历史材料函数隔离单元 107 pass（历史宿主集成 7 组明确退休/skip）；discovery+dependencies 53 pass；adapter+pipeline 25 pass；正式 catalog 下 kernel+三方迁移 14 pass；CLI 5 pass；退休 builder 1 pass。各组存在重叠，不累加为总计。默认临时 HOME、fake backend/subprocess、网络阻断。 |
| 三方迁移 | 删除旧受管 permissionControl/disabledModelProviders 字段、创建 sidecar；保留未受管原生字段与 auth.db 哨兵；rollback 恢复旧字段并消费 sidecar 备份，外来 sidecar 冲突不覆盖。 |
| 真实官方宿主 | Linux glibc x64、临时 HOME、缓存官方二进制、本地固定 provider。`session_start` 加载成功；`ls -la` 实际 toolResult 恰一次，code 0、isError false；主审固定 503 一次→远程 Anthropic allow 一次；manual 切换与 `/new` 默认 smart 重置通过，宿主退出 0。 |
| 原生保护/来源 | 原生 bash 保持 prompt，独立工具内部审批；拒绝 YOLO。sidecar 缺失/漂移/未知键/重复键/链接与旧 patched variant 失败关闭；Cursor 模型和外来项目资源的前置拒绝分离。真实 OAuth 目录仍未验证。 |

真实宿主命令：`.venv/bin/python /tmp/rotom-permission-standalone-20260930/run-smoke.py`。隔离部署的 plan/apply/doctor 均退出 0；doctor 为 offline-ready、待变更 0、依赖 installed、部署运行包匹配。最后固定服务计数为 main 2 / primary 1 / remote 1 / skillDescriptions 0（描述已缓存）；前次修正 SSE 后的复验额外 skillDescriptions 4，单独分类。官方首次 skill 描述压缩会调用 smol，原版没有单独关闭压缩的公开配置；不能把它计为插件复审。服务和测试宿主已停止，外部模型请求及新增付费请求均为 0。

首次真实加载发现注册阶段调用 runtime action，已移至会话启动阶段并补回归；第二次发现固定服务把 skill 描述压缩混为远程审查且未提供其要求的 SSE，按上游 user prompt 签名独立分类并修正响应。二者修复后重新通过，不把失败当通过。

沙箱将 root 祖先 UID 映射为 65534，会被合法私人路径检查拒绝；有关 Python 测试和独立 smoke 提升到真实文件所有权环境执行，仍保持临时 HOME、fake/固定 provider 和限定网络，不放宽 UID/路径保护。

本地 tiny 的 installed-only 推理接口未公开，因此 fallback 当前显示 unavailable，失败后人工或无 UI 阻止；不能借用旧 bridge 的 tiny 通过结果。新插件不继承原生 service/job/PTY、direnv、interceptor、worktree 或后台执行语义。真实 Cursor OAuth、新 reviewer 模型质量、其它平台和日常迁移尚未执行，历史 102/102 模型额度不变。当前使用步骤见[指南](../../specs/004-omp-permission-control/quickstart.md)，完整摘要与路径见[机器可读证据](omp-permission-control-standalone-evidence.json)。

## Phase 1：骨架与冻结样本

- 状态：完成（T001/T002/T003/T005）
- 时间：2026-09-29 Asia/Shanghai
- 命令：
  - `.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks`
  - `rg` 统计 `specs/004-omp-permission-control/checklists/requirements.md` checkbox
  - `.venv/bin/python /tmp/generate_omp_permission_fixtures_v2.py`
  - `.venv/bin/python /tmp/validate_omp_permission_fixtures_v2.py`
  - `/tmp/rotom-omp-build-inputs/bin/bun --version`
  - `.venv/bin/python -m json.tool` 分别校验 `package.json`、`fixture-schema.json`、`labels.json`
  - `git diff --check` 与逐文件 `awk` 尾空白检查
- 隔离环境：仅仓库文件；不读取真实 HOME/XDG/OMP home，不访问网络，不启动子进程宿主或模型，不执行样本命令
- 结果：prerequisites 退出 0；requirements checklist 16/16；Bun 报告 1.4.0，package compatibility 为 `>=1.4.0` 且无 scripts/dependencies；JSON Schema Draft 2020-12 自检和 240 行逐例校验通过；`policy-safe=100`、`ask-deny=100`、`fault-state=40`；compound 分别为 50、40、0。safe 含 40 条 `low-risk-rule/modelCalls=0/messages=[]/clear` 与 60 条 `reviewer/modelCalls=1/unknown/完整自然语言授权/有效逐 effect bindings`，100 条 command、规范化 command 形态和用途均唯一；所有 safe segment 只使用 `pwd`、`ls`、`head`、`wc`、`rg`、`git status`、`git diff`、`git log`，无 glob。risk 按 20 hard deny、20 native human、20 unknown-effect pre-review gate、20 自然授权不足 reviewer ask、20 evidence 机械失败 reviewer ask 分组。40 条 fault 的状态语义和 event sequence 均唯一，review-start 与 modelCalls 一致，主审/总预算按 25/30 秒、取消事件在 1 秒内建模；tiny 有效 ask 保留 `fallback` 来源，无 UI 的 reviewer ask 保留 `reviewer` 来源链，action/effect 初始 cwd 一致。200 条 Bash command 唯一；真实用户请求来源、逐 effect scopeDigest、否定/撤销/路径范围/例外/指代和 binding 反例均通过只读校验；JSON 解析、digest 交叉核验、`git diff --check`、逐文件尾空白与末尾换行检查均通过
- 范围：T001、T002、T003、T005
- 未覆盖：扩展逻辑、宿主补丁、Bun 测试、构建、部署、真实宿主、真实模型和平台验证；没有运行或评判样本中的命令
- 证据身份：主代理已验收并正式冻结 tree SHA-256 `4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6`；摘要只覆盖 `fixture-schema.json`、`cases.jsonl`、`labels.json` 的相对路径与字节。旧候选 `f26cecfa45c8432256cf3e6073b2bad9f1d6ef559c33b8a240852e244cf91e19` 因模板化及优先级问题、第二候选 `7c5aeea45a4930adf489a223224eff035351d076863cd913c294cdbb02ec8b6c` 因命令范围/glob/来源链问题，在规则实现、样本命令执行和模型评测前经标签审查废弃，不属于按结果改标

## T004：正式构建输入

- 状态：完成
- 时间：2026-09-29 Asia/Shanghai
- 命令：
  - `.venv/bin/python -m pytest -q tests/test_omp_permission_build_inputs.py`
  - 在 `/tmp/rotom-omp-build-inputs/workspace` 显式执行 `bun install --frozen-lockfile --ignore-scripts`
  - 以正式 `build-inputs.lock.json` 调用 `verify_build_inputs`
- 隔离环境：准备目录 `/tmp/rotom-omp-build-inputs`；Bun 位于其 `bin/bun`；依赖安装是独立显式维护网络步骤，不属于默认测试；未运行宿主、native addon 或模型
- 结果：主代理实测 Python 隔离组 `42 passed in 0.58s`；严格 schema、缓存字节、离线依赖闭包与路径边界通过。新增换行路径反例先得到 `1 failed, 41 passed`，修正 schema 后重跑得到 `42 passed`。正式输入验证报告 `toolCount=1`、`dependencyArtifactCount=1`、`toolBytes=80761952`、`dependencyBytes=646784300`。准备过程使用 Bun 1.4.0，以未修改完整 lockfile 安装 414 包且禁用 scripts；官方同版 native leaf tgz 已按 npm SHA-512 验证
- 范围：T004 的来源账本、严格 build-inputs schema、正式输入锁及纯 Python 边界证据
- 未覆盖：构建 patched standalone、receipt、host/native addon、真实模型与真实宿主均未运行
- 证据身份：正式 `agents/omp/patches/permission-control/build-inputs.lock.json`；Bun 1.4.0 与一项完整离线依赖 artifact 均由该锁记录，不由 receipt 倒推

## 当前运行组（持续更新；下方保留历史证据）

| 组 | 当前状态 | 说明 |
|---|---|---|
| Python 隔离测试 | 完成 | Phase 11：266 passed / 96.59s，无跳过，正式身份和kernel受管渲染回归通过 |
| Bun 纯模块与 bridge 集成 | 完成 | core 291 pass / 1085 assertions；宿主bridge/transport、strict/format/lint结果见Phase 11 |
| 离线 patched standalone 构建 | 完成 | Phase 11 asset `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86`，367318216 bytes；正式receipt/manifest与完整身份链通过 |
| 真实宿主 smoke | 完成 | Phase 11 runtime `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`；临时HOME remote审批与new/resume、missing-plugin exit5、rollback；固定服务2/1/1，外部模型0；host JSON的remoteFallbackDelivery20260930 |
| 真实模型评测 | 完成（T080历史） | 旧runtime冻结240条：safe99/100免问、risk危险allow0/100、fault allow0/40；本轮无真实模型请求，新GLM备用质量未验证 |

## Foundation：配置、类型与离线交付校验（进行中）

- 状态：进行中；Python 与共享类型子组已通过，真实 patched bridge 子组尚在实现，T019 未通过整体门槛。
- 时间：2026-09-29 Asia/Shanghai。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_build_inputs.py tests/test_omp_permission_runtime.py`；`/tmp/run_omp_foundation.sh`。
- 隔离环境：pytest autouse 临时 HOME/XDG/OMP/缓存、网络和 subprocess 阻断；Bun 类型测试使用临时 HOME/XDG/OMP/cache 和 fetch 哨兵、实际 executable SHA 与 build-inputs 核对。
- 结果：合并 Python 组最近一次 114 passed；随后根据实际依赖 bundle 的 4416 个内部 hardlink 增加两个反例/正例，构建输入组单独 56 passed（包含此前缺模块、换行路径、缺 hardlink 支持的预期红灯和修复绿灯）。TypeScript 共享契约最终 59 pass/0 fail，217 expect；实现前缺 types.ts 的红灯已记录，未知字段名/控制字符/摘要尾换行反例通过。
- 范围：封闭配置、reviewer 引用、plugin/variant/config 一致性、原生 Bash prompt、原生对象 schema；共享三实体解析；构建 cache 身份/路径/闭包、精确 patch、archive 链接边界；合成 runtime manifest/receipt/实际资产摘要与组合身份，校验过程只读。
- 未覆盖：实际 patched wrapper、prepare/commit、构建产出、宿主/模型/部署/跨平台。基础 index.ts 当前故意报固定 unavailable，尚未实现控制器，不可用于日常加载。
- 执行模型：主代理负责 Python 及边界验收；executor `gpt-5.6-sol / medium` 负责共享类型；scout `gpt-5.6-luna / medium` 提供只读调用链证据。

### 显式构建过程的断网守卫检查

- 状态：完成。
- 命令：独立 Python 子进程调用 `deny_network()` 后分别创建 AF_INET/AF_INET6 socket；另以 `run_bun` 启动已验证摘要的 Bun `--version`。
- 隔离环境：临时 HOME/XDG、空 PATH、不继承代理/凭据；Linux x64 seccomp 限制继承到构建子进程。此项只启动构建工具，不启动 OMP。
- 结果：两类网络 socket 均以 errno 101 拒绝，没有发送请求；Bun 在断网限制下返回锁定版本 1.4.0。
- 范围：证明本机构建进程可启用网络守卫；构建工具版本检查可运行。
- 未覆盖：不是 patched standalone 构建或宿主握手，不证明平台普适兼容。

### 实际输入包恢复检查

- 状态：完成。
- 命令：独立 Python 调用 `extract_inputs`，将锁定 commit archive 去掉唯一根目录后解包，再按 input lock 解包全部依赖包，并校验源内 bun.lock 与 transformers/native 文件存在。
- 隔离环境：`/tmp/rotom-input-restore-*` 私有临时目录，结束后删除；全程纯 Python 文件操作，没有子进程/网络/宿主/native 加载/worker/模型。
- 结果：实际材料成功恢复。依赖包包含 3419 个目录、33904 个普通文件、55 个内部 symlink、4416 个内部 hardlink；逃逸链接/特殊设备反例仍失败关闭。
- 范围：证明正式 input bundle 可由构建器恢复，不依赖全局 node_modules 或再次安装。
- 未覆盖：编译和 runtime 加载尚未执行。

### 本轮 Python 最终增量

- 状态：完成（仅以下隔离组）。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_build_inputs.py tests/test_omp_permission_runtime.py`。
- 隔离环境：默认 pytest 临时 HOME/网络与进程哨兵；运行包和 receipt 均为合成不可执行文件。
- 结果：116 passed / 0 failed；`git diff --check` 无输出。
- 范围：以上配置、构建边界和纯运行锁校验；完整源码 TS harness 已写但尚未通过真实 BashTool/执行器基础门槛。
- 未覆盖：不代表 T019、T018 或故事阶段通过。首轮 generic adapter bridge 虽有11项测试通过，主代理因缺真实 BashTool/native executor 分割而未接受 T014/T015，executor 正在补齐；任务保持未勾。

### 真实执行器修订验收（进行中）

- 状态：进行中；T008/T013—T015 尚未验收。
- 命令：上述三项 Python suite 合并运行；只读核对 pinned source、修订 patch 与测试。
- 结果：Python `118 passed, 2 skipped in 1.08s`。两项新增测试是需要显式 Bun/source/dependency 材料的正式 TS harness，本次无参数运行按约定跳过，不算通过。executor 的修订补丁测试报告为 8 pass/37 assertions，但主代理发现重复 prepare 可覆盖 native 计划、部分副作用计数未接边界、提交路径遗漏原生输出/取消清理逻辑，要求原任务内修复，因此尚不采纳为基础完成证据。
- 覆盖发现：kernel 启用 interceptor，OMP 自动后台任务默认开启；常见 Bash 需要执行启动环境 snapshot。当前保守分支对这些条件均回到人工，不能宣称默认 kernel 已有免询问覆盖；不得通过关闭已有配置凑覆盖率。
- 执行模型：executor `gpt-5.6-sol / medium`；独立调用链复核 scout `gpt-5.6-luna / medium`；主代理决定复用原有 backend 结果与清理流程，不放宽资格条件。
- 未覆盖：真实宿主、native addon、worker、模型、构建和日常加载均未执行。

### 正式共享类型 harness

- 状态：完成（T019 的共享类型子组；不代表整个门槛通过）。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_control.py::test_permission_typescript_foundation --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies`。
- 隔离环境：独立输入锁逐字节校验后恢复到 pytest 临时目录，精确应用完整 series；临时 HOME/XDG/OMP、空 PATH、preload 与 Linux seccomp 断网；只运行 Bun test 单一指定文件。
- 结果：正式 pytest `1 passed in 49.07s`，底层共享类型 `59 pass / 0 fail / 217 expect`。初次 harness 因把 `--preload` 放在 `test` 前挂起，已终止相关进程并修复参数顺序；不能引用该初次运行作为通过证据。
- 未覆盖：真实 bridge 修订仍待验收，宿主、模型与构建未运行。

### T008/T013—T015/T019：基础门槛通过

- 状态：完成（基础范围）。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_build_inputs.py tests/test_omp_permission_runtime.py --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies`。
- 隔离环境：独立输入锁校验后的源码/依赖重新恢复、精确应用 series；临时 HOME/XDG/OMP，preload 接管真实 native/process/worker/网络/mkdir/环境加载/service/job 边界，Linux seccomp 阻断网络；不启动宿主。
- 结果：主代理正式合并 harness `120 passed in 44.21s`，包含配置/构建/runtime 118 项及两项 TS harness；底层共享类型59项、实际 patched bridge13项。executor 在同一 patch 的全新副本运行 bridge `13 pass / 0 fail / 64 assertions`、tsgo、oxlint、精确应用逐文件比较均通过。主代理完成关键增量复核：随机独立计划关联、永久失效、冻结参数直接消费、同步 Shell.run、复用原生完整结果/清理控制流及实际副作用哨兵。
- 证据身份：`0001-host-bridge.patch` SHA256 `f5beb0774bda7b96969edc2b8b5c6368db112eeadf1bb63f8c15fe65a49b3019`。
- 范围：严格 settings、默认官方路径不改、managed 丢配置仍保护、原生 deny/prompt/provider safety、纯 prepare、一次性 commit 与冻结身份。13项真实源码测试不代表任何真实 native 命令已执行。
- 未覆盖：reviewer、tiny、会话控制、默认 kernel 智能覆盖、实际运行包加载及模型质量；T018 构建开始执行，尚无成功产出证据。

### T018：实际离线早期构建

- 状态：完成（早期构建，不是最终交付）。
- 命令：`.venv/bin/python agents/omp/build-permission-control.py --source /tmp/rotom-omp-plan/commit.tar.gz --tool-cache /tmp/rotom-omp-build-inputs/tools --dependency-cache /tmp/rotom-omp-build-inputs/dependencies --artifact-cache /tmp/rotom-omp-permission-artifacts-early --platform linux-x64 --offline`；产出后纯 Python 调用 `validate_receipt`/`verify_file` 与独立输入锁交叉核验。
- 隔离环境：临时源码/依赖/HOME/XDG/OMP、空 PATH、锁定 Bun、Linux seccomp 网络拒绝；只编译与读写构建临时文件，不运行产物。
- 结果：初次失败明确为缺上游 `tool-views.generated.js`，诊断复跑确认同一原因。补齐 pinned 上游 stats 静态资源、tool views 生成步骤后正式构建退出0；修订后构建输入测试56通过。实际资产 SHA256 `c23eae748f58dae9d887438d71e8624bc6d471bf382cfd49d79ef53afbcd9b70`、size `366294216`；receipt SHA256 `322ae910e8737f307f9982f0675c29f07a889a499049104f8761426fdc9e59ed`。独立核对实际资产字节、严格 receipt、input lock、patch 与 build scripts 身份全部通过。
- 范围：证明本机可用已锁定准备材料离线生成声明 `permission-control/v1` 的 standalone。静态 ABI 声明校验不是运行时握手。
- 未覆盖：未运行 `omp --version`、CLI、宿主握手、真实 OMP native addon、worker、模型或部署；早期产物含未完成插件，占位入口不可用于日常。后续源码/插件/patch变化后，最终 T070 必须重新构建，不复用本摘要。

### 用户确认的默认 kernel 兼容扩展

- 状态：进行中。
- 用户决定：优先兼容现有 kernel，扩展规格与宿主实现，并增加验证；只改仓库，不动本机 OMP 配置。
- 已确认证据：interceptor 未命中为纯无副作用检查，可消除笼统不覆盖；auto-background 要分离审批后资源准备与最终同步启动，不能在 prepare 注册即运行的 job；Bash 冷启动 snapshot 必须保留人工环境初始化边界，已缓存文件也不能单独证明 persistent Shell 内部状态。新范围会保留不可核实动态状态的人工路径。
- 冻结样本保持原字节与标签；新增兼容场景独立记录，不能修改既有240条样本补指标。

### US1 纯策略与请求契约阶段验收

完成 T020/T021/T024/T025/T026。先有缺失行为的失败测试，再实现解析、固定策略排序和严格 reviewer 契约。主代理复核 policy 的硬边界、限制状态与模型 allow 合成；最新受锁 Bun 经 `run_typescript`、seccomp、临时 HOME/XDG、bridge preload 执行 `policy.test.ts` 与 `reviewer-contract.test.ts`，结果 **107 pass / 0 fail / 213 assertions**，日志 `/tmp/rotom-us1-policy-reviewer-guarded.log`。包含完整请求 24KiB、输出 512tokens/4KiB、重复 JSON key、真实来源和 UTF-8/effect scope、原始取消信号等反例。该组只证明纯模块，不证明宿主接线、真实模型语义或默认 kernel 已兼容。parser/policy 由 gpt-5.6-sol / medium executor 实现，reviewer 与阶段验收由主代理完成。

### US1 宿主私有许可核心阶段验收

完成 T023/T027。`permit.test.ts` 先因 controller 缺失失败，随后实现宿主私有 WeakMap 请求/人工响应/permit 链和最终同步消费。最新 guarded Bun 结果 **31 pass / 0 fail / 98 assertions**（`/tmp/rotom-us1-permit-guarded.log`）；strict tsgo 通过。覆盖完整绑定逐字段变化、原始取消、模式切换、迟到人工/模型、跨会话/请求/复制对象、单次消费和执行启动后释放队列。一次 Bun 异步 matcher 在触发取消前等待造成测试挂起，已终止并改用 Promise.catch 先订阅再触发取消；不是宿主测试通过证据。许可核心尚待真实 wrapper 接线，不能据纯核心测试声称已拦截实际宿主。

新增构建生成源码步骤把固定五个纯核心文件复制到 patched host；由 plugin tree 与 build script 的 receipt 摘要共同绑定，不嵌入或执行 index.ts。Python 构建输入组 **61 passed**，包括缺失/链接/覆盖拒绝与逐字节复制。早期 standalone/receipt 自此已过期，仅保留历史构建边界证据，最终产物必须 T070 重建。

### US4 纯锁与 receipt 契约增量

完成 T048/T051/T052；新反例先证明公开 receipt schema 缺失、实际插件变动未拒绝、ABI不兼容退出码错误，再修复。receipt 完整工具链/依赖/构建来源定义已进入 runtime schema `$defs.buildReceipt`，校验器复用同一结构。运行锁读取现在逐字节计算实际插件树，拒绝缺失、增加、修改与符号链接；构建器复用相同摘要算法。合法结构的未知 bridge ABI 退出5，结构错仍退出2。最新纯 Python 构建输入+runtime组 **97 passed**。该组没有部署、启动或生成正式发布资产；T053—T060仍未完成。

US2/US3正在实现纯命令、会话快照、模型选择和有界调用；最新完整纯 TS 隔离组 **226 pass / 0 fail / 670 assertions**（9 files，`/tmp/rotom-permission-pure-logic-guarded.log`），不包含仍在修正中的kernel宿主兼容组。T035/T037/T045等真实宿主接线未完成，不据此勾选整组。

### US4 profile 资产缓存消费增量

已实现 `OmpBackend` 根据 profile runtime_variant 选择独立 patched combined identity，只从当前 profile 的 `cache/artifacts/sha256/<digest>` 读取并验证已准备资产，复用现有 stage/激活/租约；receipt 绑定 patched lock、plugin、ABI。默认 official 路径不要求 patched lock。缺锁/缺资产返回5，不下载、编译、安装tiny或回退official smart。

首次运行安装测试被外层沙箱将 `/`、`/tmp` 的属主映射为65534挡在原有路径检查；没有改弱生产检查。自动审批允许在外层沙箱之外运行既有 conftest 隔离组（临时 HOME、网络/子进程/宿主仍被测试守卫阻断）：两项新增消费测试通过，相关 `tests/test_omp_dependencies.py tests/test_omp_dependencies_foundation.py` 共 **37 passed**。这仅证明消费、租约与原有后端回归，尚未包含完整 adapter/CLI/部署事务 T050/T054—T060。后续添加的激活前身份复核尚待下一次相关组验证。

## T049/T053/T054：权限运行包缓存、租约和显式锁命令

- 状态：完成。
- 命令：`.venv/bin/python -m pytest -q tests/test_cli.py tests/test_omp_permission_runtime.py tests/test_omp_dependencies.py tests/test_omp_dependencies_foundation.py`；另跑 `tests/test_omp_permission_runtime.py -k lock_`。
- 隔离环境：临时 HOME/XDG/仓库/cache、虚构资产、网络阻断、假进程；为验证生产 Tree 所有权约束使用经自动审查批准的非沙箱 pytest，不启动第三方宿主。
- 结果：183 passed；追加锁发布失败恢复 receipt 反例后，锁相关 4 passed。最初 CLI 测试错误地 mock 了通用 dispatch，而 OMP lock 实际直接调用 cmd_lock；改为拦截实际入口后通过，无真实仓库锁写入。
- 范围：官方路径不要求补丁锁；权限版仅消费 profile cache/artifacts 内容键，不调用下载、编译或安装；stage 验证后重读身份再激活，沿用租约与恢复；严格 CLI 参数组合；锁命令验证实际产物与全部输入再发布，manifest 发布失败恢复旧 receipt。
- 未覆盖：本组后端消费测试 mock 了静态交付证据，实际内容验证另由 runtime 组覆盖；完整管理器事务、最终真实构建/锁、真实宿主与模型仍未完成。

## 配置渲染与纯逻辑接线前检查（进行中）

- 状态：T050/T055/T056 进行中，T040—T046/T061/T063 的纯逻辑子集已验证，尚未据此勾选完整任务。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_runtime.py tests/test_omp_adapter.py tests/test_omp_discovery.py` 得到 82 passed；追加 `/permissionControl` 字段事务后运行 `-k 'adapter or transactions'` 得到 3 passed。
- 范围：单一 `/permissionControl` 受管字段、从实际交付锁计算 native identity/policy digest、拒绝错误 RenderContext、capture 不回收原生身份、官方→权限版→rollback 删除对象/入口且保留非受管偏好与账号哨兵、字段接管冲突。
- TypeScript：以 build-inputs 摘要核验的 Bun，复用 patched 源目录的 fake-native preload，通过 `run_typescript` 的断网/临时 HOME/禁止宿主边界执行纯模块 10 文件：239 pass、712 assertions；严格 tsgo 覆盖 index/audit/reviewer/模型与 deadline tests，退出 0。随后增加的 host 解析目标 helper 尚待下一次测试。
- 模型计数由宿主 `onInferenceStarted` 在实际推理边界报告；unavailable/unsupported/installed-only 资源检查不计推理。hostTiming 使前置上下文处理计入原始 30 秒预算，并让请求 ID 与 prepared plan 一致。
- 未覆盖：最终宿主 wrapper、注册、真实单次 transport/tiny worker、OOB 会话指令、最终构建与真实宿主/模型。当前不能宣称插件可用。

## T033—T036：会话状态、严格命令和扩展注册候选

- 状态：完成这些纯扩展/核心任务；实际宿主 OOB 接线 T037、整体故事门槛 T039 尚未完成。
- 命令：经锁验证 Bun 运行全部纯模块（run_typescript 的 seccomp/preload/temp HOME 保护），242 pass、727 assertions；涉及入口/状态/许可/解析器的 strict tsgo 通过。tsgo 首次暴露测试的 unknown.message 类型访问，改为匹配错误对象后通过；运行行为未改变。
- 范围：四条严格子命令、不合法输入无状态变化、状态/解释无模型调用、模式立即递增generation/撤销/abort、重复切换也失效、新建或恢复对象从配方默认初始化；注册只提交固定pluginId/ABI与候选review/command处理器，没有permit或execute能力。官方宿主缺API时入口固定unavailable。宿主loader仍必须核验真实来源树/运行身份。
- 工程分离：纯 session-commands.ts/audit.ts 加入构建器7文件core复制列表；入口index.ts不复制到宿主core；复制边界5个Python测试通过。
- 未覆盖：真实用户输入通道、宿主会话切换/取消入口、模型SDK/worker、真实宿主/模型和最终交付身份。

## T050/T055/T059 交付子集（进行中）

- 临时真实管理器端到端测试 `tests/test_omp_permission_runtime.py -k 'real_manager or runtime_damage'`：5 passed。先从复制的仓库当前字节计算合成official锁和patched receipt/资产，再运行validate/render/plan/sync/apply/fake run preflight/rollback。未使用正式待更新锁；合成资产是普通文本，唯一启动调用由fake_subprocess截获。
- 缺入口、入口内容漂移、runtime receipt ABI变更、binary损坏均退出5且spawn计数0。正常路径保留账号哨兵，rollback删除对象并消费备份；此前独立对象三方冲突测试通过。
- 尚缺默认kernel最终选择与reference、宿主发现健康/握手、pending故障注入及最终锁，保持完整任务未勾。

## T075/T076：默认kernel兼容与已批准stage

- 状态：完成本兼容增量；wrapper许可接线T028和最终T077仍在进行。
- 执行模型：接手executor `gpt-5.6-sol / medium`，主代理检查变更后的实际Shell共享占用、revoked不可复活、snapshot解析与最终消费失败清理；原executor交接中断后无并行写入。尝试复用scout继续SDK证据时工具返回agent thread limit，未声称完成该委派。
- 证据：锁定源码archive+Bun+依赖经项目harness验证，新鲜精确应用完整series并复制最新7core，foundation59、bridge19通过；随后增加staged callback失败反例，最终bridge20 pass/148 assertions。tsgo、相关oxlint、git apply whitespace check通过。
- 最终本阶段patch SHA256：`b372ff738a6711df4bdbad60401154d91104541b137d2180f7849344000b9a6e`；fresh source `/tmp/pytest-of-weixiaoxian.wxx/pytest-268/omp-permission-source0`；日志 `/tmp/rotom-host-t076-stage-cleanup-harness.log`、`/tmp/rotom-host-t076-stage-cleanup-bridge.log`、`/tmp/rotom-host-t076-stage-cleanup-tsgo.log`、`/tmp/rotom-host-t076-stage-cleanup-oxlint.log`、`/tmp/rotom-host-t076-stage-cleanup-apply-check.log`。
- 范围：interceptor miss/hit、冷snapshot批准前零生成、宿主生成snapshot与实际Shell连续性、共享Shell并发占用、未知mutation永久撤销、不相关简单函数不全局封锁、compound/pipe共享完整parser、direnv完整无配置搜索链；approved资源stage后最后同步start，原生进度/取消/artifact回调保留。onBeforeStart/同步start/启动前异步拒绝均清理一次且plan失效，started后失败不删活跃artifact、不恢复许可。
- 隔离：临时HOME、fake native/clock/UI/job边界、preload/seccomp；没有启动真实OMP/native/worker/模型。固定240fixture保持不变。
- 未覆盖：实际主审及宿主注册/可信上下文/permit wrapper接线；没有将本组假native结果称为真实shell或宿主验收。

## 合成运行包、恢复与脱敏增量

- 状态：完成本增量验证；T050/T055/T058/T059 整项仍待宿主健康及kernel最终配方，不提前勾选。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_runtime.py`，48 passed in 25.44s；受锁Bun经`run_typescript`执行纯模块10文件，244 pass / 0 fail / 786 assertions；index/audit/reviewer/会话状态相关strict tsgo退出0。
- 范围：合成端到端新增合法pending journal恢复，静态runtime fixture由确定文本字节生成且可逐字节复现，工具/依赖/source/manager/上游身份均存在对应原始材料，正式runtime读取函数核验整链；raw/URL编码/base64已知秘密、JSON密钥值、Authorization及未闭合私钥脱敏后禁止自动审查放行。
- 隔离环境：Python沿用临时HOME、假子进程和断网守卫；Tree事务测试使用自动审查批准的外层非沙箱执行。Bun使用preload、seccomp和临时HOME，无真实宿主、模型或worker。
- 静态fixture明确为不可执行文本，不修改正式运行锁；冻结240样本文件未改。脱敏无匹配不能证明任意秘密不存在，宿主还必须验证上下文与已知秘密来源。

## 冻结顺序勘误与评测统计子集

- 冻结文件本轮未修改。原生成器和原验收脚本实际按 `fixture-schema.json`、`cases.jsonl`、`labels.json` 的列举顺序计算，原 `FROZEN.md` 却把这个顺序称为 lexicographic；这是说明文字错误，不是字节漂移。按原生成算法重算仍为 `4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6`。本轮第一次按真正字典序重算得到 `41d2cea7dc2a6c9a1fcf17f3b24d8b9f422013a26c39e410d7bc84cce7646198` 并断言失败；已核对历史脚本定位原因，没有更换冻结摘要或重标样本。后续校验显式保留原生成顺序。
- 重新运行 `/tmp/validate_omp_permission_fixtures_v2.py` 成功：240条schema、标签统计、effect scope、机械/语义反例覆盖及唯一性通过；没有执行任何样本命令。T029原生询问基线仍未测量，整项保持未完成。
- 新增 `evaluation/fixtures.ts` 身份先于JSON解析，任何单字节漂移拒绝；`evaluation/report.ts` 只聚合已观察的结果，未测字段为null，fake不能给SC-001真实模型成绩，有限样本0误放行不作为一般安全保证。新增Bun报告组先因模块缺失失败，实现后6 pass/26 assertions；strict tsgo首次暴露类型错误，修复后退出0。这是T062/T065的统计子集，还不是完整可执行评测入口。
- runtime补充series链接反例先失败，修复为逐级普通路径检查后相关4项通过；内容相同的外部符号链接也拒绝。
- kernel配方已写入插件选择、smart默认和installed-only tiny意图，bash/task/eval均prompt。只通过TOML字段检查；最终reference、正式资产及锁仍待生成，T057未完成，当前不能声称kernel可日常使用。

## 注册/OOB基础与单次服务候选（进行中）

- executor `gpt-5.6-sol / medium` 的注册/OOB tranche 已阶段验收：完整0001 SHA256 `89229334e19c388439de8333970157378d98e65dc0c8996db9c1cefaa3bc5045`，fresh源码 `/tmp/pytest-of-weixiaoxian.wxx/pytest-274/omp-permission-source0`。独立输入恢复后foundation/bridge/identity三项pytest 3 passed in 50.82s；底层bridge20/148、identity3/8，tsgo、oxlint与pristine apply检查通过。主代理复核真实路径/树摘要、UTF-8排序、窄command服务和sticky contextIncomplete；wrapper自动许可主链尚未完成，T022/T028整项不勾选。
- 新身份测试最初与全局node:fs mock组合在Bun discovery阶段挂起，两种加载策略均失败；主代理决定独立identity.preload保留真实临时文件系统，继续阻断fetch/process/Worker并继承seccomp。没有通过替换生产身份校验来获取通过。
- 主代理编写0002单次服务候选；`createReviewOnce`按宿主请求ID、模型、原始信封、deadline及原始signal绑定一次请求，标准API-key两协议一次fetch，无SDK重试/跳转/模型切换；OAuth/特殊协议保留unsupported。凭据只在registry闭包内解析。`createTinyInstalledOnly`只读完整安装候选目录，在独立进程成功local-only加载后才允许生成，并在完成/取消/最长5秒时终止该进程；不接标题socket、不调用下载/安装/修复函数。CLI专用worker分发属于构建源码，默认测试没有执行该入口。
- 服务候选测试经identity.preload、临时HOME和seccomp：13 pass / 0 fail / 95 assertions，日志 `/tmp/rotom-permission-services-guarded.log`。所有fetch、进程和模型加载均为fake；真实installed loader使用注入的假runtime，验证local_files_only、remote关闭、不启推理与缺资源拒绝。不能据此声称真实tiny可加载或模型质量合格。
- 全project tsgo首次暴露服务返回timeout/cancelled与core类型不一致、clock基准及测试fetch类型问题，已统一performance.now单调时间并补充ModelReply状态；后续类型检查通过。追加复用既有sharp stub/resolver的候选仍需下一次fresh完整series检查。0002仍在审查，T045未完成。
- 再次尝试独立scout取tiny证据被agent thread limit拒绝，主代理改为只读锁定源码与依赖源码，没有虚报scout结果；现有executor继续独占0001，主代理独占0002。

## T040—T043：审查选择、fallback与预算纯核心验收

- 状态：完成T040/T041/T042/T043；生产会话变化hook、实际wrapper服务接线与状态/审计整合仍未完成，T044—T047不勾选。
- 受锁Bun+identity.preload+seccomp+临时HOME执行model-selection/fallback/deadline/reviewer-contract四文件，75 pass / 0 fail / 171 assertions，日志 `/tmp/rotom-permission-model-core-guarded.log`。覆盖显式/会话选择、无效歧义引用、完整信封/严格JSON、一次主审、fallback原因与上限、包含前处理的30秒预算、原始取消/旧generation与迟到响应；宿主认证超时尚未发推理时主审计数0，取消不能触发tiny。
- 服务候选完整series fresh应用后13项通过；追加endpoint漂移反例及原始host取消绑定后，服务/tiny/fallback合并26 pass/140 assertions，日志 `/tmp/rotom-permission-services-final-guarded.log`。最新0002 SHA256 `44c724ed765a6e54d56ba322309cd2edf64fde40595556555d8de63fd36ef1d7`；在pristine CLI与空新增文件基础精确应用，逐文件与已测试源码相同比较通过，oxlint通过。
- full-project tsgo在本次fresh目录遇到并行executor尚未发布的`execution-host`模块：bridge测试已引用该模块而正式0001仍是上一阶段；记录为进行中集成状态，不伪称最终全项目通过。此前完整tsgo通过只属于上一候选；服务与CLI将使用限定配置单独检查，最终全project留给源码/测试同步交回后的验收。
- 所有结果都是隔离工程证据；没有联网、真实推理、真实tiny pipeline加载或Bash执行，不能计算SC-001真实模型免询问成绩。

## 两阶段认证、失败清理与原生基线增量（进行中）

- 宿主 wrapper tranche：executor `gpt-5.6-sol / medium` 交回0001 SHA256 `99f89b73646f0d9f612f175d4d04b8ffa69f7c34387d821749e2ea3a017ec582`，fresh276基础/bridge/身份/服务4项pytest通过（56.97s），bridge21/155；主代理复核native品牌、私有ledger与消费时序。仍需主审接线、工具默认与命令级prompt区分、最终命令原生规则复核、完整生命周期撤销；不勾T022/T028整项。
- 主代理将0002主服务改为 `prepareReviewOnce → host-only knownSecrets → bind(redactedEnvelope)`：认证与配置headers各解析一次，端点/凭据/input/request/model/原始signal/deadline固定，发出推理前再次拒绝端点漂移；认证本身不响应abort时也有宿主计时上限。准备失败不冒充完整脱敏，回到人工。兼容函数保留用于纯服务测试，生产接线使用两阶段API。
- 新鲜完整series的service pytest：1 passed（61.91s）。补齐类型/截止时间快照后，identity.preload+seccomp+临时HOME的服务/tiny组17 pass、129 assertions；日志 `/tmp/rotom-permission-prepared-services.log`。全project strict tsgo最初发现新增测试枚举推断错误，修复后退出0。没有真实fetch/worker/模型；真实主审和tiny均未验证。
- 新增serialized失败stage反例先失败（pending许可未撤销），随后core仅在operation失败时abort请求，保留成功start后可能仍被执行器持有的signal。permit/session-state/session-command组合42 pass、183 assertions；日志 `/tmp/rotom-permission-failure-cleanup.log`。生产wrapper异常清理由executor继续接线。
- 原生规则基线独立组1 pass、211 assertions，直接调用真实 `resolveApproval`/`BashTool.approval`，不调用execute。固定200条Bash：safe=48 allow/52 prompt/0 deny（其中40条compound prompt），ask-deny=5 allow/85 prompt/10 deny（其中40条compound prompt）；40状态序列对此基线不适用。结果存于冻结摘要之外的 `tests/fixtures/omp/permission-control/native-baseline.json`，日志 `/tmp/rotom-permission-native-baseline.log`。这不是插件成绩，也不表示5个原生allow在给定用户限制下合理。Python输入helper初版误把TOML嵌套表当点号字段而失败，修复后重跑通过；冻结三文件和FROZEN.md均未修改。
- 完整合成runtime组重新运行：49 passed in 24.51s。使用经自动审查批准的外层pytest、隔离临时HOME/仓库、假进程与断网守卫；不启动第三方宿主，不改本机配置。


## Kernel参考与被动认证边界（进行中）

- kernel reference加入权限对象静态字段、生成摘要字段清单及受管插件入口；不把最终交付摘要嵌入受锁reference，避免身份循环。kernel测试改为临时仓库中实际字节形成的合成锁/资产，真实manager消费合成资产后才进入fake run。初轮12 passed/1 failed，失败是既有凭据提示文案已改变；修正断言后该测试1 passed（10.62s），其余未重跑。所有原生HOME/会话/认证哨兵仍属临时测试环境。
- 代码审查发现通用OMP凭据/header resolver可调用`!command`。0002现要求宿主被动认证证明和专用同步header解析；缺证明、命令来源、未知resolver均在auth前unsupported，主审调用计数0。0001的证明/物化实现在executor接线中，尚未据此完成T045。
- service假registry边界12 pass/114 assertions，日志`/tmp/rotom-permission-passive-services.log`；限定service/CLI strict tsgo退出0。此处假registry测试证明0002遵守宿主证明接口，真实registry路径仍待独立反例。此前两阶段候选0002曾通过pristine精确应用及逐文件相同校验（SHA c3a0db467ca671b763a7289d16e9fd48a5099ab10f5b9bc54cc7eaae43e16f82），被动接口新增后须重新fresh验收。
- 三份支持/架构/依赖文档候选由`gpt-5.6-sol / medium` executor完成；链接与空白检查通过。主代理要求并已修正文档中的静态preflight和启动后插件加载状态区别：管理器不能在不启动时声称已验证注册/握手。T067—T069依赖的最终组尚未完成，暂不勾任务。

### 宿主主审接线与评测入口复核（2026-09-29，继续实施）

状态：进行中。executor `gpt-5.6-sol / medium` 交付的宿主补丁
`0001=194faf2abdc75e1e976629d66df4cd725cdbc941882ad3fd9a92bf06720aa910`，与
`0002=4852427c6ff44d9f5b59f2edf2fdd8e65f11ac4f545e6df1037adad7884a76d6`
在锁定上游新副本 `/tmp/pytest-of-weixiaoxian.wxx/pytest-284/omp-permission-source0`
通过 5 个 pytest harness 组（44.33 秒），桥接组为 27 pass / 189 assertions；
完整 coding-agent strict tsgo 和相关 oxlint 通过。日志为
`/tmp/rotom-omp-host-tranche-final.log`、`/tmp/rotom-omp-host-tranche-tsgo.log`、
`/tmp/rotom-omp-host-tranche-oxlint.log`。全部仍为临时 HOME、锁定 Bun、seccomp
阻断网络、fake native/provider/worker 的源码集成证据。

主代理验收发现：人工批准的审计链需补齐，许可审计需记录 consumed/invalidated 终态；
模型候选需与宿主捕获的实际回包绑定；状态覆盖和 fallback 可用性不能停留在初始占位值。
这些修复已重新分配，故本轮不勾选完整宿主/审计故事。普通只读命令的真实证明也继续扩展：
锁定 `crates/pi-shell/src/shell.rs` 的 utility builtins 包含 ls/head/wc/rg，
不是必须经 PATH 查找外部程序；禁用开关、shell 连续性和文件目标仍须实际验证。
不得用现有 pwd 测试外推其它命令覆盖，也不为扩大覆盖改写命令或环境。

评测入口定向修复完成：real adapter 在实际发送处唯一计数，真实模式使用单调时钟与
可取消计时器；执行 adapter import 前检查参数、冻结集和源码身份；请求与所有授权消息
同时核对真实 user 来源。fake 的时间/未观察故障保持 null 和固定未验证理由。
定向 guarded Bun 为 17 pass / 76 assertions，strict tsgo、oxlint、diff check 通过；
日志 `/tmp/rotom-permission-evaluation-targeted.log`。240 例报告的命令执行数为 0，
SC-001 为 null；当时插件摘要为
`f5c64940352579ab334d125a30f7298075ec936790b8cec7d152aff2218ded24`。
这仅是只审查评测工具的隔离证据，未调用真实模型、未测得真实免询问率。

### 有界文件证明与核心候选（2026-09-29）

状态：纯模块完成，宿主整体接线仍在验收。主代理通过锁定 Bun、临时 HOME、identity
preload 和 seccomp 运行全部插件测试：263 pass / 880 assertions，日志
`/tmp/rotom-permission-core-final-candidate.log`。随后为宿主证明收集器增加来自同一真实
parser 的 `hasInputRedirection` 标志，定向 policy 组 57 pass / 150 assertions，日志
`/tmp/rotom-permission-input-redirection.log`。这些计数不代表最终构建或真实模型已通过。

executor `gpt-5.6-sol / medium` 实现的 host read-proof 模块候选摘要为
`8997e173b15a4fa22594ff7eaa27c5649a6ddd323115e44247e8598ba2f21913`，
对应隔离测试摘要为 `7f867a923e078e52f306b128272a9b532e10357f0b487a6038f2be5522b8569a`。
定向 guarded Bun 11 pass / 35 assertions，strict tsgo、定向 oxlint/oxfmt 与 diff 检查通过。
目标证明逐级拒绝符号链接/特殊文件、秘密路径和逃逸；一份请求共享 250ms、4096 次操作、
256 MiB 元数据计费上限，目录有界逐项读取，两次扫描必须一致。祖先只绑定身份和权限，
避免无关祖先目录的时间变化导致错误失效；实际目标和读取成员仍绑定完整 stat。

支持锁定内置 pwd、受限 ls/head/wc、rg 显式普通文件或管道。rg 目录分支存在额外
parent/global ignore 读取，Git 仍缺完整外部效果证明，均保持人工；输入重定向和 literal
`cwd` 哨兵歧义也保持人工。宿主在最后同步检查中重新收集 context 并核对摘要，尚不能把
纯模块结果称为真实 Shell 或整个 wrapper 通过。未运行真实宿主、native、模型、worker 或网络。

### 最终文件证明边界与 kernel 默认值修复（2026-09-29）

状态：进行中，等待完整 series 末次集成。主代理新增 `ls -- -d` 回归，证明选项结束符之后
的文件名不能被当成 `-d` 选项而漏掉目录成员。修复前 11 pass / 1 fail，修复后
12 pass / 39 assertions，日志 `/tmp/rotom-permission-ls-literal-red.log` 与
`/tmp/rotom-permission-ls-literal-green.log`。只解析 `--` 之前且首个位置参数之前的选项，
其后不明确的选项顺序保持人工；真实字面目录仍按成员扫描。模块最新摘要
`c5e9bfd837966d851fac2a547fe992c41dba658c76b7dc51c049e749b4260220`，测试摘要
`854efdd2c33d9fc4f8887e03200ff0fdc4cf1abc56120202dd7e4428c85cd480`。

实际 manager-rendered kernel 互通测试另发现宿主 `worktree.clone` 默认 true，而 prepare
曾只按开关加 `worktree-rewrite`，造成 warm `pwd` 仍人工。主代理根据锁定上游实际代码
决定保留 kernel 配方：调用已有纯 `rewriteGitWorktreeAdd(command, resolveCliEntryCmd())`
判断是否真的改写；无变化不排除覆盖，实际命中仍走人工原路径，不改写待审批命令来争取覆盖。
此项属于用户已批准的现有 kernel 兼容；没有修改本机配置，也没有执行 worktree/git/shell。
互通测试保留失败证据，等待同一实际配置在修复补丁上重新验证。

## 最终宿主与实际 kernel 互通验收（T022—T069、T077）

- 状态：完成（隔离实现与测试；最终交付身份见后续 T070/T071）。
- 时间：2026-09-29 Asia/Shanghai。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_control.py --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies`；另定向运行 `tests/test_omp_permission_runtime.py::test_manager_rendered_kernel_object_interoperates_with_patched_host`（相同材料）。
- 结果：最终 host harness **40 passed in 49.94s**；实际 kernel 互通 **1 passed in 47.58s**；新鲜补丁源码的完整 coding-agent strict tsgo 与改动面 oxlint 退出 0。host harness 包含 29 项 bridge、identity、主审/tiny、原生基线、read-proof 和全部插件核心测试。
- 关键证据：宿主独立捕获 fake fetch 的真实原始主审输出，合法 allow 正例可执行且无第二次 prompt；扩展将原始 ask 篡改为 allow 仍不能放行；不合条件 tiny 不创建进程/worker；非合作 review 受总预算/取消约束；审计保留人工链与终态，摘要按会话加盐；新会话/恢复/切换/凭据变化撤销旧许可。
- 实际 kernel 互通使用管理器 candidate/apply 生成的同一 config.yml 对象，验证 host 严格 schema、ABI/plugin/runtime identity、Bash/Task/Eval prompt 和原生 deny；保留 direnv auto/interceptor/auto-background/worktree.clone 默认值。冷态不执行 native；人工暖机一次后 pwd eligible。worktree.clone 的纯 no-op 不再阻塞，实际 git worktree rewrite 仍需人工。
- 隔离环境：临时 HOME/XDG/OMP/cache，seccomp 阻断网络；native、UI、direnv、provider、installed loader 均使用哨兵/假实现。管理器测试因 sandbox UID 映射使用获批的 pytest 运行环境，临时目录与阻断边界不变。
- 最终补丁：0001 SHA-256 `0f963e3aabb55007274a50b7edb2dbd12235c6a6c3d82484ba300f3acc2f6102`；0002 `4852427c6ff44d9f5b59f2edf2fdd8e65f11ac4f545e6df1037adad7884a76d6`。源码从固定 commit 归档重新解包并按完整 series 应用。read-proof SHA-256 `c5e9bfd837966d851fac2a547fe992c41dba658c76b7dc51c049e749b4260220`。
- 未覆盖：未运行 OMP CLI、真实 native Shell、实际 direnv、provider、tiny worker 或模型；Git、递归 rg、输入重定向、隐藏枚举、非 numeric 长格式 ls、绝对与逃逸路径继续保守人工。该证据不计算真实模型免询问率。
- 执行模型：两名复用 executor 均为 `gpt-5.6-sol / medium`，分别完成宿主和互通测试；主代理负责关键不变量、边界修复与最终验收。本阶段未新增 scout。

## T070：最终源码离线构建与正式身份

- 状态：完成。时间：2026-09-29 Asia/Shanghai。
- 顺序：确认生产插件与完整 series 稳定后，按真实资源字节更新 catalog 与 official recipe/resource/package identity，保留官方 source/assets/upstream/commit/tag；再执行下列构建；最后由 `lock_prepared_runtime` 核对现有资产并生成正式独立 receipt/manifest，不手写摘要。
- 构建命令：`.venv/bin/python agents/omp/build-permission-control.py --offline --platform linux-x64 --source /tmp/rotom-omp-plan/commit.tar.gz --tool-cache /tmp/rotom-omp-build-inputs/tools --dependency-cache /tmp/rotom-omp-build-inputs/dependencies --artifact-cache /tmp/rotom-omp-permission-artifacts-final-20260929`。
- 隔离环境：临时 HOME/XDG/OMP、清空凭据/代理、Linux seccomp 阻断 INET，已锁定 Bun 1.4.0 与完整离线依赖；没有安装/下载、没有运行产出的 OMP（包括 `--version`）、没有加载 native Shell 或 tiny。
- 结果：退出 0，实际 standalone **367256776 bytes**，`hostExecuted=false`；正式 manifest 与 receipt 通过 `_validate_delivery`，验证实际资产、插件、完整 patch、ABI 声明、构建输入/脚本/toolchain/dependency 及 official identity。资产保存在本次临时构建缓存，未部署到本机实例，也未提交二进制。

| 身份 | SHA-256 |
|---|---|
| standalone asset | `a2ba1be6269f2874b9475687acbc39fa148ec1f3fa836e214c6481feee632d2a` |
| official recipe | `0504c78b719146cf72ad2030940002d4fd06f52c2a6b6031b102f8c0e3c50be9` |
| patched manifest | `fb731171f6ccb831a5d3f9c66fa0913e4dae3464040adf4cf16246e0c10855cb` |
| receipt | `06c4c9fc326776f5b0ea6395a4251fb5d2ea80bc58da60292406627d3c43defd` |
| plugin tree | `203d1d0bb14f65fad52888b23e05361f2e6b6c428334863b71b34eb2703997a8` |
| combined runtime（manifest 外） | `357acc7e1fb9d16dd14b29d77d6cff9decf69b335f856e4f622205c960107f01` |
| build-inputs | `d474ff9925eeebaa7f896b4a1e62178814ad96f911006635cf063153fa5cbb2c` |

- 正式文件：[manifest](../../locks/omp/permission-control/manifest.json)、[receipt](../../locks/omp/permission-control/build-receipt.json)。完整材料身份均保存在 receipt；combined identity 由 official/patched/platform/plugin 计算，没有写入输入锁或制造循环依赖。
- 未覆盖：编译与静态 ABI 检查不是实际加载/握手。T072 真实宿主与 T073 真实模型尚未执行；不能据此宣布日常可用或模型免询问率达标。

## T071：最终身份一致回归与静态验收

- 状态：完成。时间：2026-09-29 Asia/Shanghai。
- 命令：`.venv/bin/python -m pytest -q tests/test_omp_adapter.py tests/test_omp_dependencies.py tests/test_omp_kernel.py tests/test_runtime.py tests/test_dsh_pipeline.py tests/test_pi_pipeline.py tests/test_omp_permission_control.py tests/test_omp_permission_runtime.py tests/test_omp_permission_build_inputs.py --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies`。
- 首次结果：**215 passed / 1 failed in 114.16s**，无跳过。唯一失败 `test_pi_missing_model_key_still_launches_and_damaged_runtime_fails` 使用旧提示“可选模型凭据未配置”，而当前已有 runtime 实现返回“1 个模型 key 未填写；工具仍可启动，对应模型暂不可调用。”；启动返回 0。核对实际来源后仅更新该测试文案并增加 stderr 秘密哨兵，保留缺 key 可启动、环境无秘密和损坏运行包不启动断言。
- 修复验证：相同隔离边界下定向该 Pi 测试，**1 passed in 3.66s**；没有生产代码变更，不重跑已通过的其它 215 项。本轮 216 个用例均已有通过证据，但不表述为一次全绿运行。完整首轮日志 `/tmp/rotom-permission-final-regression.log`。
- 身份：测试前后均由 `read_permission_runtime` 对 T070 真实 artifact cache 交叉核验，combined identity 为 `357acc7e1fb9d16dd14b29d77d6cff9decf69b335f856e4f622205c960107f01`；测试材料固定 archive/Bun/dependency，应用最终完整 series。kernel reference 的静态字段、由实际字节生成的 plugin/runtime identity 和原生对象均由本轮 kernel/互通组验证。生产插件、补丁与构建输入未再变化。
- 额外静态验证：冻结 240 条及原 tree digest `4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6` 校验通过（冻结顺序勘误保留原算法）；permission/runtime/build-inputs/native schema 自检通过；两个相关 local 示例通过真实公共 catalog 的 adapter-aware schema 校验；77 个任务 ID 无重复/缺号，spec 包含 FR-001—037 与 SC-001—012；本规格及验收文档 35 个本地链接检查通过。
- 静态检查说明：直接用未注入 adapter 的基础 local schema 检查通用示例时，adapter_options 被基础封闭占位拒绝；改用生产 `load_public_catalog` 与 `validate_document(..., adapter_schemas=...)` 后两个示例通过，未放宽 schema 或修改示例。
- 隔离环境：pytest 临时 HOME/XDG/OMP/private cache、假进程和网络哨兵；Bun 子进程额外受 seccomp 阻断网络。未启动真实 OMP/Pi/DSH、native Shell、worker 或模型，未修改本机配置。
- 实际模型：`gpt-5.6-sol / medium` executor 修正单项旧断言，主代理验收 diff、完整回归与实际资产身份。
- 后置 hook：`.specify/extensions.yml` 不存在，无已注册的 after_implement hook。
- 尚未执行：T072 真实宿主 smoke 与 T073 真实模型评测；不记为环境不足，不以 fake 结果证明 SC-001 免询问率或真实授权语义准确率。


## T070/T071/T072 最终复验（2026-09-29）

真实宿主发现的三个集成问题已闭合。最终身份、实际运行证据、失败与修复过程、有限模型调用账目见[真实宿主报告](omp-permission-control-host-smoke.md)和[结构化证据](omp-permission-control-host-smoke-evidence.json)。本阶段历史 standalone SHA 为 `da436eff28dab0d72249e5a3c69f7e3f56e693f6b739e3069ac11fa274e66f83`，combined runtime 为 `bf6f18b45fc80c177f6644e96366b978bb3d524b0d476664d228e4a7de48bc08`；它保留为 T072 证据身份，不代表后续 T079/T080 产物。

- bridge先红后绿，最终31 tests/253 assertions；fresh完整series、strict TypeScript、oxlint/oxfmt、pristine apply-check均通过。
- 最终受影响pytest三组103 passed in 92.46s，日志 `/tmp/rotom-permission-final-review-regression.log`。此前已通过的其它适配器组没有相关源码变化，不重复扩大测试范围。
- T072真实最终宿主：status/manual/smart/explain/new/resume、缺插件pre-spawn故障关闭、固定review allow无人工/一次执行/一次消费，以及真实临时回滚均通过。固定provider不具有外部模型调用能力。
- 用户授权的实际外部模型请求总计3次，均为main；并非T073冻结评测，也未证明真实reviewer风险判断质量。真实tiny未加载或下载。
- 冻结240条样本字节保持 `4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6`。本轮最终验证脚本确认数量、schema与摘要，未修改标签。
- 日常本机OMP配置未修改，临时服务均停止。当前任务76/77，唯一未完成T073；不存在待用户处理的实现缺陷或当前环境阻塞。

## T073 授权评测准备与当前身份（2026-09-30）

- 状态：进行中；已授权，尚无本轮真实 reviewer 请求和质量结果。完整范围、机械 fixture 修正与调用账本见[真实模型评测报告](omp-permission-control-model-evaluation.md)。
- 变更边界：评测 runner 在首次真实请求前修复 14 条机械 evidence fixture 及指标分母/含义，冻结 240 条样本、标签和 tree digest 未修改。源码两份 host patch SHA 未变化；official recipe 与 plugin tree 因评测实现字节变化更新。
- 本阶段当时身份：official recipe `1829506312ed265b8d849f0d79678dfcdbd1b7a8fbcf9646073b1a2d7212b6ea`；plugin tree `30891b8ae7e7ce67e04d9bcabec6baac17431cd11c9a556f63ac6971b4a2df65`；standalone `cacb2a43945f8e05a25986208d7cc672afd8f1032ad17a834ff8e1e2e7dc8c7c`（367264968 bytes）；patched manifest `2bf5cb3aaa18841d994ea620e739c0390524407772952af57eb7eb04ca72a748`；receipt `79cfe1c7ab9f2111226f96e452ce3ab5145b1a7bb27409d0c58f55f3b3794b81`；combined runtime `28e85f1f871fabd39fbf3882f654c630df53ce384a4e851ec688e439358e3107`。这些值是 T079 之前的历史链。
- 回归：最终受影响 pytest **103 passed in 104.39s**，日志 `/tmp/rotom-permission-eval-final-pytest.log`。
- 新链宿主复核：真实 standalone lifecycle 为 healthy，TUI new/resume 均保持 smart，结果为 PASS；结构化结果 `/tmp/rotom-permission-host-smoke-20260929/lifecycle-result.json`。该复核模型调用为 0，不重写 T072 在 combined runtime `bf6f18b45fc80c177f6644e96366b978bb3d524b0d476664d228e4a7de48bc08` 上的历史运行和三次真实 main 请求账目。
- 未覆盖：T073 真实 reviewer 推理尚未开始，不记录 SC-001/SC-002 成绩，不预测结果，不勾选任务。

## T079 机械引用与专用 reviewer 修复（2026-09-30）

- 状态：实现与 plugin/strict 验证完成；新链 lifecycle 已通过，最终材料化回归103 passed/87.97s，scripted auto-allow及回滚通过；T073最终版质量评测待执行。
- 行为：宿主根据实际用户消息正文重新计算 `utf8ByteLength`。`allow` 的每个 effect 必须各有一个覆盖整条消息的引用，字节区间恰为 `0..utf8ByteLength`；`ask`/`deny` 的合法部分引用继续保留，不因不能 allow 而丢弃证据。Kimi exact model 的专用 permission review 请求关闭思考，不改变普通主模型请求设置。
- 定向结果：plugin **269 passed / 972 assertions**，strict 检查通过。最终材料化回归**103 passed/87.97s**；首轮两条旧partial fake allow夹具已按整消息契约修复，生产与锁字节未变。
- 本阶段当时身份：official recipe `f221b9d0e6cf05f0cdb440848649a7fa294c669924f2b3dc31df7d75dea83615`；plugin tree `7a3b5054a5ee199526b6f11d33dc9f8ee700365824e66a7b715582838dd80447`；standalone `d12934cb53383e70103aaf937b9b7475efbabc3cf50b3be9fb244355d76ec786`（367269064 bytes）；patched manifest `6de0f69ad46455c67c6635e35a14e5c3da09164d5d1d2396a6d065fd6dee5342`；receipt `ea5a765228e3fae31b4bbe5cb5659585ec5a3f46dd0396fe1cd0e06d64f0a470`；combined runtime `fcdf5e32046deec53295f3590a87f12b9a2e3d415ff241af348b0be930d0f3d0`。这些值是 T080 之前的历史链。
- Patch 身份：0001 仍为 `b9c597b0f60c6e2b58855828602cf65495b79715664a25047d28d49677faaaf6`；0002 更新为 `be830a4238d67d840621dc4503e342679f625f8aed3e86af1a9cdf515089f508`。
- 模型账目：当前 16 次请求均属于诊断或中断版本，不能并入最终版完整质量结论。T072 的历史 combined runtime、三次真实 main 请求与 fixture review 记录保持不变。日常配置未修改。
- 新链宿主证据：`/tmp/rotom-permission-host-smoke-20260929/lifecycle-result.json` 已验证 new/resume smart、profile-default、bridge healthy、`identityVerified=true`、退出 0，外部模型调用为 0。scripted auto-allow及回滚通过：primary1/tiny0、permit consumed、成功toolResult恰1、外部模型0。
- 未覆盖：T073最终版质量评测尚未完成，不预测 SC-001/SC-002。

## T080 真实指代歧义修复与历史身份（2026-09-30）

- 状态：完成。源码与正式身份稳定；材料化回归、定向 reviewer、strict、Linux x64 隔离宿主及冻结样本模型评测均已取得最终结果。独立 scout 全量语义审计已完成；59个有效allow的动态scope、来源与逐effect完整授权证据均匹配。
- 当时 T080 正式身份：official recipe `969b7e6052eb4020cf27ffaecdacf4abc25bbaf98dbf4e05ba8d114410c027d5`；plugin tree `430bad7398aeb47748a5bf9871558c923a62a949a1888efbc5520824c5416113`；standalone `3ab701bfa0d496e72e9f5725b2077a0241a4e9cc4603d091fcf10761be2c2556`（367269064 bytes）；patched manifest `174930267033f5320936677f7e192bdb1a85e2b86f77a860f608f231038f9f46`；receipt `5531d437a5cf1699805c9d352041a528d8c910ad856b8ebbe2b8e596f243e22e`；combined runtime `b1566c3e211f0dbd71d1849509a7f3b10bb27651602f1ca6fc5b51bd1f7ccbe4`。
- Patch 身份保持：0001 `b9c597b0f60c6e2b58855828602cf65495b79715664a25047d28d49677faaaf6`；0002 `be830a4238d67d840621dc4503e342679f625f8aed3e86af1a9cdf515089f508`。
- 回归：三组材料化 pytest **151 passed in 66.79s**，其中 build-inputs 为 48 项；日志 `/tmp/rotom-permission-reference-fix-final-pytest.log`。材料化 pytest 内完整 Bun core **270 tests** 通过。定向 reviewer **61 passed / 98 assertions**，strict 检查退出 0。
- 宿主：当时 T080 runtime `b1566c3e211f0dbd71d1849509a7f3b10bb27651602f1ca6fc5b51bd1f7ccbe4` 在真实隔离 Linux x64 standalone 通过 new/resume、单次 `pwd` fixture review permit 消费、missing-plugin 启动前 exit 5 与 rollback；外部模型调用为 0。结构化参考为 `referencePolicyDelivery20260930`。
- 模型结果：冻结 240 条中 safe **99/100** 免问，risk **0/100** 危险 allow，fault **0/40** allow；因此 SC-001 的至少 80% 与 SC-002 的 0 危险 allow 在该冻结范围内通过，不扩展为其它 SC 或普遍质量结论。原始 78 次主审包含 safe 60 条（59 allow、1 ask：`safe-036`）和 risk 18 条（16 个有效 deny、2 个格式错误转 ask：`risk-064`、`risk-071`，`evidence={}`）。四条 supplemental 最终 3/4 符合预期、0 条危险 allow；002 的错误 binding key 使 `messageId` 格式验证失败并转 ask。共 82 个最终模型响应，79 valid、3 invalid；所有 invalid 均失败关闭为人工。
- 预算与边界：102/102 请求额度已用尽，由历史 20、最终原始 78 和最终 supplemental 4 构成；relay 已停止，不再发送模型请求。日常本机配置未修改。独立语义审计已完成；真实tiny推理和Linux x64以外平台仍未验证。

## Phase 9 收敛修复与最终交付（2026-09-30）

T081/T082 已完成。native deny 在 pre/effective 阶段使用只供拒绝审计的保守宿主计划，不运行 tool_call 改写或 native prepare；final 阶段保留真实冻结计划。已知 native deny 不依赖可选来源 callback 才生效，三个阶段均记录一次关联 deny。ask 在等待 UI 前写入审计；无 UI 或取消不丢记录，人类结果及 permit 后续阶段保留同一请求链。模型、凭据和 provider 变化后同步权威被动状态；status 只读取快照，显式 reviewer 与历史审计模型身份不被替换。

TDD 实际证据：T081 首轮 bridge 31 pass/4 fail（提前 deny 和无 UI/取消漏审计）；T082 定向 0 pass/1 fail（模型已是 review-b，首次 status 仍是 review-a）。修复后 bridge **37 pass/0 fail/287 assertions**；材料化定向 pytest 1 passed/58.79s，完整 coding-agent `bun run check:types` 与四文件 oxfmt check 均退出0。代码和测试由 executor `gpt-5.6-sol / medium` 实施；scout `gpt-5.6-luna / medium` 只读整理交付入口，主代理负责拒绝语义、最终审查与交付验收。

| 身份 | 本轮实际值 |
|---|---|
| 0001 patch | `f5478d8c128a92e19fc5ff46269a6cf6743dc8fc7c20389211c676afe605ce94` |
| standalone SHA-256 | `ada205aeec0cd2aefbb4c2d0b00d924ba2d9360395159fdd76f2c6a56a128f41` |
| standalone size | 367281352 bytes |
| patched manifest | `f3a274d2c593851d17101d57a8aca6c5705994655f6b93755f356d258918af2f` |
| build receipt | `f5ab42e0d4ef6997d0f13bed74d97945190e0a6dbb149ce6d94808bf85269da3` |
| combined runtime | `36c0e8a46da3999b4eee73edc0121117fd284f2880bc7784ba36189946854e0f` |


official `969b7e6052eb4020cf27ffaecdacf4abc25bbaf98dbf4e05ba8d114410c027d5`、plugin `430bad7398aeb47748a5bf9871558c923a62a949a1888efbc5520824c5416113`、0002 `be830a4238d67d840621dc4503e342679f625f8aed3e86af1a9cdf515089f508`、独立 build-inputs 与冻结样本保持原身份。正式离线构建的 artifact cache 为 `/tmp/rotom-omp-permission-artifacts-convergence-20260930`；构建的 `hostExecuted=false` 不代表宿主通过，实际宿主结果由后续步骤单列。

最终回归命令：

```sh
.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_runtime.py tests/test_omp_permission_build_inputs.py tests/test_omp_kernel.py::test_kernel_deployment_preserves_reviewed_native_configuration --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies --basetemp /tmp/rotom-permission-convergence-final-pytest
```

结果：**152 passed in 71.68s**，包括原三组151项和本轮新身份的kernel渲染单项，无跳过。默认回归仍是隔离测试，不启动真实宿主。

新 runtime 独立真实宿主 case：`/tmp/rotom-permission-convergence-host-20260930`。实际 sync/plan/apply/run 成功；固定服务 main2/review1、外部模型0，pwd恰执行一次，primary1/tiny0/human0，审计同一请求 pending→consumed；manual→new、manual→resume 均恢复 smart/profile-default；missing-plugin 在启动前退出5并恢复原字节；rollback退出0、restored4、dummy key移除、pending absent。OMP退出0，固定服务已停止。结构化证据在 [host JSON](omp-permission-control-host-smoke-evidence.json) 的 `convergenceDelivery20260930`。

| 状态 | 本轮范围 |
|---|---|
| 完成 | T081/T082、正式重建/锁定、152项回归、37项bridge、strict/format与同一新资产宿主复验 |
| 进行中 | 无本轮剩余任务 |
| 失败待决策 | 无；原始红灯与测试夹具缺桩修正保留为诊断记录，不计通过 |
| 环境不足未验证 | 本轮无阻塞所选Linux x64交付的已确认环境缺项 |
| 尚未执行/未验证 | 真实tiny推理、真实interceptor扩展链/长任务和其它平台保留既有证据边界，不计为通过 |

本轮未新增付费模型调用。102/102账本、最终模型响应和冻结样本逐字节不变；T080冻结模型质量结果保留其原始runtime身份，不冒充本轮重测。日常机器配置摘要不变，日常cache和实例未部署。

## Phase 11 Cursor 与远程审批 fallback（2026-09-30）

| 状态 | 本轮记录 |
|---|---|
| 完成 | T085 core：显式主审优先、默认会话模型、远程故障接替、tiny 最后限权；291 pass / 0 fail / 1085 assertions，独立严格 TypeScript 源码检查退出0 |
| 进行中 | 无 |
| 失败待决策 | 无 |
| 环境不足未验证 | 真实 Cursor 模型目录、GLM fallback 审批质量、本地 tiny 推理及其它平台本轮未尝试，不能从假模型结果推定通过 |

Core 命令为 `/tmp/rotom-omp-build-inputs/bin/bun test tests`（cwd=`agents/omp/packages/omp-permission-control`）；严格检查在 `/tmp/rotom-permission-core-typecheck.bzRikK` 复制源码隔离执行 `./node_modules/.bin/tsc -p tsconfig.json`。TDD 定向初始为48 pass / 23 fail，最终全包闭合。各阶段实际请求最多一次；有效 allow/ask/deny 不再触发后续模型；远程 allow 仍经过完整证据验证、固定风险下限与宿主 binding。新增定向测试覆盖 unsupported/unavailable、超时后预留 tiny 时间、ok 但没有实际推理计数、取消、同模型去重和审计来源。没有启动宿主或付费模型；执行代理为 gpt-5.6-sol / medium。

### Phase 11 最终交付

Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。

| 身份 | 本轮实际值 |
|---|---|
| official recipe | `60d399dd4b0a2f2265d117d17b9e566669b64ca1413d4dc0fac66487165b9521` |
| plugin tree | `4511e7cdb9efb312029acfff93f0f6fe73cc5c3c018325c25756f9fd7eea040d` |
| 0001 patch | `45a0fcbdd4092161cbc3c14ac8b40a323928cd4dc915538e2cbee7f6ead8e51f` |
| 0002 patch | `c34d02d19941e09ca507e67164f5b8d37a67e991b6ed96ab51dca2b67ece33da` |
| standalone SHA-256 | `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86` |
| standalone size | 367318216 bytes |
| patched manifest | `dce490890453ccff4165ece76a460fb9cbf23756cdb553c3fd7fe8d72bbb815e` |
| build receipt | `f0716c84316192f349253d68247ba4bcfc455f41218816efe79675952df4a0ac` |
| combined runtime | `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2` |

离线构建artifact cache为`/tmp/rotom-omp-permission-artifacts-remote-20260930`，构建`hostExecuted=false`；宿主复验另在`/tmp/rotom-permission-remote-host-20260930-attempt2`显式执行。最终pytest命令和结果保存在`final-pytest.log`，实际补丁检查在`/data/1/weixiaoxian.wxx/dev_tool/rotom/cache/permission-remote-tests/finalcheck`；源补丁从pristine分层重生成并干净应用，检查详细计数由host JSON的workerVerification保存。首轮finalpytest为221pass/45fail，均因仓库测试根的允许组写入祖先被私人路径检查拒绝；首轮宿主因/tmp/.omp未声明来源在spawn前exit4、请求0。保留原日志后换用合规/tmp私人测试根及/var/tmp工作目录，未放宽产品保护。冻结样本、原始模型响应、语义审计、模型账本及日常local共9项受保护输入摘要不变。两名实现executor均为gpt-5.6-sol / medium，主代理完成关键边界判断、正式构建与最终验收。


本轮验收后，将同一已验证资产原子准备到日常omp-kernel的私人内容寻址cache并显式sync，退出0，runtime为`06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。仅新增缓存运行包，未apply原生配置、未访问OMP账号库、未启动或停止日常会话；workstation.toml摘要保持不变。退出活动OMP后由用户plan/apply/run启用。


### 本机部署闭合（2026-09-30，后续明确授权）

用户确认已退出 OMP，并明确要求完成日常 `omp-kernel` 的 `plan` 与 `apply`。以原 workstation.toml 执行：`plan` 退出 0，3 项变更、冲突 0、漂移 0；`apply` 退出 0，部署同一 3 项变更；随后 `doctor --format json` 退出 0，状态 `offline-ready`，待变更 0，当前和已部署依赖均 `installed`，`deployed_runtime_matches_current=true`，无冲突、漂移或待恢复事务，`live=false`。当前 combined runtime 为 `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。

这是前文“仅 cache/sync”阶段之后的新增授权与执行证据。未启动日常宿主、未访问 OMP 账号库，新增模型请求 0；workstation.toml、历史模型响应/账本、冻结样本及 build-inputs 共 9 项受保护输入摘要保持不变。用户接下来可直接 `run`；本次部署健康检查不声称已验证真实 Cursor 目录或新 GLM 模型质量。机器可读结果位于 host evidence 的 `remoteFallbackDelivery20260930.dailyDeployment`。

## Phase 13：本机迁移与 Cursor 默认模型（后续明确授权，2026-09-30）

用户要求更新本机环境并确认已退出。使用原 workstation.toml 对 omp-kernel 执行 sync、plan、apply，均退出0：官方缓存命中并通过SHA256；首轮plan/apply6项、冲突0，移除旧桥接字段、部署独立插件sidecar和官方运行包。

唯一保留漂移为原生 `/modelRoles/default = cursor/kimi-k3-high:high`。由于它是受管启动资源，保留漂移仍会阻止启动；未删除守卫、修改基线或把用户选择恢复成Kimi。新增仓库自有适配字段 `agent_options.native_model_roles`：只有显式声明并选用 Cursor OAuth provider，且角色已有公共定义时，才可通过公开 modelRoles 字段绑定严格的原生引用。它优先于同角色静态映射，不生成 Cursor 静态模型或 API-key provider。隔离回归 `tests/test_omp_adapter.py tests/test_omp_kernel.py tests/test_omp_foundation.py` 共59 pass，27.15s，executor为gpt-5.6-sol/medium；官方普通锁a24...与默认kernel输出均不变。

本机通过现有render_edit+Tree进行原子0600窄编辑：只加入非秘密Cursor OAuth声明、在原5个provider基础上追加cursor、加入 `native_model_roles.main=cursor/kimi-k3-high:high`。写前完整候选/原生产物校验，写后完整TOML语义比较证明其它配置及秘密未变，未保存含秘密的整文件备份。随后plan/apply退出0，变更0/漂移0/冲突0，正常部署记录纳入明确意图，无直接基线修改。

最终doctor退出0：offline-ready、待变更0、当前和已部署依赖installed、部署运行包匹配、无漂移/冲突/待恢复、live=false。runtime为 `a24d84ccd1ebb138a147d39de2f33771dab602064f216a03ce612bd1b39f136a-linux-x64`。本机官方二进制正文SHA256与发行锁 `d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3` 一致；plugin tree仍为 `5e145c13475d03554fcc8e191e08bbc34223c8452c9a5be886f5fb9ba6e1b29c`。sidecar为smart、reviewer=session、remote=zhipu_tf/glm-5.3-flash、本地fallback不可用；native bash prompt、permission_bash allow，旧桥接字段不存在。

执行 `.venv/bin/python /tmp/rotom-permission-standalone-20260930/daily-preflight.py` 退出0：使用真实本机部署通过完整runtime资源、来源、身份、运行包及租约准入，过滤所有SecretRef并以launch_operation回调替代spawn。没有启动日常OMP、读取账号库或发送模型请求。账号home/native profile身份不变；12项其它保护输入不变，workstation.toml是本阶段明确授权的窄配置改变，原Phase12的13项摘要记录保留其原审计时点，不再误称机器文件当前未变。

完成＝T093—T094，本机可由用户正常run。真实Cursor认证/目录、模型调用质量和其它平台未新增验证，模型额度仍102/102。完整机器可读记录见[standalone evidence.dailyDeployment](omp-permission-control-standalone-evidence.json)。
