# Pi 重建验收证据

当前进度87/96，本轮约定交付完成。T037/T038/T058/T059与T085–T087均按记录的Linux/
实际绑定/四模块范围完成；用户接受三处状态差异，Brave/Cursor真实账号明确延后。
Pro继续等待合格社区上游，T064–T071与T096保持开放。最终84条owner全部complete/idle。
当前结论见[本轮交付验收](current-delivery-acceptance.md)，旧计数和快照属于历史检查点。

候选与目标基点、任务状态见 [implementation-status](implementation-status.md)。
支持声明绑定精确候选/源码摘要、锁/模块选择、OS/架构/工具链类别、实际 argv、退出码、
脱敏结果与未覆盖范围；文件存在或退出 0 不单独证明第三方能力。

## 证据模型

每条记录包含：task_id、candidate、target_main、lock_or_selection、scenario、platform、
argv、exit_code、result、evidence、limits。result 为 passed / failed / not_run；
阶段不适用须附理由，不能把缺账号/授权或已选失败改为未选择。
源码摘要代替提交时须记录纳入的相对路径集合、确定性算法和摘要；输入变化使相关证据失效。
静态、隔离、原生、账号/模型四层分开；requested/selected/observed_model 分开，无回执为 unknown。

默认隔离使用临时 HOME/DSH_HOME/Pi/session/XDG、阻网、假子进程及虚构模型。
A/B/C原生范围已获授权并执行，首次B的两项问题修订后复验通过。
后续共享默认模型、一次有界真实工具、真实取消恢复/压缩统计、D–G原生/服务与TUI/用量样本
已有证据；真实账单、Brave/Cursor账号、真实远端机器和其他平台仍未验，不能扩大支持范围。

## 执行结果

| 任务/范围 | 层级 | 实际 argv 或核查 | 退出码/结果 | 限制 |
| --- | --- | --- | --- | --- |
| T001–T004 | 静态 | Python 3.11 `-B` 文档/路径/引用核查；scout AST/调用证据 | 0 / passed | 仅初始清单、公共差异和固定研究来源，不证明消费者归零 |
| T005 | 静态 | 检查 `tests/conftest.py` 与 `tests/test_isolation.py` | passed | 复用已有临时环境、进程/网络保护；行为由T008验证 |
| T006 | 静态 | Python 3.11 `-B` 生成并解析 `tests/fixtures/pi-reboot/*.json` | 0 / passed | 合成场景资料，不是宿主执行回执 |
| T008 | 隔离 | `../../../.venv/bin/python -B -m pytest tests/test_config_schema.py tests/test_config_resolution.py tests/test_deployment.py tests/test_runtime_preparation_recovery.py tests/test_dependencies.py tests/test_omp_dependencies.py tests/test_omp_dependencies_foundation.py tests/test_lock_publication.py tests/test_isolation.py -q --tb=short -x` | 0 / passed；376 passed，218.92s | 外层执行以获得正确系统目录属主；临时HOME/阻网/假进程保护仍在；不证明新Pi或真实宿主 |

## 交付门

Base、退役、状态栏、Pro、US6模块分别记录，不用Base成功抵扣其他门。
Powerline0.20.2 与 mjakl3.1.0 仍 held；原生回退和拒绝不合格协作只证明安全边界。
Linux x86_64 是首轮目标，macOS候选未验证；历史组合不作为当前平台证据。
FR/SC/26个场景的完整覆盖在T088收口；T096保持开放直到全部必需门闭合。

## US1 增量证据

- T009/T010/T013/T014：配置/合并/三方/journal复用公共实现；九文件基线和三adapter定向边界通过，无需复制实现。新Pi schema全catalog场景仍由T022验证。
- T011/T015：`tests/test_dependency_backend_contract.py` 外层45 passed；假backend透过真实CLI验证exit2/5、不读取秘密、不改变已有包/home/备份；原生闭包/暂存本体仍由各backend既有测试证明。
- 三adapter定向配置/双OMP共享运行及T011：外层56 passed，exit0，3.79s。
- 共享锁/部署恢复/DSH和OMP依赖及隔离阶段回归：外层263 passed，exit0，229.37s；随后FD释放语义修订按受影响路径重验。
- T012/T016：独立run owner 57例通过；binding/完整出生身份/未知保留/维护核实/根替换/深层损坏/观察时间不自动释放。
- 继承FD回归先红（exit1），改为close-only后6例通过；仅用os.dup模拟共享open-file-description，不启动进程。
- T017/T018最终定向：`../../../.venv/bin/python -B -m pytest tests/test_run_owner_integration.py tests/test_instance_admission.py tests/test_lifecycle_leases.py tests/test_omp_runtime_foundation.py::test_omp_parallel_run_leases_block_configuration_writes tests/test_omp_runtime_foundation.py::test_two_omp_runs_can_share_deployed_instance -q --tb=short -x`，外层69 passed，exit0，22.74s。fake宿主退出码保留；记账失败保留active保护并给非秘密说明，不掩盖原生退出；两主互不清除。

前次检查点未实现生产observer；继续实施后Linux已加入spawn前child-subreaper覆盖，完整内核证据只释放本次active。
缺覆盖、后代存活、平台不支持或manager异常仍unknown；旧unknown不能被新运行清除。自有内核探针
通过不抵扣T037/SC008真实宿主，后续证据见本文继续实施段。

T019：`../../../.venv/bin/python -B -m pytest tests/test_secrets.py tests/test_config_secret_loading.py tests/test_omp_secret_boundaries.py tests/test_omp_capture.py -q --tb=short -x`，外层57 passed，exit0，163.90s；只合成凭据/临时原生文件，不读真实账号。

T020：`../../../.venv/bin/python -B -m pytest tests/test_readiness_evidence.py tests/test_presentation.py tests/test_cli_presentation.py -q --tb=short -x`，外层44 passed，exit0，31.99s；doctor六阶段分开，不把安装或服务可达写成加载/账号/运行通过。

T022：新完整catalog测试先红，exit1，原因是新Base/Pro尚未登记，符合待实现事实；测试和实现均未记为通过。

T021：`../../../.venv/bin/python -B -m pytest tests/test_config_schema.py tests/test_config_resolution.py tests/test_deployment.py tests/test_runtime_preparation_recovery.py tests/test_dependencies.py tests/test_omp_dependencies_foundation.py tests/test_runtime.py tests/test_omp_runtime_foundation.py tests/test_dependency_backend_contract.py tests/test_instance_admission.py tests/test_lifecycle_leases.py tests/test_run_owner_integration.py tests/test_readiness_evidence.py tests/test_isolation.py tests/test_presentation.py tests/test_cli_presentation.py -q --tb=short -x`，外层539 passed，exit0，304.98s。临时HOME/阻网/假进程不变；候选为上述基点上的US1未提交源码，范围即本命令对应公共管理实现，不证明新Base或真实宿主。收尾首次运行因测试把允许变化的读取atime纳入“无写入”比较而失败（exit1，160 passed）；改为比较dev/ino/mode/size/mtime_ns/ctime_ns，仍验证文件及备份未被重写。最终回归包含该修订，以及记账告警遇关闭stderr时保留宿主退出码的六例测试。

