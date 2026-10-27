# 受管入口部署契约

契约日期：2026-10-23。状态更新：2026-10-24 已获授权并在专用临时 HOME、受信源码副本与离线工具链通过真实 Linux zsh/Tab、入口绑定保持、显式换绑和回滚验收；日常入口未切换。实际范围及证据见[本轮记录](../main-review.md#19-真实-zsh-入口与-tab-验收)。
依据：[规格 FR-017–020](../spec.md#functional-requirements)、[数据模型](../data-model.md)。

## Herdr V1 的提交后交接

V1 在写 accepted 之前最后核验并保存 caller；accepted 后父进程可以正常清除 workspace pending。驻留包装使用已核验的 caller，不在 accepted 后重新要求 pending 存在。原 fixed command、namespace/source/tty、marked/accepted 错误分支及普通 shell fallback 保持；pending 清除不授予新的恢复许可，resident 仍核验实时 terminal 身份。

## 目标与安装定位

| 目标 | 内容 | mode |
| --- | --- | --- |
| `$HOME/.local/bin/rotom` | 固定协议的静态 launcher | 0700 |
| `$HOME/.local/share/rotom/entry.json` | EntryBinding v1 的确定性生成字节 | 0600 |
| `$HOME/.local/share/rotom/zsh/site-functions/_rotom` | 静态 zsh 补全 | 0644 |

部署时这些目标按计划中保存的有效 target HOME 定位，与入口偏好的 XDG_CONFIG_HOME 分开。
复用已有 PATH 去重；新 fpath 在 compinit 前加入。不得通过重启 shell、联网或启动宿主验收安装。
运行时 launcher 从自身经核实的普通安装文件路径及固定目录布局推导唯一 entry.json，
不使用调用者 HOME、XDG 或 cwd 重新选择绑定；不支持的安装布局、链接或文件身份变化明确失败。
静态 launcher 只读该唯一绑定，校验路径/协议/可信 checkout 和准备环境，再按 token exec 仓库入口。
其 sh 定位层调用 `python3 -I -S -B` 内嵌标准库解析器，隔离 Python 环境/site 自动导入，
不读取 stdin、不导入项目模块；再 exec 由仓库入口选择的准备 venv，所有业务仍需 Python 3.11+。
新仓库入口及 venv 交接也禁写 bytecode，help/补全不能通过导入生成 pycache；不能靠调用者环境变量保证这一点。
系统定位 Python 的缺失是明确依赖诊断，不能改用它执行项目代码、自动安装或扫描其它环境。
不 eval、不查找 main、不搜索其它 worktree，不隐式准备 venv；损坏时提供从已知 checkout 修复的诊断。
源码 `./rotom --help` 无需绑定；已安装 help 的定位层只能读取这一非秘密绑定。

## 显式来源与计划

新门面在 `term plan/apply` 提供 `--entry-repo PATH`，仅在选择 zsh 时合法。
第一次部署可将正在执行的可信 checkout 作为候选，但必须在计划中展示并接受。
已存在绑定默认保持，即使另一个 worktree 发起配置更新；换绑、搬迁修复必须显式指定来源并审阅。
目标 checkout 须具有所需入口/协议、准备环境与兼容 schema；校验不启动其 Python 或 shell。
不得因文件缺失从搜索结果改选另一份源码。

计划至少覆盖：machine、HOME、组件、当前 state/journal 身份、各目标写前身份和所有权、
静态内容摘要、生成器版本、输入/来源摘要、精确生成内容摘要与 mode、明确的原/新绑定。
真实来源或目标变化使 plan_id 失效。apply 在原 machine/repository lease 下重建并比较计划；
没有新的全局 `--yes` 能绕过 plan/adopt/zshenv 等批准。

## catalog/state/journal 兼容

- catalog v2 增加 static 与受限 rotom-entry-binding 两种形状；static 与 v1 字节/路径规则一致。
- 新读取器接受 catalog v1 与 v2，未知版本/字段拒绝。生成器不得读取凭据、原生会话或执行模板代码。
- 带生成产物或已有生成产物状态的操作写 state/journal v3；纯静态旧状态保持 v2。
- v2 与 v3 的 pending 恢复分别按各自严格 schema 处理；不自动升级活动 pending，也不将 v3 降版。
- 旧 checkout 无法读 v3 时明确拒绝受管写入；不能删除 journal、吞字段或用当前 catalog 伪造旧状态。

v3 journal 保留既有 before、backup、mode、写前/写后身份与 stage，并为生成条目记录
精确 desired payload 的受保护内容引用、sha256、kind、生成协议/来源摘要。
payload 在目标写入前 durable；不依赖将来的 checkout 仍存在或产生相同内容。

## 事务顺序与中断

1. 完整预检所有来源、目标、计划与权限；已 pending 则按原恢复流程处理，不能混入新目标。
2. 持久化生成 payload、全部 before/backup 与 prepared journal，确认必要的 fsync。
3. 沿既有逐文件事务写入静态启动器、补全及其它相关 zsh 文件，保存写后身份。
4. 最后原子替换 entry.json，使所审阅绑定生效；记录写后身份与 activated stage。
5. 写入完成状态及上一版备份，结束 journal；无变化不轮换备份。

绑定最后激活仅减少部分可见窗口，不是跨文件原子性。静态 launcher 必须接受其声明兼容的旧绑定；
协议不兼容时先拒绝计划，不能暂时安装一个无法解释现有绑定的 launcher。
进程或机器中断可能留下“新绑定已生效、journal 未收尾”；失败结果必须披露这一状态。

恢复先检查所有目标身份，再按 journal 逆序恢复已证明属于本事务的写入。
不重新解析 entry-repo，不读取当前模板来决定旧字节，来源仓库不可用也不影响已有 backup 的核实。
用户漂移、来源不明或缺少足够写后身份时返回 4 并保留 pending；当前字节等于 desired
不能单独替代所有权证明。rename 与 durable journal 之间的模糊窗口必须有模拟用例，
证据不足时报告“可能激活/需审阅”，不能删除或自动接管看似相同的文件。

rollback 使用记录的上一版内容和身份，不意味着软件降级或恢复旧进程。
没有旧绑定的首次部署回滚只移除已确认由本次创建且未漂移的目标，保留其它 shell 配置与私人文件。

## P-ENTRY 验收

| 场景 | 必须证明 |
| --- | --- |
| 首次安装与现有绑定 | 来源明确；跨 worktree 默认不换绑；没有 shell 执行 |
| 计划后来源/目标/schema 变化 | 旧 plan 被拒绝，不部分安装 |
| 每个 payload/journal/write/rename/fsync 窗口中断 | 可证明的写入恢复；不明窗口准确 pending，不谎称全旧或全新 |
| 绑定激活后 journal 未收尾 | 诊断实际激活可能性，既有备份保留 |
| 用户改动、链接替换、不安全祖先 | 拒绝覆盖，不放宽权限 |
| v1 catalog/v2 journal、v3 新状态与旧工具 | 新工具兼容恢复，旧工具失败而不静默迁移 |
| 仓库搬迁、源丢失、回滚 | 可用已存恢复依据；换绑重新审阅，不扫描其它 checkout |
| 完整机器配置与现有 launcher | 不解析密钥地验证兼容；真实终端验收另行授权 |
| 定位解释器与 exec 交接 | 路径含空格/Unicode、stdin/argv/退出/信号保持；定位层无 site/PYTHONPATH 导入，业务只用准备 venv |
| 调用环境改变 | 从不同 HOME/XDG/cwd 调用同一已安装文件仍定位同一绑定；不读取另一 HOME 的同名文件 |

默认验证均使用临时 HOME/XDG、假文件和故障注入；真实 zsh/终端加载不能由上述模拟代替。


## 位置恢复候选与入口绑定

本次驻留和新 tab 恢复复用已经准备好的仓库入口，不增设日常 launcher、不自动切换 checkout，也不改变 entry.json 的批准/回滚语义。内部 child/resident 使用固定仓库 `.venv/bin/python -B` 与固定脚本路径，业务导入锁定该 checkout；受保护请求不能提供任意 argv。驻留源码身份覆盖三个自有 Python 包与既有受审 schema，代码变化拒绝旧驻留进程混用新逻辑。此内部执行约束不代表公开位置组合已经验收，普通 rotom run 仍为单次启动。
