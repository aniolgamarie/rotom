# Pi 迁入 agentcfg：本机 Pi 接手文档

更新日期：2026-09-21。工作仓库：`/data/1/weixiaoxian.wxx/dev_tool/rotom`。

配套的[接手 prompt](pi-migration-prompt.md)可以直接发给本机 Pi。本文件是操作交接，不是完成或发布声明。

## 1. 先读结论

- 功能目录：`specs/001-unify-pi-capabilities/`；任务清单目前 **104/112**，未完成的是 **T098、T106—T112**。
- 当前软件候选锁为 `484f07e9f16e070296b88ba24dcf7a5900f9d098ed1d5f43340c4f31b281dd26`，38个来源、四个profile；DSH锁在此前解析中保持不变。
- default、Cursor已经完成Linux x86_64双路径冷重建；Codex、Task Keeper第一目标全部原生通过，第二目标分别在资产校验、Python依赖下载阶段失败。
- 最后一次有效完整隔离回归为1782 Python、7 subtests、325 Node通过。它与锁生成有约30秒重叠，需要补一份锁已固定后开始的完整回归。
- 用户明确表示Pi本机`--local`文件和实网测试项目**未准备**；六项实网服务仍全部已选。其他三个平台没有机器，用户明确要求保留未验证。
- **还存在验收器代码接线工作，不能把所有剩余项都说成只缺机器或账号。** T098的具体缺口见第5节。
- 仓库有大量未提交修改和未跟踪文件，整个Pi实现尚在工作区。先检查`git status`，保留已有工作，不执行会丢失这些文件的reset/clean/覆盖操作。

### 本次交接新发现

2026-09-21核对时，以下旧临时入口已经不存在：

- `/tmp/agentcfg-run-final-mock.py`
- `/tmp/agentcfg-cold-profile-retry.py`
- `/tmp/agentcfg-run-codex-cold-retry.sh`
- `/tmp/agentcfg-pi-build-tools-24.14.0/bin`
- `/tmp/agentcfg-pi-volume-o7nluwv_`

不要直接照抄旧阻塞文档中的临时脚本命令。第6节提供不依赖这些脚本的执行方法。仓库内的`cache/pi-validation/runtime-volume`仍存在；旧`/tmp/agentcfg-pi-volume-o7nluwv_`是先前沙箱中的挂载位置，不是今天必须存在的真实目录。

当前工具发现的node路径为`~/.nvm/versions/node/v24.1.0/bin/node`，没有在PATH发现bun；这不是锁要求的工具链。本轮未执行版本命令或安装工具，Pi接手后需重新核验并准备正确版本。

## 2. 已确定的用户决策与执行边界

1. **彻底以model-delegate替换codex-delegate**。七个旧Codex协调角色收敛为一个真实委托入口和用途模板；保留完整技能、显式高级操作，不能重新注册旧执行器或七个独立协调角色。
2. **官方Codex CLI + 原生工具**。不改回默认MCP工具桥，不维护Codex分支。系统/企业/组织配置或账号边界无法核验时拒绝执行；这些环境的兼容性缺口已被用户接受，但不能删除验收范围。
3. 用户要求自主完成不需要新决策的代码、修复、默认测试、已授权的依赖安装/锁解析和合成服务native/cold验证，不要反复询问已确定路线。
4. Codex、Cursor、MCP、web、代理、终端**全部选择实网验收**；缺配置、登录、机器或服务不能改成`not-selected`。Task Keeper的direct/proxy调查、修复、检查、审查、第二视角也是必需live范围。
5. 当前没有明确可用的Pi本机配置、测试项目及其账号/服务绑定。不得直接借用“正在运行本机Pi”的账号或项目来填充这些空缺；具体输入具备且满足既有授权、匹配native前提后再执行live。
6. 其他三种平台缺机器，保留`not-run`。可继续完善平台无关代码和替身测试；macOS原生编译、运行及监督证明不能由Linux测试代替。
7. 遵守根目录[AGENTS.md](../../AGENTS.md)：默认测试只用仓库和临时HOME、阻断网络、假进程/模型，不启动第三方宿主。native是独立的已授权步骤，只用合成服务；live单独处理。秘密不进入配置摘要、日志、报告或异常。
8. 历史失败、`escaped`、`unknown`、未核验租约都保留。不要删除保护记录、放宽目录属主规则或关掉校验以让测试通过。

前一个Codex会话的自动审核超时属于**执行通道问题**，不是项目要求每次都重新征求测试许可。Pi在自己的正常用户环境按上述既有授权继续；如果Pi自身执行工具有实际审批限制，应遵守该限制并报告具体原因。