## US2 增量证据（进行中）

- 新薄适配/完整catalog/配置与启动边界：executor最终116 passed，exit0，24.18s；命令为`../../../.venv/bin/python -B -m pytest tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_runtime.py -q --tb=short -x`。含完整闭包、脚本、schema、profile独立选择、optional peer及SRI边界；不运行真实npm/CLI。
- 公共锁发布与假backend/新适配阶段：`../../../.venv/bin/python -B -m pytest tests/test_lock_publication.py tests/test_dependency_backend_contract.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_runtime.py -q --tb=short -x`，外层185 passed，exit0，24.96s。扩展fixture时首次因遗漏Pi分支走OMP reader而失败（68 passed/exit1）；补齐真正Pi分支后通过。
- 主代理最终后端增量：`../../../.venv/bin/python -B -m pytest tests/test_pi_reboot_dependencies.py tests/test_lock_publication.py tests/test_pi_reboot_pipeline.py -q --tb=short -x`，外层129 passed，exit0，6.23s。目录替换/重复键收据先红，再固定借用lease的Tree句柄、严格JSON解码；缺包前不读秘密、密钥解析异常不登记运行、假CLI退出17原样保留、packages漂移不修复/不安装。初版管线测试接口/fixture调用错误已更正，未修改生产保护。
- Node最低版本及既有依赖：`../../../.venv/bin/python -B -m pytest tests/test_runtime_toolchains.py tests/test_dependencies.py -q --tb=short -x`，78 passed，exit0，201.71s；新增minimum与既有same-major策略分别保持。
- 显式维护静态下载：隔离临时HOME/空npm配置，`node --version`/`npm --version`与`npm install --package-lock-only --ignore-scripts --no-audit --no-fund`、`npm ci --ignore-scripts --no-audit --no-fund`均exit0；Node24.14.0/npm11.9.0，119锁包、13生命周期声明。静态审阅见[npm-script-audit](npm-script-audit.md)，所有脚本保持不执行；不构成宿主运行或账号证据。
- 原工作区正式resolve在私人发布日志创建前因可被他人写入的路径祖先被拒绝，exit1；公开锁未改变。环境限制如实保留，未调整目录权限或生产检查。改为在受信任临时维护副本使用同后端/同来源生成，再审阅公开锁文件；该替代结果待后续记录。

T032最终锁：补全独立法律材料后显式重建并由临时维护副本公共publisher发布，schema2和正文同源校验exit0。锁identity=`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`；每档119包、13项已审跳过脚本。先前候选`2c06bb9a…`因宿主tarball未包含LICENSE不能作为可安装证明，已由本锁替代；官方固定提交MIT正文位于`agents/pi/licenses/pi-coding-agent.LICENSE`，descriptor绑定source URI和SHA256，安装到独立licenses/，npm宿主目录不补文件，npm gitHead仍null。锁导入分支后read_lock与维护副本对象相等，exit0；未修改原工作区上层权限或私人运行状态。

T033/T035最终隔离：`../../../.venv/bin/python -B -m pytest tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_lock_publication.py -q --tb=short -x`，外层208 passed，exit0，35.76s；含独立许可正文复制/源漂移/运行包篡改/闭包更新、四层配置与新管线、两个独立假主运行。缺锁和管线增量另5 passed，exit0，5.50s。原生、账号、模型均not_run。

T036进行中：两份干净源码快照已固定，确定性算法为按相对路径排序的`[path,mode,sha256(body)]`行JSON紧凑序列化后SHA256；摘要`d6ec236748ff0a7f65b793f3f14aacc3cba1cf911ff5ec9973d9a10a4afa220d`。源快照及真实维护argv/输出仅存在0700临时证据目录（文件0600），不导入私人路径；后续退役不改变已冻结的本轮输入。尚未将维护结果记为通过。

## T036 / US3与候选边界的增量结果

T036：两个全新仓库/用户路径（其中一个含中文与空格），相同冻结来源摘要
`b494bed7196661e4caad851a3d42d0a914d63b64098762f055737b66793f7f57`，Linux x86_64，
Node24.14.0/npm11.9.0，消费同一Pi锁`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`。
每个副本实际执行`<prepared-python> -B -m agentcfg --local <case-local> --profile pi-base <command> --format json`，
command依次validate/sync/apply/plan/apply/doctor，12次均exit0。sync使用真实npm ci --ignore-scripts及离线npm ls，未执行生命周期脚本。
两份54个配置artifact在仅规范化仓库/用户根后语义摘要一致，运行身份均
`4f2267757b1731721612c6ca6a87cf9c9083a18a9f7ba871e24662a026c23e24`，重复apply变更0且previous未轮换，
无auth/session创建、生成文件手改0。doctor依赖/部署passed，加载/运行not_run，账号not_inspected。
确定性输入摘要算法沿用前文，纳入src、schemas、profiles、三adapter公开来源、所选公共规则/完整Skill、Pi新五文件锁；
原始行清单、实际绝对argv和输出仅在0700临时证据目录/0600文件保存，不公开私人路径。
共享已准备Python解释器，不是独立重建Python工具链；没有旧Pi home、旧运行包或共享npm缓存。

失败记录：最初不完整的公共catalog快照（摘要d6ec2367…a220d）在validate被拒绝，未运行后续；
补入未改动的DSH/OMP公共来源后冻结为b494bed7…。
首次比较脚本错把合法首次previous记录要求为null，在第一副本六命令exit0后断言失败（exit1）；
改为比较首次/重复apply的previous保持相同，再从两套全新目录重跑通过。另一次解释器相对路径调用错误exit127，未进入管理器。
失败仅修验证脚本，不调整生产所有权/路径检查。

T039–T047：精确退出91个旧Python模块、26个脚本、102个专属旧测试、30个目录边界及71个显式资源/fixture文件。
逐路径删除/保留和消费者证据见[retirement-execution](retirement-execution.md)。四个适用公共保护测试保留/窄迁移，
旧source静态及literal动态导入0，全pytest collection exit0；不读取或清理用户账号/会话/任务库/Git owner。
退役后受影响28文件命令见该执行记录：899 passed/1 deselected、exit0、481.38s；
唯一排除的OMP真实锁断言在显式重锁后原样1 passed、exit0、3.75s，没有用fake锁替代。
OMP同版本官方源码/校验和重新解析，固定源SHA256保持，6公开锁文件在可信临时维护副本发布并审阅导入；
身份从`90357d838801ddab2d3ebe54d57f8cdc49ca31870b9c1e9615409ab58be592ca`变为
`7afccd2beff673e94eb5e2fdc276f0488e2b70d0a8a424d4b795660aaee694af`；没有执行OMP。
DSH锁未改变；新Pi两档recipe及锁身份也未改变。T048退役后双路径结果另记，不能以本回归替代。

