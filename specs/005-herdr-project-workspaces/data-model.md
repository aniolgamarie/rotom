# Phase 1 data model

这是原生组织和现有配置的扩展，不新增持久终端库存。接口见 [work-cli](contracts/work-cli.md) 与 [configuration](contracts/configuration.md)。

## Entities and validation

| Entity | Fields / invariants | Lifetime / relationships |
| --- | --- | --- |
| ProjectCheckout | canonical_root为现存Git checkout realpath；project_digest为UTF-8规范路径SHA256，64位小写hex；label只显示 | 身份=(所选endpoint, canonical_root)；完整路径每次用native worktree provenance复核，digest不替代路径 |
| SelectedServer | machine选择、binary、session；公开socket_path、O_PATH fd、st_dev/st_ino；ping version/protocol/capabilities | 单次操作；请求只连固定fd，不失败重连旧路径；无虚构boot UUID |
| ProjectWorkspace | native workspace_id、worktree.path；rw_project、rw_epoch、7个rw_ROLE、rw_pending | metadata随server存活；epoch为32位随机hex；项目不随cd/branch改变 |
| PurposeInstance | role、op、kind、native pane_id/terminal_id/tab_id、project/epoch、phase、commit | role∈shell/edit/build/debug/pi/codex/dsh；kind∈primary/extra；只从当前native成员确认 |
| WorkSelection | machine.work与machine.editor的非秘密选择；pi/dsh显式profile | 私人TOML，不解析SecretStore；Agent凭据只由既有run按需解析 |
| ManagedTarget | ID=herdr.config、component=herdr、source=terminals/herdr/config.toml、destination=.config/herdr/config.toml、sha256/mode | 复用termcfg v2 journal/ownership/previous；不拥有socket/session/cache/manifest |
| CandidateReceipt | release/tag/commit/asset URL+SHA256、磁盘/运行版本、配置/规则/集成来源与摘要 | 显式选版/安装/升级证据，不能只记版本 |
| BenchmarkRecord | fixture/manifest/policy/schema身份、非识别环境、授权类别、normalized_argv、私人原件digest/evidence_ref、批次/指标/判定 | 私人原件记录实际argv，公开仅规范化数组；见[benchmark](contracts/benchmark.md)，不存私有会话 |
| TaskEvidence | 已完成/进行中/失败待决策/环境不足未验证；normalized_argv/exit/evidence ref | 工程状态与指标结果分开，未执行不能通过；实际argv原件只在仓库外0700/0600存储 |

通用配置未知字段失败。项目路径可含空格、中文、引号、美元和反引号等字面字符，不得含NUL、换行或其他控制字符。私人配置路径沿用现有安全检查；Git symlink归一是另一边界，不能套用“拒绝所有链接”的私有配置规则误拒正常项目。

## Native metadata

只用公开report_metadata，不设TTL。patch最多16 keys、resource最多32 keys。本功能workspace最多10 keys、pane最多8 keys；key为ASCII字母数字/下划线且<=32 bytes，value为ASCII且<=80字符。其他来源占满容量则退出4，不清除别人metadata。

workspace source=`rotom-work-v1`：

| Key | Value |
| --- | --- |
| rw_project | 64位hex摘要 |
| rw_epoch | 32位随机hex，建立后不随enter改变 |
| rw_shell/rw_edit/rw_build/rw_debug/rw_pi/rw_codex/rw_dsh | absent、unknown或p:<32位op>:<pane_id> |
| rw_pending | <role>:<32位op>:<primary或extra>；无pending时clear |

pane keys为rw_project、rw_epoch、rw_role、rw_op、rw_kind、rw_commit、rw_phase、rw_error。父调用确认前五项并设commit=op；launcher写phase=ready/accepted/failed，error只用稳定非秘密错误码。仅无payload的原生初始shell例外，由父调用写phase=accepted归属标记。launcher source=`rotom-work-launch-v1`，父source=`rotom-work-v1`。不存命令、目录或会话正文。

primary值同时保存op和当前原生pane_id（总长仍<=80），以完整原生查询区分pane关闭、移动与metadata被清除；仅保存op不足以证明关闭，不另建终端清单。

writer对自己的resource/source使用严格递增monotonic_ns作为seq；父调用由flock串行，迟到旧patch不能覆盖新seq。候选必须通过公开seq抑制旧值/数值范围测试，否则拒绝自动变更。不同resource没有原子性保证。

## Workspace transitions

1. enter先验证Git和配置；非Git/无效路径退出2，零server创建/修改。
2. 锁内发现session确实不存在时可启动headless server，等API-ready；socket可连不是ready。保留原生初始临时工作区，不自动关闭。
3. worktree.open明确报告本次新建且同endpoint事实完整确认：初始pane可标shell primary，其余absent；父调用给这一个无payload的原生初始shell写完整project/epoch/role/op/kind、commit=op、phase=accepted标记，表示普通shell归属交接，不表示Agent执行。初始化不完整则unknown，不能猜补absent。
4. 已有workspace无有效epoch：native provenance确认项目后建立新epoch，所有角色unknown，不接管旧pane。这只确认项目，不声称恢复用途。
5. epoch/provenance一致：重复enter只focus，不重置角色。重复checkout映射、metadata矛盾或结果不明退出4。
6. 原server停止时固定endpoint失败，操作结束。新一轮enter可选新endpoint，按冷恢复规则重新确认。

## Purpose transitions