## 3. 阅读顺序与可信证据

先读项目约定，然后按下面顺序读，不需要先重读整个长历史记录：

1. [任务清单](../../specs/001-unify-pi-capabilities/tasks.md)、[spec](../../specs/001-unify-pi-capabilities/spec.md)、[plan](../../specs/001-unify-pi-capabilities/plan.md)、[quickstart](../../specs/001-unify-pi-capabilities/quickstart.md)。
2. [当前候选身份](../acceptance/pi-candidate-484f07e9.json)、[Linux汇总](../acceptance/pi-linux-x86_64.json)、[阻塞记录](../acceptance/pi-validation-blockers-484f07e9.md)。
3. [默认回归记录](../acceptance/pi-default-tests.md)、[完整mock原报告](../acceptance/agentcfg-pi-mock-20260920-host-namespace.json)、同名`.artifacts/`输出目录。
4. [冷重建索引](../acceptance/pi-cold-484f07e9/index.json)及[目录说明](../acceptance/pi-cold-484f07e9/README.md)。本次交接重新核对了索引中**79个文件**的SHA，全部匹配。
5. [证据与发布契约](../../specs/001-unify-pi-capabilities/contracts/evidence-and-release.md)、[固定scope](../acceptance/pi-scope.json)、[支持矩阵](../acceptance/pi-support-matrix.md)、[实网准备情况](../acceptance/pi-live-readiness.md)。
6. 需要追溯具体修复时再查[实施历史](../../specs/001-unify-pi-capabilities/implementation-progress.md)及相关测试。

当前候选的源码摘要为`2294e30ff067d5e577dddaba12a1ff3c4f4a6e878a597ca065feb82489ad0ba1`。它是冷重建的源码集合摘要，不是Git提交hash。软件输入冻结不代表scope中所有机器、策略、模型和账号身份均已冻结。

| Profile | 第一套干净HOME/checkout | 第二套干净HOME/checkout |
|---|---|---|
| pi-default | 安装、部署、全部原生场景通过 | 全部通过 |
| pi-cursor | 安装、部署、全部原生场景通过 | 全部通过 |
| pi-codex | 全部通过，包括官方CLI只读/写入/控制 | sync退出5：数据资产大小或摘要不匹配；原生未执行 |
| pi-managed | 全部通过，包括11个生命周期场景、父宿主退出及恢复 | uv下载coverage 7.16.0发生TLS handshake EOF，3次重试后失败；sync和原生未执行 |

不要把Codex失败简单认定为确定的网络瞬断：现有证据只证明资产校验失败；若重复发生，应查明固定源内容、传输完整性和摘要是否一致。

## 4. 最新实现与容易误改的边界

| 领域 | 主要入口 | 当前实现/注意点 |
|---|---|---|
| Linux宿主与Codex生命周期 | `src/agentcfg/pi_pid_namespace.py`、`src/agentcfg/pi_host.py`、`scripts/pi-namespace-exec.py` | Pi宿主和Codex分别使用独立PID命名空间。先核验init/包装出生身份并登记v3记录，再放行；宿主门控通过SO_PEERCRED核验，保留stdin。已通过目标中58个宿主租约均已回收且有terminated记录。 |
| 固定bwrap依赖 | `agents/pi/dependencies.json`、`src/agentcfg/pi_vendor.py` | 四个Linux profile均选择固定Codex发行物里的bwrap辅助资产；安装辅助程序不代表启用Codex backend。不要因非Codex profile只有bwrap就强制要求完整Codex CLI资产。 |
| 历史进程记录 | `src/agentcfg/activity_linux.py`、`src/agentcfg/process_tracking.py` | v1/v2不自动升级或清除unknown/escaped；64KiB限制只针对v3。停止后的短暂/proc不确定状态只在既定期限内继续观察，不向未知身份补发信号。 |
| model-delegate | `src/agentcfg/model_delegate*.py`、`src/agentcfg/pi_delegate*.py`、`agents/pi/packages/model-delegate/`、`shared/skills/model-delegate/` | 官方CLI原生只读/写入/控制已实跑合成服务。结果刷新必须先于新物理证明采样，不能以probe或旧收据冒充执行成功。 |
| Task Keeper | `agents/pi/packages/task-keeper/`、`agents/pi/runtime/managed-*.ts`、`agents/pi/runtime/native-validation.ts` | 使用新subagents接口。pause让当前步骤收尾，stop才中止执行；native软暂停窗口180秒、stop窗口30秒。11场景包括两项proxy场景。 |
| 默认插件与Todo | `profiles/pi-*.toml`、`agents/pi/packages/todo-vendor/`、`agents/pi/runtime/resource-loader.ts` | ordinary核心包含Todo、循环保护、状态栏；Todo完整功能与九种语言已迁入，配置只读实例manifest。已选插件缺少安装资源必须报错。 |
| Bun | `src/agentcfg/pi.py`、`src/agentcfg/pi_delegate_spawn.py` | 使用`--config=PATH`、`--tsconfig-override=PATH`。不要改回分离参数；Bun自身的tsconfig诊断不靠移除配置限制隐藏。 |
| 冷重建 | `src/agentcfg/pi_cold_rebuild.py`、`src/agentcfg/pi_cold_sandbox.py` | 先冻结源码，再从冻结快照重启控制代码/schema；两个目标均重新安装。不能只冻结数据而继续用可变工作树里的schema。 |
| ReadSeek | `src/agentcfg/pi_readseek_source.py`、`agents/pi/build/readseek-source.json`、`docs/pi-readseek.md` | macOS Intel固定源码构建路径及替身测试已实现；Zig 0.16.0，非Rust构建。未在真实macOS编译/运行，不继承Linux证明；完整原生工具覆盖仍需按能力矩阵核对。 |