T050/T052/T060–T062及未选模块阶段：先新增缺失行为测试再接入固定未就绪报告，
`../../../.venv/bin/python -B -m pytest tests/test_readiness_evidence.py tests/test_pi_status_admission.py tests/test_pi_collaboration_admission.py tests/test_pi_collaboration_contract.py tests/test_pi_optional_modules.py tests/test_config_examples.py -q --tb=short -x`，
外层80 passed、exit0、29.79s。包括doctor JSON与human分层、held拒绝、Base独立、未选模块零进程/连接、跨实例合成哨兵和虚构示例。
第一次optional测试引用不存在process.run失败（exit1）；改为真实subprocess.Popen边界及LaunchSpec接口后通过，生产代码未放宽。
合成协作执行者只定义每主2/两主4、取消/unknown占位与结果独立的验收资料；不是生产调度器，不能抵扣T068/T069。
该80例隔离检查点当时没有已准入/已选择外部模块，T072/T074–T085仍开放；此为历史状态，当前四模块选择和实际验收见本轮交付记录。

T053/T063静态精确包复审：来源SRI、许可正文与真实接口/读取位置见[module-admission](module-admission.md)第6节，
外部模块配方见[optional-module-recipes](optional-module-recipes.md)。Powerline/mjakl依旧held；没有执行候选代码，
没有以深度控制代替并发2，也没有以原生UI回退抵扣十类信息对齐。

## T088：34 FR / 10 SC / 26 AC覆盖矩阵

本表逐项链接任务与本文件的实际证据。passed只表示所写层级；partial/not_ready/not_run不关闭相应交付门。
公共/恢复证据见US1与retirement-execution；Base见T033/T035/T036及T048；边界见80例命令；候选静态资料不作运行通过。

