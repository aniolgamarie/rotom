# Base 运行文件声明的共享解析模块缺口

2026-10-07 root 实施包。当前 `pi-base` 的 105 条显式运行文件行遗漏 `src/agentcfg/pi_lock_resolution.py`。当前 AST 证据链为 `scripts/pi-supervisor.py` → `pi_host.py` → `workspace_leases.py` → `pi_registered_roots.py` → `pi_dependencies.py` → `pi_lock_resolution.py`，均为顶层导入。最后一项的顶层本地依赖只有已声明的 `config.py` 与 `paths.py`。这是当前静态 Base 完整性缺口，尚未观察到产品启动失败。

历史 Base 导入图没有大多数逐文件源码 pin；最新差量按当前声明的 25 个 TS 和 64 个 Python/script 文件提取导入，发现已有 TS 新边的目标均已声明。只接受这个有界结论，不能把节点名单或历史图当当前完整动态闭包。此前 Full capture 缺项中的 `pi_lock_resolution.py` 同时是 Base 必需；其余 14 个缺项不由此变成 Base 必需。

## 唯一变更与不变量

唯一 writer 只改 `agents/pi/dependencies-modern.json` 与新增 `tests/test_pi_base_declared_import.py`。在 `pi-base.runtime_files` 加唯一行：source 为 `src/agentcfg/pi_lock_resolution.py`，path 为 `supervisor/src/agentcfg/pi_lock_resolution.py`，transform 为 `copy`，按原声明排序插入。声明不加 mode；原 `lock_files` 负责生成锁行的 `0600`。删除这一行后的整个 JSON 须与原声明深相等；实际原声明字节保存审计，不在永久 pytest 中固定整个文件 hash。

不改 npm 版本、provider/选择绑定、正式锁、任何生产 Python/TS、launcher 的 REQUIRED、上游源码或缓存。保留 Base profile/资源选择；不声明、加载或初始化 Full 服务。M1、B3/B4 和所有旧测试保持只读。不得通过假 validator、扩大清单到任意源码或恢复网络/子进程守卫消除缺模块错误。

## 有意义的默认回归

新测试从当前声明读取 Base rows，实际使用原 `lock_files`、`install_files`、`validate_files` 在独占临时目录物化并核验声明的源码，generated 空集合。它不建立已安装 SDK、account、宿主或服务。

使用公开 Python import API，在一个全新的测试私有包命名空间中，从该次物化的 `supervisor/src/agentcfg/__init__.py` 及其目录导入 `pi_host`；记录/断言新命名空间的自有模块都来自该次物化目录。共享 Python stdlib/已加载第三方库保留原测试环境，因此不是独立解释器或第三方完整闭包资格。不得替换导入失败为成功、利用已缓存的原 `agentcfg` 局部模块弥补缺文件，或调用 HostSupervisor 构造/业务方法。若发现该顶层路径使用绝对 `agentcfg` 导入而导致逃回 live 包，交 root 决策，不通过放宽测试消除。

测试临时设置 `sys.dont_write_bytecode`，结束后恢复，并在 finally 清理仅属于新私有包前缀的模块。不清空或替换 pytest 原 `agentcfg` 模块缓存，不改第三方 import 实现。实际文件字节/物化 root 的核验与仅 alias 名称分开记录；私有命名空间只检验本仓库顶层相对导入可用性，不推导真正 manager 进程启动资格。

同一个最终正控在加声明之前应因缺少物化的 `pi_lock_resolution` 实际失败，保存完整真实 red；加行后相同正控通过。另一个负控在物化和原校验之后删除该共享模块，再冷导入，要求真正 ModuleNotFoundError，并不能逃回 live 源。未选择的 delegate/Task Keeper/reviewer/installed Full origin/owner 服务模块不能因本次共享模块补齐被新导入。控制中使用临时 HOME/DSH/XDG/OS-account、假子进程和断网守卫，不启动 SDK、Node、Pi、Codex 或任何外部程序。