[第一方内核smoke记录](../acceptance/pi-host-kernel-smoke-484f07e9.json)覆盖stdin保留、脱离进程组的后代终止、继承只读挂载不被放宽，以及门控EOF不执行目标。它不代替Pi原生或live结果。

## 5. 剩余任务与关闭标准

| 任务 | 应做的工作 | 何时可以关闭 |
|---|---|---|
| T098 | 审计并补齐分层验收器的实际接线及报告/scope对应关系，特别是下面列出的macOS缺口和完整能力覆盖 | 所声明场景有真实执行入口、必要替身/负向回归通过；平台执行未发生仍保持not-run，不靠删除guard变成支持 |
| T105补充证据（任务当前已勾） | 在正常用户环境、锁稳定后重新执行`--tier mock --case all`，保留原报告 | 新报告及原始输出有效通过；原有效报告不删除。如果发现实现回归或候选改变，重新打开受影响任务 |
| T106 | 补齐Codex、managed的两路径冷重建；核对四profile同候选原生证据、归档和平台汇总 | 每个profile至少满足任务规定的两个新HOME/checkout完整安装及原生通过，不能把两个历史不同源码候选拼成通过 |
| T107—T109 | Linux arm64、macOS arm64、macOS x86_64实机验证 | 目前缺机器，按用户决定保留未验证；不能用mock、CI定义文件或x86结果代替 |
| T110—T111 | Task Keeper direct/proxy与六项已选服务的真实验收 | 明确的local/项目/账号/服务绑定就绪，匹配native前提，通过对应live场景；当前未准备，不执行真实账号 |
| T112 | 最终scope证据登记、支持矩阵、check-release及交付说明 | 全部required和selected_optional证据匹配passed才可批准；当前可以生成阻塞报告，但不能勾完整交付 |

### T098已定位的代码缺口

`src/agentcfg/pi_validation_native.py`目前对非Linux平台明确返回以下not-run：

- `recovery-grants`：`recovery-runner-requires-linux`；实现仍依赖`LinuxProcesses`，见`pi_validation_recovery.py`及`scripts/pi-native-recovery.py`。
- `delegate-control`、`delegate-proxy-control`：`standalone-control-runner-requires-linux`。
- `migration-runtime-conflicts`及三项`codex-native-*`：`migration-runtime-mount-requires-linux`；检查`pi_validation_sandbox.py`的`local_runtime`接法。
- `parent-loss`：`parent-loss-runner-requires-linux`；见`pi_validation_parent_loss.py`，它使用Linux身份信号接口。

这些是尚未完成的接线，不是只缺一条测试记录。需要结合`activity_macos.py`、`scripts/pi-supervisor-macos.c`、平台停止/收据契约设计，不能直接删除平台条件、对裸PID发信号或模拟成Linux。没有macOS机器时，继续能独立完成的接口及替身测试，并明确剩余原生实现/验证限制。

同时按validation-matrix、能力矩阵和quickstart逐项检查：默认场景组通过不自动证明所有可选插件的完整用户流程（例如ReadSeek工具操作）都已原生覆盖。

## 6. 本机执行方法：不依赖旧/tmp脚本

### 6.1 前置检查

在正常用户shell中进入仓库，检查未提交工作、可能仍在运行的旧验收及磁盘空间。只核对明确归属的活动，不按名字批量杀进程，不清旧状态。