| 要求/场景 | 对应任务 | 实际状态/证据范围 |
| --- | --- | --- |
| FR-001 | T002、T025、T039–T049 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-002 | T003、T013–T018、T021 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-003 | T009–T018、T021 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-004 | T025–T028、T032、T062、T071 | partial；两档独立已实现；Pro协作held，未交付 |
| FR-005 | T004、T025、T030、T041–T043、T053–T055、T063–T066、T091 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-006 | T031、T034–T038 | passed（限定Linux/实际绑定）；本地UI、共享模型切换/继续/分支/压缩及有界合成读写检索/固定命令通过；见本轮交付验收 |
| FR-007 | T027、T034、T043、T047、T065、T078 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-008 | T009、T013、T022、T024–T030 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-009 | T013、T014、T019、T022、T029、T031、T055、T074 | passed（公共与本轮选择）；配置/偏好/恢复保护、四模块禁用重选与服务证据完成；Brave/Cursor真实账号按用户决定延后 |
| FR-010 | T005–T006、T019、T034、T039、T080、T091 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-011 | T012、T016–T019、T026、T030、T037 | passed（限定Linux）；真实双主独立归属、维护4/4/0与完整退出观察、实际回环SSH/tmux通过；非root服务端255限制保留 |
| FR-012 | T010、T014、T029、T036 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-013 | T010、T014、T039、T040、T048 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-014 | T012、T016–T018、T037、T039、T044、T068 | partial；A/B/C正常退出13个owner均完整观察后空闲；旧unknown不清除，崩溃/Pro等未验 |
| FR-015 | T011、T018–T019、T023–T024、T028、T030、T032–T033、T075 | passed（本轮选择）；完整锁/显式维护/未选零副作用及四模块组合测量已完成；无隐式安装或登录 |
| FR-016 | T004、T011、T015、T023、T027–T028、T032–T033、T055、T066、T075、T081、T091 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-017 | T002、T022、T025、T039、T041–T049、T093 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-018 | T002、T022、T025、T039–T049 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-019 | T050–T051、T056、T059 | passed；十类有明确处置，多轮/压缩统计与正缓存通过；用户明确接受三处差异，费用无来源unknown |
| FR-020 | T057–T059 | passed（限定Linux）；60/90/130列与回环SSH90列交互、实际中断恢复通过；窄屏收拢获明确接受 |
| FR-021 | T051、T056–T058 | passed（明确统计范围）；续开/分支/reload、多轮/压缩与正缓存通过，真实账单不伪造；Pro未启用不承诺子调查统计 |
| FR-022 | T050–T055、T059 | passed；公开API替代footer完成信息门，Powerline仍held；用户接受权限说明/分支均速/窄屏详情 |
| FR-023 | T060–T071 | partial；准入拒绝/合成契约通过；真实协作未交付 |
| FR-024 | T061、T063–T066、T070–T071 | partial；真实只读/递归/后台/并发闭包未通过 |
| FR-025 | T061、T063、T067–T070、T083 | partial；观察维度合成定义；候选结果/取消集成未实现 |
| FR-026 | T026、T060、T062–T064、T071 | partial；not_ready正确报告；Pro交付门开放 |
| FR-027 | T072–T087 | passed（本轮四模块）；选择/准入/六场景/组合/退出与适用测量完成，未选零副作用有隔离和真实禁用证据 |
| FR-028 | T072、T074、T076–T085、T087 | passed（本轮四模块）；Context7实际服务、浏览器合成页面和footer/cache实际usage通过；Brave/Cursor真实账号明确延后 |
| FR-029 | T040、T083–T084 | partial；tmux/日志交接资料；会话内进程候选未准入 |
| FR-030 | T004、T053、T063、T073、T076、T079、T082、T086 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-031 | T004、T032、T075、T086–T087 | passed（限定Linux/四模块）；固定源/完整锁/按选重锁重验与测量完成；其他平台未声明通过 |
| FR-032 | T001、T007、T020、T038、T059、T067、T071、T074、T085、T087–T089、T092、T095 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| FR-033 | T005、T007–T012、T021–T024、T035–T039、T048、T058、T069–T070、T084–T085、T088、T092–T093 | partial（完整feature）；已记录隔离/双路径/Linux原生与共享模型/有界工具通过；Pro真实协作及其他平台仍未验 |
| FR-034 | T089–T090、T095 | passed（管理/静态层）；对应公共/新Base隔离、完整锁或静态来源；原生范围另见A/B/C记录 |
| SC-001 | T002、T022、T025、T039–T049、T093：100%处置及零旧依赖 | passed；旧源/发行路径零消费者；用户状态原位保留 |
| SC-002 | T003、T009–T021：七类公共场景及差分证据 | passed；七类公共管理隔离539及退役受影响900例 |
| SC-003 | T032–T038、T092、T095：每声明平台双路径干净重建 | passed；仅Linux x86_64管理器/依赖双路径；不外推原生 |
| SC-004 | T034–T038：六类Base用户场景 | passed（限定实际绑定/合成文件）；六类Base场景通过，有界guard只属验收，不声称生产权限保护 |
| SC-005 | T051、T054–T059：十类信息、三种宽度、未知及差异接受 | passed（限定Linux）；三宽度/回环SSH、多轮/压缩/正cache与十类处置通过；三处差异获用户明确接受 |
| SC-006 | T061、T064–T071：六类协作、每主2/两主4与禁止越界 | not_ready；无合格协作候选；合成契约不抵扣 |
| SC-007 | T072–T087：所选模块六场景与未选零加载/连接/后台 | passed（明确选择交付四模块）；六场景和所选组合通过，未选零副作用通过；性能另由T086记录，Brave/Cursor真实账号明确延后 |
| SC-008 | T010–T021、T036–T040、T044、T048、T068：状态保护、恢复、幂等及多主维护 | partial；配置保护及真实双主维护4/4/0通过；13次正常原生退出归属完整，异常/Pro待验 |
| SC-009 | T007、T020、T038、T058–T059、T067–T071、T085、T088、T091–T096：声明可追溯 | passed；支持声明限定组合/层级，未执行如实保留 |
| SC-010 | T089–T090、T095–T096：临时材料及失效引用归零 | passed（当前树）；八份临时材料已退出，来源承接及公开/feature链接检查通过 |
| US1/AC1 | T009、T013、T021 | passed；配置/覆盖/选择契约 |
| US1/AC2 | T010、T014、T021 | passed；三方/非受管/漂移/冲突 |
| US1/AC3 | T010–T012、T015–T018、T021 | passed；缺损/中断/活动分列、无隐式副作用 |
| US1/AC4 | T011–T012、T017–T021 | passed；跨工具/配方合成哨兵 |
| US1/AC5 | T012、T016–T018、T021、T037 | passed（Linux正常多主）；独立登记、退出一主不清另一主、维护阻断及完整释放通过；Pro有独立门 |
| US2/AC1 | T025–T036 | passed；两路径同锁54artifact、0手调 |
| US2/AC2 | T027、T031、T034、T038 | passed；简单真实工具任务无强制计划/Todo/工作树/子代理；合成文件与固定命令在显式验收guard下通过 |
| US2/AC3 | T024、T030、T037–T038 | passed（限定共享默认账号/无工具）；真实切模型/继续/分支/压缩及正常退出通过 |
| US2/AC4 | T026、T035、T060–T062、T072 | passed；held Pro/未选模块不阻断Base |
| US3/AC1 | T002–T003、T022、T025、T039、T041–T049 | passed；消费者盘点/公共用途迁移 |
| US3/AC2 | T041–T049 | passed；旧源/发行/发现链退出 |
| US3/AC3 | T039–T040、T044、T048 | passed；旧owner未知阻断；不读/删原生状态 |
| US3/AC4 | T010、T014、T039–T040、T048 | passed；配置恢复/回滚不回滚软件任务数据 |
| US4/AC1 | T051、T055、T057–T059 | passed（限定Linux）；三宽度/中文/tmux/SSH/reload与活动/context可辨认；窄屏详情获明确接受 |
| US4/AC2 | T051、T056、T058–T059 | passed；真实用量/正cache、多轮/分支/reload/压缩范围正确；费用unknown，三处差异获接受 |
| US4/AC3 | T056、T058–T059 | passed；继续/分支不重复，多轮/压缩摘要不重复累计；Pro未启用，不将未提供子调查统计当通过 |
| US4/AC4 | T050–T054、T059 | passed；Powerline保持held，公开API替代footer交付，三处差异获明确接受 |
| US5/AC1 | T061、T064–T070 | not_ready；候选未准入，无生产调查 |
| US5/AC2 | T061、T065–T068、T070 | not_ready；合成越界拒绝不证明第三方 |
| US5/AC3 | T067–T070 | not_ready；当前结果/取消/后代回执未集成 |
| US5/AC4 | T060、T062–T064、T071 | passed；不合格请求exit2/not_ready，不恢复旧平台 |
| US5/AC5 | T061、T066–T070 | not_ready；两主4仅合成定义，未有候选集成 |
| US6/AC1 | T004、T073–T083、T086 | passed（当前选择/比较范围）；精确来源、逐模块SDK用量及匹配fresh应用级首次/重复/进程/RSS已测；不作更快/省token主张 |
| US6/AC2 | T072、T075、T084 | passed；默认未选外部模块0入口/连接/后台有隔离证据；A原生仅host/theme |
| US6/AC3 | T074、T076–T085 | passed（明确选择四模块）；所需原生/服务场景通过，缺前提/失败保留；Brave/Cursor真实账号经用户明确延后 |
| US6/AC4 | T075、T086–T087、T092 | passed（限定Linux/四模块）；完整锁/按选失效管线、实际重锁/禁用重选及测量收口；其他平台未验 |

T048退役后双路径：相同方法/12条管理命令、同Pi锁、Node24.14.0/npm11.9.0，
冻结管理来源摘要`5274d040ef5e09ddd929010201ed5f57bc8a8ff5f3b9f038aa4a10feb3044e71`，
两个全新路径均passed/exit0；54个artifact语义摘要及运行身份4f226775…c23e24相同，0手调、重复apply无变化/不轮换previous。
加载/原生/账号未运行。该快照只复制当前src等公开管理输入；目录中不存在91个退役模块、旧运行平台或旧Pi锁。
收据包含独立法律材料及119包安装树；没有为通过而修改npm包或忽略未知脚本。

## T089/T090/T092 正式文档与支持边界

README/zh、AGENTS项目说明、architecture/adapters/getting-started、Pi指南/迁移/支持矩阵、索引/known-issues/roadmap/worktrees
已与稳定实现对齐。八份临时研究的有效决议与限制承接正式指南/feature资料，160个去重公共来源完整承接pi-support bibliography；
十份旧Pi/OpenSpec指南保留历史正文且加顶部历史范围标记，不作为当前入口。八临时文件及有效旧链接均0。
实际`../../../.venv/bin/python -B scripts/check-public-docs.py`返回PASS/findings[]、exit0；`git diff --check`exit0；
feature Markdown相对文件/heading链接另核无缺失。初始旧draft headings及2个已删script链接失败已修正，未改checker忽略规则。
支持矩阵仅将Linux x86_64依赖/管理重建列为有证据，macOS与其他架构、原生/账号分别not_run；CI配置不算已执行。

## T091：稳定公开来源、许可和内容审阅

