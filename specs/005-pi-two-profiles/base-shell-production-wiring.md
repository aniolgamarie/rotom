# Base Shell 默认生产组装接线

本包闭合仓库自有默认 `HostSupervisor → FileAdmissionControl → ShellOperationAdmissions` seam；不提升正式锁、SDK、实际 Base/Full、隔离可用性或产品验收状态。当前正式运行包/提供者资格及实际宿主模型 bash 执行仍分别待验证。

## 默认构造

现代 pi-base/pi-full 明确创建一个 `OperationAdmissions`，activation 来自当前 store owner 的 manager_activation_id，时钟来自原 operations.now，继续默认 4096 operations/32MiB 私有输入限制。File 与 Shell 借用同一原对象；保留原 control 对 ledger exact identity 的核验。原 operations.admission 仍是文件桥，不改接口。

只有当前 manifest.options.external_tools 明确拥有 shell 键时才导入/创建 Shell 桥，固定 binding_name=shell，借用 control 原 context_provider 和 shared admissions。未选 shell 保持 shell_bridge=None，legacy 构造不接新账本或桥；没有 AUTO/reviewer 分支。

## 私有后端预检

Host-bound `_shell_backend_preflight` 只收 resolution/physical 公开投影，不收脚本文本；非 Linux 固定 unavailable。

1. 原 host_namespace_binary 核所选运行包、原收据/descriptor/gate、平台及固定 bin/pi-bwrap；禁止 PATH/Codex/系统 helper 回退。
2. 原 Tree 以 16MiB 上限读取这个实际文件并核 0700。
3. 原 compile_mount_plan 编译完整公开计划，不运行 helper、mount、Shell 或子进程。
4. 再次原 namespace 校验并有界重读 helper，原 bytes/mode必须一致，不能用同路径新 helper 沿用旧 SHA。
5. 返回 runtime_root.name、实际 helper SHA256、完整 mount_plan 与原 digest。

任何收据/helper/平台/plan错误固定 SHELL_BACKEND_UNAVAILABLE，无原异常正文/链回显。返回值只绑定/重验，不授予执行权限；原 Shell `_compile` 仍做实际重编译、计划比较和 policy classification。Host resolve/spawn、ShellStart、消费、私有输入、锁/日志/unknown/recovery 顺序未修改。

## 默认证据与剩余

新增 focused 测试用实际默认 Host 构造、假进程、真实 Tree/原收据 validator 与合成未执行 ELF/helper bytes；这不是官方 helper 执行或完整已安装 Base 资格。planner 正控真正调用原函数，但只使用自有小树/synthetic mountinfo，不证明生产默认系统树。测试覆盖默认共享桥、未选/legacy冷门、完整计划、固定错误零spawn、规划期间 helper变化及默认 control prepare/consume→Host resolve 的 linux-shell ticket；后续实际 start由原既有 routing测试的明确替身验证，不启动 Shell/SDK。

原共享 identity/cap/private-byte 限制与最小 actual-Host/路由回归复用，guard不变。完整真实 exit/log/pins/diff/report 在 `.cache/pi-two-profiles/run-20261004/base-shell-production-wiring-review01/`。

正式锁与来源绑定、正式 runtime 的 helper/系统挂载树、SDK组合/模型工具实际加载、实际隔离/Shell/native验收仍未由本包证明。Root已发现独立 JS installed capability ID 与 plugin ID 的 Base组合差异，另包处理；本包不修改JS/maps/资格、不以预检或 ticket证明产品已可用。