```sh
cd /data/1/weixiaoxian.wxx/dev_tool/rotom
git status --short
.venv/bin/python -c 'import os; from pathlib import Path; print("uid", os.geteuid()); print([(str(p), p.stat().st_uid) for p in (Path("/"), Path("/tmp"))])'
node --version
npm --version
bun --version
uv --version
df -h /tmp "$HOME" /data/1
```

锁定版本：Node **v24.14.0**、npm **11.19.1**、Bun **1.4.0**；Python 3.11+、uv、Git及Linux bwrap也须可用。按锁准备独立可信工具链并明确PATH，不升级锁来迁就偶然发现的系统版本。

前一个Codex默认沙箱中有效UID为1002，但`/`和`/tmp`映射为65534，触发属主保护，产生847 passed、892 failed、43 errors；正常用户完整隔离运行此前已通过。若Pi看到相同问题，应修正执行环境，不能改`paths.py`或伪造UID。也不要chmod不属于本次任务的`/data`等祖先目录。

### 6.2 为本轮创建独立输出根

在**有足够空间且祖先属主可信**的位置建新目录。下面使用用户缓存目录作为例子，必须先确认该文件系统能容纳多份运行包、模型、checkout和下载缓存；不能默认小容量`/tmp`足够。

```sh
agentcfg_handoff_base="$HOME/.cache/agentcfg-pi-handoff"
mkdir -p "$agentcfg_handoff_base"
chmod 700 "$agentcfg_handoff_base"
export AGENTCFG_HANDOFF_RUN_ROOT="$(mktemp -d "$agentcfg_handoff_base/run.XXXXXXXX")"
```

冷重建的destination必须是尚不存在的目录，且不能直接位于repository内部。如果大容量磁盘只在仓库所在的`/data`，应重建明确的外层bwrap视图，将本次独立存储目录绑定到可信`/tmp/...`路径，显式只读绑定仓库与工具链；参考`pi_cold_sandbox.py`及旧报告的路径结构。内层生产runner仍必须只挂新目标和工具链，不能挂旧运行包/模型缓存。不要只改报表里的绝对路径来假装复用了旧沙箱。

### 6.3 补跑完整mock

先核验当前源码/锁。以下检查针对保持484f07e9不变的重跑；若先修改了实现，按第8节生成新候选后再运行，不能仅改assert掩盖失配。

```sh
PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path
from agentcfg.pi_dependencies import PiBackend
expected = "484f07e9f16e070296b88ba24dcf7a5900f9d098ed1d5f43340c4f31b281dd26"
assert PiBackend().read_lock(Path.cwd()).identity == expected
PY

.venv/bin/python -B scripts/verify-pi.py --tier mock --case all \
  --output "$AGENTCFG_HANDOFF_RUN_ROOT/mock.json"
```

此入口包含完整pytest和Node测试，并创建临时HOME/隔离环境；保留`mock.json`及`mock.json.artifacts/`。根据退出码、报告status和输出判断，不用历史测试数量硬编码通过条件。

### 6.4 只重跑缺失的Codex与managed冷重建

源码未改变时，default/Cursor的当前候选双路径证据可以保留，不必无条件重跑。下列代码调用生产冷重建接口，自动冻结控制代码/schema，创建`first`和`第二组 空格路径`并执行各自完整原生场景；没有注入替身回调，也没有使用旧缓存。

```sh
PYTHONPATH=src .venv/bin/python -B - <<'PY'
import json
import os
from pathlib import Path
import shutil

from agentcfg.pi_cold_rebuild import cold_rebuild
from agentcfg.pi_dependencies import PiBackend

repository = Path.cwd()
output_root = Path(os.environ["AGENTCFG_HANDOFF_RUN_ROOT"]).resolve(strict=True)
expected = "484f07e9f16e070296b88ba24dcf7a5900f9d098ed1d5f43340c4f31b281dd26"
assert PiBackend().read_lock(repository).identity == expected
uv = shutil.which("uv")
assert uv and Path(uv).is_absolute()
for profile in ("pi-codex", "pi-managed"):
  destination = output_root / profile
  assert not destination.exists()
  result = cold_rebuild(repository, profile, destination, allow_host=True, uv=uv)
  with (output_root / (profile + "-cold.json")).open("x") as output:
    json.dump(result, output, ensure_ascii=False, indent=2)
    output.write("\n")
  print(profile, result["status"], flush=True)
PY
```

脚本正常退出不代表两份结果通过，必须检查每份JSON及目标明细。独立profile可在资源允许时并行，目标目录必须各自唯一。首次失败后保留目录，下一轮另建输出根。

注意：`--tier native --case all`包含cold-rebuild。不要在上述生产冷重建之外再无意重复触发整轮嵌套冷重建；定向native复验选择实际case，并且不能替代冷重建证明。