首轮最终回归前的管理来源/测试输入摘要为`f123e6100cc71df04e0f6c72424d1c778fcb9fa09bf7027e361f52d5f1252d99`，
514个文件，范围为当前公开src/agents/shared/schemas/profiles/locks/tests、pyproject/uv.lock及CI workflow，
不含已删文件、缓存、真实账号/认证/会话或本验收文件，算法为按路径排序的[path,mode,sha256(body)]紧凑JSON的SHA256。
该摘要识别未提交候选；不能当作已准备合入的commit。目标main仍93e4f789…84ce，HEAD仍8ac50aaa…9c6。

公开checker完整树与feature相对链接/heading检查通过。另加凭据前缀/私钥头/URL用户信息/临时认证链接模式扫描，
只输出相对位置和类别；23处命中经scout逐项核查均为脱敏/策略拒绝/历史隔离/不复制等合成负向测试，未决0。
判据为reserved .invalid/.test域、CANARY/Sentinel、短私钥占位正文、拒绝或不回显断言；没有仅因HEAD已有就自动豁免。
唯一有改动命中文件test_pi_inventory的凭据URL属于.test域合成不复制用例；其余文件与HEAD相同且场景独立核实。
原始模式扫描保留FAIL/23供审阅，分类审阅结论passed；未修改生产checker或加入忽略规则。
这是有限当前公开内容审阅，不证明历史从未含凭据；未读取真实密钥/账号/会话来验证清理。

Pi锁522bed3a…396e7与两recipe逐项复核通过，各119包，held包0。完整闭包的来源URI/SRI/版本/声明许可在锁中，
实际安装树经收据完整散列；官方宿主缺LICENSE由固定SHA256的独立MIT法律材料承接，不向宿主目录打补丁。
主题实际LICENSE随包保留；传递依赖实际随包法律文件由完整树覆盖，但未另建逐包法律正文索引，不声称完成独立法律审计。
两轮真实依赖准备均ignore-scripts；未知生命周期/implicit binding.gyp、配方/正文/收据/许可漂移有隔离拒绝证据。
补充“调用者伪造PiLock”3种损坏隔离测试3 passed/exit0，安装和实例写入前拒绝。

OMP重锁语义审阅：上游tag/commit/assets/source/upstream/package/interpreter均与原锁相同，
仅shared/content.toml配方摘要变化，73项被移除资源全部属于退役model-delegate Skill，
一个保留的cpp-database-kernel Skill正文摘要更新，没有额外资源加入。
DSH锁保持f9da5fd8…8d15。旧Pi补丁/SDK执行链删除，保留法律材料不含可执行平台归档；
没有修改上游源码、npm包正文、官方二进制或缓存副本。公开锁维护是审阅后的显式行为，不由run隐式重建。

T093首轮最终回归失败：40文件受影响集合在`test_omp_secret_boundaries.py::test_literal_native_secret_never_enters_reports_or_backups[plan]`
初始化处停止，490 passed/1 failed、exit1、446.85s。`test_omp_pipeline.full_workspace`临时仓库未复制新Pi schema，
完整catalog在PiAdapter._schema处正确拒绝；未进入原生秘密操作，也没有秘密泄露证据。
由executor迁移公开测试夹具，不放宽生产校验或取消全catalog；修订后重验所有helper消费者与首轮尚未运行部分，
已经通过且不受此次纯fixture变更影响的前段不重复全量运行。该失败不记为通过。

T093夹具修复：仅`tests/test_omp_pipeline.py::full_workspace`新增注释及copytree两行，复制完整agents/pi/schemas；
保留Pi注册和严格校验，未改生产src/锁/保护。原失败单例先复现再1 passed/exit0/6.08s；
`../../../.venv/bin/python -B -m pytest tests/test_omp_secret_boundaries.py tests/test_omp_capture.py tests/test_omp_pipeline.py tests/test_omp_migration_flow.py tests/test_omp_kernel.py tests/test_omp_permission_runtime.py -q --tb=short -x`
最终96 passed、exit0、140.97s。全tests的公开来源复制和临时全catalog构造静态扫描只发现这一缺口；
直接full_workspace与间接permission_workspace消费者全部覆盖，AST/diff检查exit0。

该唯一后续源输入变更后，最终摘要更新为`7ce2ea686ff9999c208d9eafc9df46330d4fd7039dcfc62e699f1b7590b6266e`，
仍514文件/同算法/同范围；前文f123e610…2d99识别的是首轮最终回归候选，不当作本次修复后的最终身份。
生产源码/资源/锁未变，T036/T048双路径证据仍适用；前490通过用例不消费变更的fixture，
相关消费者以本96例重验。新增fixture两行及补充静态候选资料已定向复核，无真实凭据或失效本地链接。

## T093–T096前次阶段检查点（继续实施前）

后半27文件回归578 passed/exit0/224.66s，加上不受最终fixture变更影响的首段490及修复后96个OMP消费者，
最终受影响范围共1164例通过。确切三组argv、原整体失败、最后fixture diff及最终来源摘要见[final-verification](final-verification.md)。
没有扩大为全仓库/CI或原生/账号通过声明。T094目标main及HEAD未移动，无新历史/身份变更；T095正式命令/测试入口及恢复指引已核对。
T096未完成：T037/T038、T054/T059、T064/T071、T075及相关US6交付链、完整后代释放与状态栏差异接受仍未闭合。
任务63/96完成；没有归档、提交、合并或远端更新。

## 继续实施证据：当前实现与前次检查点分开

此前63/96和7ce2ea68…来源摘要是继续实施前的历史检查点，不能当作下面新增源码的最终身份。
候选分支/HEAD/目标main未移动；executor角色配置gpt-6.1-sol/medium负责薄适配，
scout配置gpt-6-luna/high负责精确公开来源和调用链证据；主代理决定公共锁/恢复/释放语义。
未另行切换模型，不把代理无法自证的内部运行模型ID当事实。

| 场景与实际argv | exit/结果 | 层级与限制 |
| --- | --- | --- |
| `../../../.venv/bin/python -B -m pytest tests/test_pi_optional_modules.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_lock_publication.py -q --tb=short -x` | 0；254 passed/102.27s | 默认隔离；固定三模块选择、缺凭据、失败、取消、禁用、组合和密封支持；不证明服务执行 |
| `../../../.venv/bin/python -B -m pytest tests/test_pi_status_contract.py tests/test_pi_status_admission.py tests/test_pi_optional_modules.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_lock_publication.py -q --tb=short -x` | 0；267 passed/113.86s | 默认隔离；补footer显式选择/初始化/保留偏好/按选身份；未加载社区代码 |
| `../../../.venv/bin/python -B -m pytest tests/test_descendant_release.py tests/test_instance_admission.py tests/test_run_owner_integration.py tests/test_lifecycle_leases.py tests/test_deployment.py tests/test_pi_mcp_reference_guard.py -q --tb=short -x` | 0；118 passed/47.76s | 默认隔离；本次后代完整观察、单主释放不清其他owner、旧unknown和无效proof拒绝、空容器来源及恢复 |
| `node tests/pi_status_observer.test.mjs` | 0；5 tests/5 passed | 自有JS+合成公开API；分支/未知费用/cache分母/模型切换/60/90/130意图/生命周期；不执行Pi/社区渲染 |