运行新 suite，另按实际 collection 运行受影响旧选择：`tests/test_pi_runtime_files.py::test_selected_sources_install_only_declared_transformed_bytes`、`tests/test_pi_runtime_files.py::test_invalid_file_selection_refused_without_stage_writes`、`tests/test_pi_lock_families.py::test_modern_generation_publishes_only_v2_candidate_with_exact_resource_owner`。不重复其它已接受套件。默认 wrapper 若出现祖先属主守卫错误，完整保留后在同离线边界正常属主执行，不改路径安全规则。

## 停止与后续

writer 自行实现、验真 red→green、最小旧回归、自审，再 STOP；实际 argv/退出码/XML/log/UID/时间/首末源码 pin、目录清理和声明逆去审计保存私有证据。root 针对停止后的稳定 diff 和新测试验收。若 import 揭示其它当前共享缺项，或测试必须执行宿主/扩大文件范围，交 root 重新判断。

本包默认通过只接受运行文件声明的局部修复。固定完整 modern manifest 尚未生产；npm 11.19.1 官方工具材料虽已取得，也未执行。实际候选解析、完整来源/许可、安装/backend/current、SDK/namespace/账号和产品 gate 各自验收；正式 7/100 与 strict 计量前 AUTO OFF 保持。

## 2026-10-07 稳定默认结果

两文件 STOP 后 root 验完整新测试、声明唯一行及实际原字节逆去、只读源 pin、XML/日志/collection/UID/首末 pin 和清理记录，106 输入 receipt `9b2e909b990057ee348155f03866d5945fce2bb5af909a87155afa2e607df2fb`。声明 38822B/bd0b05262187390764af92b858e380eddc6ae2e57b1e867d6612bb64ccb40857，Base 106 行；唯一共享行删除后整个原 38646B/00a972e10976877ddf46ef064055fd18bbfde36af750581db981c123fce6498f 字节和 JSON 均相等。新测试最终 4696B/1336ce940a2be8c162e4dc18ad9c741323d4e592cefeba31a5e8771baa11279e；生产 Python/TS/launcher 与旧测试未变。

同一初版正控加行前真实1fail，确为物化私有包缺 pi_lock_resolution 的 ModuleNotFoundError；加行后新2pass/0.81s。受影响旧三函数实际10nodes按1+8+1分三批全pass/零error/skip。最终审查发现 Full 排除名单含不对应实际文件的名字，将唯一常量改为13个当前真实 Full 模块，其余测试字节不变；只重跑两项新测试，另次2pass/0.70s，旧10项不重跑。两次新套件各有2个既有 xunit2 record_property warning，root 实际解析 XML 中29个私有模块的文件路径/hash；不把 warning 当缺证。

原 pytest agentcfg 缓存不被替换；私有前缀冷导入来自本次原 install_files/validate_files 物化目录，负控实际删除共享文件后仍失败。这里共享 stdlib/已加载第三方库，未构造 HostSupervisor，不签独立解释器、第三方完整闭包、SDK/宿主/native、完整动态闭包、Full/source/principal/hold 或产品资格。

封存脚本的三次真实 exit1 分别为 root 证据 pin 的 mode 字段比较、逆去块缩进、重复一致归档输入；对应实际脚本前像保留，均非产品或 pytest 失败。修正证据处理后脚本 exit0，没有因此重新运行测试；失败前未写结果文档或 state。

官方 npm 11.19.1 工具材料另13输入 receipt `b31b4f6226dcce8259e8bf91a8659d78e38af8de8e4782ce90bc086cf9414e57`：metadata 与 tar SHA1/SRI 一致，1943个常规文件/460目录/12223891B 内容逐项读回，LICENSE 原文保留；registry signatures 未独立验证。默认下载 DNS 失败和同开发边界正常网络重试成功分别保留。尚未执行 JS/Node/npm/resolver，不修改 nvm 的11.9.0或将版本要求降级。下一步仅独立临时源码副本中的原候选解析；正式 modern manifest、安装与所有产品 gates 尚未通过。正式7/100、严格计量前 AUTO OFF。