### 6.5 失败处理

- **资产摘要/大小失败**：核对固定URL/commit、期望大小及摘要、响应和传输是否完整。诊断不得把带签名URL或凭据写入公共日志；不能跳过校验或未经核实更新摘要。
- **TLS/下载失败**：检查网络、系统CA和显式安装代理。生产代码只向安装阶段传入经过校验、不含URL凭据的标准代理；native/模型阶段不继承它。不能关闭TLS验证。
- **进程回收失败**：先读该目标的controller结果、lease、process记录和终止证明。未知状态保留，不能用测试脚本退出或PID当前不存在就擦掉保护。
- **真实功能失败**：定位并修复，运行有意义的定向回归；源码变化后按第8节重建候选。避免在长冷重建运行途中持续编辑其控制代码/schema。

## 7. 证据、scope和最终报告

每次使用新报告名称/目录，保留失败。归档至少包括：mock JSON和输出、cold顶层报告、两个目标各自的`native/*.json`及安装输出，另生成SHA索引。核对报告路径、候选锁、源码摘要、runtime identity、场景列表、退出码、终止确认，不仅看顶层`passed`。

历史报告内的绝对路径属于当时的沙箱。可从`cache/pi-validation/runtime-volume`查原始记录，但公开证据以仓库归档为准；本轮不要求旧临时脚本或映射路径继续存在。

当前scope revision 2有364项：340 required、24 selected_optional、0 not-selected；本次核对364项identity均为空。候选软件输入、原生执行报告与最终EvidenceRecord是不同层次。不得复制native汇总给所有V项：按[证据契约](../../specs/001-unify-pi-capabilities/contracts/evidence-and-release.md)、`pi_evidence.py`、`pi_acceptance.py`逐项核对实际覆盖与身份，不编造缺失的机器/策略/账号摘要。

在正常用户环境可以先输出真实的阻塞状态：

```sh
.venv/bin/python -B scripts/verify-pi.py --report-only \
  --scope docs/acceptance/pi-scope.json --evidence-root docs/acceptance \
  --output "$AGENTCFG_HANDOFF_RUN_ROOT/status.json"

.venv/bin/python -B scripts/verify-pi.py --check-release \
  --scope docs/acceptance/pi-scope.json --evidence-root docs/acceptance \
  --output "$AGENTCFG_HANDOFF_RUN_ROOT/release.json"
```

`report-only`成功不代表批准；`check-release`在范围未满足时返回1是有效的“不批准”结果，返回2表示输入/保存等错误，不能混淆。当前仍应保留未验证平台和live范围，不能为了全绿缩减scope。

## 8. 如果需要继续改实现

1. 先集中核查T098和能力覆盖缺口，区分当前可完成的软件工作、需要其他平台才能验证的工作。不要把“没有macOS机器”写成代码已经实现。
2. 集中完成本轮必要改动与定向回归，再冻结候选；避免反复边跑长验收边改源代码。
3. 使用仓库正式锁解析逻辑`agentcfg.pi_vendor.resolve_lock(repository)`生成完整四配方锁/vendor；解析前后逐文件核对`locks/dsh`不变。不要手改manifest身份或归档摘要。
4. 更新来源/调用方/许可证核对和候选记录。若原T103—T105证据因改动失配，先重新打开任务，再按实际验证关闭。
5. 完整默认回归必须对应最终源码。新锁/runtime/source身份不能直接继承484f07e9的原生通过；按照证据契约重新取得受影响的完整验证。
6. 用户的其他平台未验证、live未准备决策保持不变。继续能独立完成的代码与验证，只在确实缺少新输入或存在新的范围决策时集中报告。

## 9. Pi本轮交付应包含什么

- 实际修改内容及原因；最终源码/锁/候选身份。
- 有效完整mock报告；Codex/managed冷重建的结果及原因，default/Cursor既有证据是否仍匹配。
- T098每个缺口的最终处理：实现、替身验证、实际平台验证或具体剩余限制。
- 更新tasks、implementation-progress、平台记录、支持矩阵和发布报告；只勾符合任务验收条件的项目。
- 明确区分代码完成、mock通过、native通过、live通过。不能因网络恢复、安装成功或部分场景通过而宣布完整迁移。
- 如果只剩其他平台/真实配置等外部前提，给用户一份精确短清单；不重复询问已选的六项服务，也不把旧Codex工具的审核超时当成本机Pi必然存在的限制。

本次交接只整理文档和prompt，未重新启动测试、安装依赖、调用真实账号或修改生产源码/锁。