真实Linux内核探针只fork自有短命Python后代：double-fork+setsid、父退出而孤儿存活时无释放证明，
孤儿自行结束且ECHILD后才确认；exit0，无信号、第三方宿主或凭据访问。它不抵扣T037真实宿主场景。

真实可选组合维护使用私有临时checkout/HOME，逐项运行管理器`lock --agent pi`、validate、sync、apply、
doctor、再次apply，全部exit0；npm全程ignore-scripts，无宿主/服务/模型调用。
footer-only完整锁120包，identity `82f5b4acf835769384252cbdf5c4d05a1800de72a619c377b22591e994b978c4`，
recipe `d79b56ba5c85e9c023c8b6c4cf2e4af272e7600e4863de20aefcc0d6c6640aac`。
footer+cache+Context7+Brave完整锁245包，identity
`8104719b27eb395bd516eee979cdcf37ac9f2e3b8203f04e3b54bcbf55aaec66`，recipe
`902dba5e22720049a41283a942f770801fe7afd71dbc3e9f0ba13093fa0aba03`。
两个组合的Pro slice保持公开默认；实际六组argv和退出码只在私有commands.json保留，
公开规范化变量为独立临时repo/local/home；原始日志不含账号，未向公开树复制私人绝对路径。
doctor的dependencies/deployment=passed，loading/runtime=not_run，重复apply changes=0。
首次在选择改变后直接validate正确exit2 stale lock；改为显式lock先行后全部通过，不放宽校验。
正式仓库默认锁仍无外部所选模块，没有拿临时可选锁替换默认配方。

独立静态检查还发现pending恢复可在后续凭据冲突前恢复较早文件。主代理补充全受管引用预检，
在任何recover/rollback目标写入之前覆盖当前与待恢复集合；新增两条多文件pending哨兵回归。
首轮5文件集合80 passed后受系统盘ENOSPC中止（exit1），不是通过；沙箱只读探针也因无空间exit101。
仅清理本任务两份可再生npm下载缓存，保留锁、原始审计、来源和状态；空间恢复后重跑受影响集合。
网络namespace能力用`unshare --user --map-root-user --net true`检查exit0，仅自有命名空间不启动第三方。

[原生方案](native-validation-plan.md)已准备，A/B/C无账号隔离原生授权问题已提出，未收到明确授权前不执行。
D/E服务联网、账号/模型、费用、SSH/tmux/macOS均另有前提，仍not_run。Pro的不可绕私有探测见
module-admission第11节，T064未通过，后续不得以合成策略执行者顶替真实插件。

当前稳定增量的后续检查：

- `../../../.venv/bin/python -B -m pytest tests/test_deployment.py tests/test_pi_mcp_reference_guard.py tests/test_pi_optional_modules.py tests/test_omp_secret_boundaries.py tests/test_lock_publication.py -q --tb=short -x`：160 passed、exit0、88.77s（ENOSPC恢复后完整重跑）。
- `../../../.venv/bin/python -B -m pytest tests/test_pi_status_contract.py tests/test_pi_status_admission.py tests/test_descendant_release.py -q --tb=short -x`：30 passed、exit0、15.34s。
- `../../../.venv/bin/python -B -m pytest tests/test_dsh_pipeline.py tests/test_omp_pipeline.py tests/test_omp_capture.py tests/test_omp_kernel.py tests/test_omp_migration_flow.py tests/test_omp_permission_runtime.py tests/test_pi_reboot_pipeline.py -q --tb=short -x`：97 passed、exit0、172.09s；运行前确认空间足够，未再ENOSPC。

新增shared恢复预检后，所选Pi、OMP凭据、DSH/OMP/Pi完整消费者均有实际隔离结果；
原生/账号/服务和托管CI仍not_run。不将重叠集合相加为唯一用例总数。

## 浏览器、Cursor与方法资源继续实施的实际依赖证据

同一独立私有临时checkout选择footer/cache/Context7/Brave/Cursor/Playwright和两种方法Skill，
使用虚构cursor remote model、空Brave key，只执行管理器维护，不执行宿主/浏览器/服务/模型。
来源摘要`086ad4b0d9a956d2c3f20cb502770ffaf18f09c5466e995782a31f07c945f183`，
305个src/agents/shared/schemas/profiles文件，相对路径/mode/正文SHA256排序compact JSON算法。
以下是真实命令模板；实际完整argv/退出码和私有路径只在该场景commands.json保存，
`$selection_python/$selection_local`指其已声明解释器/临时绑定，不作为可直接执行的路径。

```sh
$selection_python -B -m agentcfg --local "$selection_local" --profile pi-base lock --format json --agent pi
$selection_python -B -m agentcfg --local "$selection_local" --profile pi-base validate --format json
$selection_python -B -m agentcfg --local "$selection_local" --profile pi-base sync --format json
$selection_python -B -m agentcfg --local "$selection_local" --profile pi-base apply --format json
$selection_python -B -m agentcfg --local "$selection_local" --profile pi-base doctor --format json
$selection_python -B -m agentcfg --local "$selection_local" --profile pi-base apply --format json
```

六步均exit0，250包，23条原始manifest/lifecycle审计，npm全部ignore-scripts。
锁identity `b606b1c0dc52b01f9a60e489dffffc43e9238dd808afe91924a7f81679d194d6`，
选中slice recipe `94adc9b65877265fea2093da2bbae276551642e02f44eb51541b9d45189ec2d4`；
另一个Pro slice仍为公开默认。doctor dependencies/deployment=passed，loading/runtime=not_run，
重复apply changes=0，官方宿主/插件/浏览器/服务启动0次、模型调用0次。
Brave key为空不影响离线准备，绝不记账号/服务ready。此所选锁仅存在临时副本，没有覆盖默认正式锁。

实际锁中的Playwright0.1.22→playwright/core精确alpha、Cursor1.4.39→protobuf2.13.0及
SRI均与静态审包一致；无新的未审核生命周期。Cursor prepare只接受已发布dist的忽略决定，
不执行缺失脚本/浮动npx。完整发布法律材料与文件保留，不修改上游。

新增隔离命令：`../../../.venv/bin/python -B -m pytest tests/test_dsh_pipeline.py tests/test_omp_pipeline.py tests/test_pi_method_resources.py -q --tb=short -x`
为20 passed、exit0、53.65s。覆盖新公共catalog声明的DSH/OMP入口与两种静态方法资源，不启动真实宿主。
方法测试首次缺fixture导入是setup error，补齐后通过，随后两资源参数化2 passed。
公开文档检查首次误用系统低版本python3而缺Path.is_relative_to，exit1；改用项目3.11解释器后
PASS/findings0，不改脚本或降低项目Python版本要求。

