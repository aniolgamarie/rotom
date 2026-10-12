# Base 已安装资源清单的离线诊断接线

2026-10-09 root，T011 的第一生产子包。已接受 `base-resource-diagnostics-next-boundary-evidence-review01`：doctor projection 没有实例/运行包位置，modern profile plan 只记录选择；历史 loaded-manifest 仅来自旧 launch，不能当作现代实际加载证据。本包只核对现代已安装描述，不读历史加载文件，也不新增宿主调用。

## 接口与身份

自有 doctor 为现代 Pi 添加可选的 `installed_resource_context`，仅从已经校验的 Workspace、当前 lock/profile slice、backend runtime_identity/root 产生。字段为实际 profile_id、runtime_root、lock_identity、runtime_identity、slice_identity、expected_resources（原 lock slice resource_manifest）。不得从用户 options、模型或第三方 extension 接收路径。其他 agent、旧 Pi 和缺失此上下文的旧调用保持原行为。

`pi_diagnostics` 将该上下文传给新的自有 `pi_installed_resource_diagnostics.py`。仅当 dependencies 为 installed 时读取固定 `runtime/profile.json`，使用既有 Tree 的安全只读能力，单文件128KiB上限，不遍历运行包/HOME、不执行资源。总资源条目最多4096、ID与非秘密输出总UTF8字节65536；重复 key、非有限JSON、未知字段/类型、重复资源ID、路径穿越/绝对路径/链接、错误 profile/runtime/lock/slice/engine 和资源字段不符均拒绝，不吞掉字段修复输入。

描述结构沿用 `pi_modern_launcher.validate_profile` 的现代 schema v2 15个字段；资源 kinds 与 lock 的 RESOURCE_KINDS 一致。比较完整原资源清单及四项身份，不重新计算/伪造accepted context，不读取凭据或其内容摘要。出现读取中漂移、旧身份或验证不明，返回固定 code 的 invalid/stale 等状态，不能使用失败读出的部分数据。

输出加入现代 host 的 profile_plan 下 `installed_resource_inventory`：明确 status（not-inspected/missing/invalid/stale/matched）、固定 reason code、经过验证的公开 resource kind/id/capability_id 和有限计数，不输出文件路径、原描述、异常或文件正文。status matched 仅表示保存的安装描述与当前 lock/context 相符；不是 actual loader、账号、SourceHold、并发锁或权限隔离证据。现有 load/execution evidence、discovery 各 observed 与 permission isolation 都不得升级。

## 写范围与验证

唯一代码写入者拥有 `src/agentcfg/commands.py` 的 doctor projection 小段、`src/agentcfg/pi_diagnostics.py` 的现代 profile plan 接线，以及新 helper `src/agentcfg/pi_installed_resource_diagnostics.py`。测试拥有新 `tests/test_pi_installed_resource_diagnostics.py`，必要已有 `test_pi_modern_diagnostics.py` 小量接线回归；不改锁/catalog/provider/host/其他agent代码。模块只在 modern+selected host 路径延迟导入，Base不引入Full依赖。

先保存源前像和有意义的假描述 red，再实现，固定默认 pytest 只运行新模块及已有 modern diagnostics/doctor 的最少受影响用例。全部使用临时HOME、假provider/model、断网和禁止真实子进程；测试证明匹配、错身份/资源、未知字段、超限/重复/nonfinite、缺失/链接、dependencies未安装零读取、无上下文保持not-run、完整doctor实际投影路径、跨profile和未选Full零探测。不得读实际账号、加载SDK/资源或启动宿主。

不要引入新锁/事务/恢复协议。原 Tree 或 producer 缺失无法满足安全读取、需要扩大源写范围、同一有效失败两种修复仍未解时升级 root。完成后停止写入，提交稳定diff/证据供独立复核。正式8/100、产品未通过、Pi AUTO OFF，OMP已交由他人负责。