| Current fact | Request | Result |
| --- | --- | --- |
| 无已确认调用pane/项目 | open任意形式 | 4，指导enter；零创建/启动/attach |
| primary且当前成员/epoch/op/kind一致、phase=accepted且commit=op | 普通open | 只focus，零输入/cd/重启 |
| absent且workspace无pending | 普通open | pending→新tab→握手/commit→primary |
| unknown且无pending | 普通open | 4，保留对象 |
| 未决pending | 普通open/--new的新创建 | 4，不替代/取消/过期回收；已确认primary仍可只focus |
| primary | --new | 新extra，不替换primary |
| absent/unknown且无pending、无可确认primary | --new | 新primary，仅解除该role的unknown |
| 已知primary关闭/移出，完整同endpoint查询确认 | 后续open | 可转absent；保留已移动pane，不再认作原项目用途 |
| 多primary、标记矛盾或查询失败 | 自动操作 | unknown/4，不提升extra或按label认领 |
| 已登记primary后来phase=failed或commit不符/缺失 | 普通open | role转unknown/4，保留普通shell/pane，不重试启动；--new可明确建立新primary |

未决pending一律阻新创建，--new也退出4，不尝试取消旧意图。metadata检查/报告/exec非原子，不能用“尚无accepted”或超时推定旧launcher不可能启动。若完整证明同op已commit/accepted且成员仍相符，可完成原登记，不重复exec，再将--new判作extra；否则保留pending供用户显式处理。不得自动关闭pane/server来清理。已有primary不因--new替换；冷恢复清空metadata且无pending时，unknown的显式新增路径不受影响。

## New-pane handshake and failure windows

父调用在锁和总deadline内：验证依赖→写workspace pending→tab.create(cwd=checkout,env=结构化意图)→确认新pane ready(op)/当前成员→写pane commit→等accepted→单patch更新role并clear pending→focus。默认总期限30秒，受管pi/dsh open为60秒；payload保留父调用原绝对期限，launcher不能重新计时。shell/build/debug也走此路径，但没有任务命令。

payload另有selection_digest，绑定解析后的local配置路径与herdr_binary/session/editor/pi_profile/dsh_profile/codex_binary/codex_daemon七项普通选择；不摘要凭据。

launcher消费一次payload，确认endpoint dev/inode、epoch、provenance、pending/op与自身pane一致后自报ready；只有自身commit和workspace pending均匹配且未超deadline才报告accepted并exec。它不获取父flock，避免死锁。父最后patch失败可根据accepted只读对账，不重启工具。

创建超时/父崩溃可能留下未标记tab或pending；默认请求不得重试创建。无commit/过期则报错退普通shell，不关闭tab。ready/accepted仅是交接，不是应用登录或任务状态。exec失败在额外最多2秒内写failed/错误码并清该pane commit，保留错误；accepted请求可能已生效而失败标记也无法确认时退出launcher，不留下伪有效普通shell。失败上报不延长业务exec准入期限；不能把失败实例当已成功启动Agent。冷恢复无payload，只进普通shell，不执行历史意图。

即使pending已清，每次复用也重新检查该op的phase/commit。先accepted、后登记、再exec失败的窗口不得遗漏：观察到failed或commit矛盾时，原角色保守转unknown并报4，保留pane；明确--new可建立新primary，旧失败pane不被关闭或重新exec。rw_phase仅为Rotom启动交接状态，不能把Agent idle/working/完成等任务状态映射到它；应用后续任务状态不自动清除primary。跨查询时变化仍按非原子冲突处理，不宣称瞬时生命周期快照。

**已证明结果的登记**：下一次enter在同UID锁/固定endpoint内先核对pending。唯一同project/epoch/op成员明确failed且commit已清，可按原角色状态不变clear pending；failed是launcher不可逆的失败分支，之后只能退普通shell，不能因迟到commit重新进入业务exec。唯一同op明确accepted且commit匹配，可补登记primary/extra并clear pending，不再exec。failed/accepted矛盾、多匹配、缺marker或查询不完整均不能清除。这是完成已知结果登记，不是取消未决操作。

**仍无法证明的恢复**：保持4，不提供自动取消。用户可原生Goto/新建tab继续工作；工作区/project布局仍可使用。以原生只读workspace/pane查询核对，若后来出现可证明failed/accepted，再enter登记。仍无证明时须待该server全部任务自然结束，在用户明确确认无存量任务并授权停服后，采用原生session stop与重新enter的冷恢复流程；绝不为了清pending自动停止任务。冷恢复后原布局用途unknown，再显式--new建立所需新primary。这条较慢路径是公开能力不足时的明确限制，步骤见[CLI runbook](contracts/work-cli.md#pending-recovery-runbook)。

锁为Linux每UID固定 `/tmp/rotom-work-UID/operation.lock`，父0700/文件0600、同用户普通文件、O_NOFOLLOW、永不unlink，与machine/local的state_root无关。手工native操作不受锁约束：请求显式目标，使用前后重查归属；变化报冲突，不发启动输入。不能承诺多次API全局事务。

## Deployment and upgrade

termcfg沿用plan→adopt→apply/pending/recover→previous→rollback；无变化不轮换备份。未选herdr的旧machine/state不迁移不重写。v2只扩enum和可选herdr previous键；旧代码不懂新记录，先恢复pending再代码回退。

候选：显式stable选择→资产校验→隔离验证→适用真实客户端→新工作canary→显式切未来入口。旧任务保留。binary/配置/native状态分别验证回退；入口切回不是进程迁移。无已验收基线只能first-baseline测量，不能升级回归PASS。