### T078–T084最终隔离证据与模块×场景

生产源码固定后，下列完整定向集合396 passed、exit0、184.49s：

```sh
../../../.venv/bin/python -B -m pytest tests/test_pi_cursor_module.py tests/test_pi_browser_module.py tests/test_pi_optional_modules.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_lock_publication.py tests/test_pi_status_contract.py tests/test_pi_status_admission.py tests/test_config_examples.py tests/test_config_resolution.py -q --tb=short -x
```

全套collection后补充的六路取消专项6 passed、exit0、11.35s，只有测试追加，生产来源不变：

```sh
../../../.venv/bin/python -B -m pytest tests/test_pi_optional_modules.py::test_selected_fake_cancellation_preserves_unknown_owner tests/test_pi_cursor_module.py::test_cursor_fake_cancellation_keeps_unknown_and_blocks_maintenance -q --tb=short -x
```

原始日志0600；该专项与全套有重叠，不累计为唯一用例数。执行者配置gpt-6.1-sol/medium，
scout配置gpt-6-luna/high核对来源与静态边界；主代理审核准入/脚本、锁、环境与恢复语义。

下表只表示**管理器隔离场景**的证据，不把假CLI的正常返回当真实插件、服务或浏览器成功。
“退出”栏保留unknown是正确管理行为，不表示后代已退出；真实六场景整体仍属T085。

| 选项 | 启用/完整锁 | 正常管理路径 | 缺前提/漂移 | 失败/取消 | 禁用 | 退出/归属 |
| --- | --- | --- | --- | --- | --- | --- |
| cache-hit-monitor | 固定包/入口按选，默认0加载 | 假CLI返回与显式-e | 密封运行包/入口校验，usage缺失不造0 | 单独取消→unknown，禁止维护 | 不再-e；状态保留 | 同公共owner规则，不以退出文本证明释放 |
| pi-footer | 固定社区入口+observer-last | 初始化模板，保留后续偏好 | 源码/配置输入漂移拒绝；窄屏意图合成测试 | 单独取消→unknown，禁止维护 | 不再加载；偏好保留 | hooks真实清理not_run，不冒充passed |
| Context7 | 精确stdio闭包、仅白名单工具 | 假CLI和固定引用/清洗环境 | 已声明key缺失exit3；cwd/引用/入口漂移拒绝 | 单独取消→unknown，禁止维护 | 去配置/空自建容器；缓存保留 | 服务真实退出not_run，后代未知不清owner |
| Brave | 精确stdio闭包、仅brave_web_search | 假CLI和固定引用/清洗环境 | 必需key缺失exit3；非法command/env拒绝 | 单独取消→unknown，禁止维护 | 停后续连接；缓存/auth保留 | 不以白名单推断实际费用或退出 |
| Playwright Skill/CLI | 精确包、完整原始Skill/10指南/LICENSE | 假exec固定私有session/PATH/cwd/env | bin/目录/自动config异常拒绝；真实二进制未验证 | 单独取消→unknown，禁止维护 | 删受管入口；cache/下载保留 | daemon/浏览器真实退出not_run |
| Cursor | 精确包、明确非官方OAuth owner | 假CLI固定route；离线不读auth | provider/plugin不匹配、缓存/最终env漂移拒绝；账号仍未验证 | 单独取消→unknown，禁止维护 | 停后续加载；auth/cache/journal保留 | 原生认证刷新/真实后代not_run |
| 两种方法Skill | 完整源目录按选摘要，无新增npm/tool | 静态部署与未选slice独立 | 所选来源改变报锁失配；项目工具缺失记未验证 | 不启动进程，无取消hook | 不再部署选择，无后台连接 | 项目命令归其所有者，不伪称由Pi释放 |

所有默认未选外部模块均无-e、MCP连接或后台启动；预览不能spawn/install，实例哨兵不变。
Web-access两候选、pi-tool、未闭合ast-grep扩展和processes/PTY候选明确未注册，拒绝启用；
选择理由和精确静态比较见module-admission第7/8/13节。Cursor和已接通可选组合保持
selected/not_verified，不因缺账号、浏览器或原生授权改记not_selected。
T078–T084产物与隔离层闭合，T085–T087及T096仍开放，不作性能或完整feature通过主张。

稳定新增代码/资源的独立scout静态终审未发现critical/high问题；完整上游Skill/10指南/许可
与固定tar原字节一致，默认锁不加载未选模块。新增范围有限隐私扫描只命中保留域名、说明路径
和合成归档名误报，未发现实际凭据或私人工作区绝对路径；不扩张为全历史清理结论。
该历史检查点公共检查PASS/findings0，本地链接缺失0，diffcheck0；旧记录的文档总数不作当前范围依据，
当前固定清单为39份/189个本地链接，见final-verification末尾复核。
来源快照直接导入首次漏设PYTHONPATH导致exit1；显式PYTHONPATH=src重做exit0，
305文件来源与真实npm准备一致、正式默认锁仍522bed3a…96e7，未改生产路径保护。

## A/B/C授权后的最新原生与修订证据

2026-10-19用户对具体A/B/C无账号范围答复“授权”，Linux本地可执行验证现已完成。
完整步骤、组合、argv模板、实际失败和未覆盖范围见[native-acceptance](native-acceptance.md)，
稳定审阅见[final-verification](final-verification.md)。前文各次无宿主/授权待答复记录均是当时检查点。
任务仍80/96；没有把T037/T058的本地部分、依赖准备或进程exit0写成完整功能交付。

当前生产/测试输入共544文件，范围src/agents/shared/schemas/profiles/locks/tests、
pyproject.toml、uv.lock和.github/workflows/tests.yml，排除node_modules/pycache/pyc；
按相对路径排序的`[path,mode,sha256(body)]`数组compact JSON再取SHA256：
`e35c65143baf7605773f618bb20fbb5a4c7c0423c5443280188b6d75aa925da5`。
当前305文件生产摘要39fa875a…70c1b及各锁完整身份见原生记录。
旧544摘要6c16bd33…和305摘要086ad4b0…均属于本轮observer修订前，不能冒充新B的来源。

| 任务/范围 | 层级/实际核查 | 退出码/结果 | 限制 |
| --- | --- | --- | --- |
| T037、本地A | 官方Pi1.3.0/主题0.1.6，version/help、tmux及裸PTY60/90/130列、中文粘贴/reload/正常退出 | exit0 / passed（本地范围） | 合成模型及占位key，无真实请求；SSH/账号相关场景未验 |
| T037、双主保护 | 同binding两个真实主会话；两主活动/一主活动/全退出分别apply | exit4/4/0 / passed | 正常退出且完整本次后代观察；不抵扣崩溃/Pro等场景 |
| T058、本地B | footer0.5.1+observer，完整身份/unknown、菜单恢复idle、偏好、三宽度/reload | 修订后exit0 / passed（本地范围） | 原始provider压缩/菜单滞留失败已修；窄屏第二行截短，未获完整差异接受 |
| T085、本地C部分 | cache-hit-monitor0.1.1显示/隐藏/reload/三宽度，waiting for provider cache usage | exit0 / passed（本地范围） | 实际cache/费用、其他选中模块及六场景完整门仍未验 |
| 两项observer修订 | `node tests/pi_status_observer.test.mjs`，Node24.14.0 | exit0 / 7 tests、7 pass | 自有代码fake API，先红后绿；不代表托管CI |
| 受影响Python两文件 | `../../../.venv/bin/python -B -m pytest tests/test_pi_status_contract.py tests/test_pi_status_admission.py -q --tb=short` | exit0 / 13 passed、11.30s | 临时HOME/XDG、阻网/假进程；保留生产路径保护 |

全部13次官方CLI正常exit0；功能语义仍按表分别判断。最终13个owner均idle_confirmed，
coverage complete，active/unknown 0；三组末次apply均0。27次Node新网络namespace入口
均核对只有lo、IPv4路由0；没有模型请求或真实登录。偏好逐字节保留，私有tmux关闭，裸PTY模式恢复。
独立scout对这两文件稳定增量及原生证据的有限终审无critical/high发现，不认证全部旧分支历史。

T037/T058仍partial：SSH缺可用远端终端，macOS/其他架构缺环境；真实账号/模型、usage/cache/费用、
运行中取消和会话继续/分支/压缩未执行。D–G不在本次授权范围，性能与Pro公开接口门未闭合。
T038/T059、T064–T071、T085–T087及T096开放；没有提交/合并/推送、发送上游消息或清理用户数据。

## 共享模型与D–G补充验收（当前检查点）

用户授权复用共享默认模型和SecretRef并要求密钥不能被模型读取；新隔离实例已实际使用，
无需已有运行实例。详细来源、完整锁、实际运行及限制见[补充验收](remaining-native-acceptance.md)。
该记录覆盖R、B/C真实usage、D–G限定范围及18次CLI性能样本；上一节not_run为历史状态。

当前544个生产/测试输入SHA256为
`20e57fb8410d61c53a021f176cdd0866bf787118035669024a0ff8d981d58742`，
305个生产输入SHA256为`44be2fa6fb13714ad2cf54a7e1e704fdb35fe988f728a3fcaab124f63cf635e4`。
范围、mode/正文SHA256排序compact JSON算法沿用前文；文档结果更新不进入摘要。
修订后的默认Pi锁仍522bed3a…；不将早期R/F/G使用的afa0be66…来源替换成未来摘要。

| 任务 | 新增实际证据 | 尚缺范围 |
| --- | --- | --- |
| T038 | 首次/继续/fork/第二模型/压缩及压缩后请求通过；全部--no-tools | 读写检索/命令工具、运行中模型取消 |
| T058/T059 | B真实1395/12与footer一致、续开/分支/reload不重复；C零缓存等待及reload通过 | 多轮/压缩/子任务统计、完整覆盖/差异接受、真实远端SSH |
| T085 | Context7原生及独立两次外部查询、固定Chromium合成DOM操作/退出；Brave/Cursor无账号加载 | 真实Brave凭据/搜索、Cursor本实例OAuth/权益、完整所选六场景 |
| T086 | A/B/C交错18次version/help全0，三次中位数wall/user/sys/RSS已记录 | OS冷启动、服务完整进程/初始context及匹配条件比较 |
| T064–T071 | 精确社区候选已刷新；用户决定继续社区插件、等待上游 | 无合格候选，保持未完成，不自建执行插件 |

修订后一次运行：

```sh
../../../.venv/bin/python -B -m pytest tests/test_pi_reboot_runtime.py tests/test_pi_reboot_dependencies.py tests/test_lock_publication.py tests/test_pi_reboot_pipeline.py tests/test_pi_browser_module.py tests/test_pi_optional_modules.py tests/test_pi_mcp_reference_guard.py tests/test_pi_core_contracts.py -q --tb=short -x
node tests/pi_status_observer.test.mjs
```

八文件324 passed、exit0、101.73s；自有observer7/7、exit0。默认测试保持临时HOME/XDG、阻网
及假进程，没有启动第三方宿主、读取凭据或网络调用；真实步骤在独立授权运行中完成。
此前依赖/publication155项、runtime64项、browser39项均为重叠定向证据，不累计成唯一用例总数。
独立scout核对本轮来源、锁、退出码、owner、服务与性能元数据未发现可复核差异；未读取密钥、
认证或会话正文，有限审查不代表整个分支历史/其他平台或托管CI通过。

任务仍80/96。Pro按用户决定等待上游，其余partial/环境缺项仍保留；T096未完成。

回环SSH后续补充：A/B/C各90列中文粘贴/清除/reload/CtrlD通过，client/manager均0，
sshd非root inetd exit255及login记录限制保留；三组owner A13/B12/C11均完整空闲，
所有fixture端口关闭、无模型请求。它是本地SSH传输/原生交互证据，不关闭真实远端/三宽度门。
首次认证前StrictModes拒绝及第二路线的具体官方接口见[补充验收](remaining-native-acceptance.md)。

B零新增请求的续开与fork打开各exit0，reload前后input1395/output12不重复累计，费用unknown。
这只覆盖该单请求样本；多轮新增/压缩/子任务统计和取消未验。全部原生结束后再次核对
A13/B14/C11/D2/E1/F4/G3/R6，共54个owner完整空闲，无active/unknown，临时SSH端口均关闭。

## 本轮明确决定及新增通过

[本轮交付验收](current-delivery-acceptance.md)记录用户接受三处状态差异、延后Brave/Cursor
真实账号及一次有界工具授权，包含实际argv边界/保护器身份、五次工具事件、取消/恢复/压缩
统计、正缓存、版本/源/锁、性能样本与所有权。T037/T038/T058/T059和T085–T087均已完成；
T064–T071及T096按用户决定继续开放。

## 本轮约定交付的最终闭合

最终来源与实际锁、六场景/组合及两组匹配fresh对照见[本轮交付验收](current-delivery-acceptance.md)。
T085–T087完成，任务87/96；Pro T064–T071和T096保持开放，Brave/Cursor真实账号按决定延后。
A/B/C/D/E/F/G/R加四个fresh实例共84条owner完整空闲，active/unknown0；F原local/锁恢复，
不删除owner或原生文件来制造通过。之前各段not_run/partial为对应历史检查点，当前矩阵已更新。
