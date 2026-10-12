# Base 原生状态目录的默认边界验证

2026-10-09 root 实现子包，T012。依据 `base-native-home-producer-increment-evidence-review01`：主路径已由 Workspace/PiAdapter/官方 launcher 定义，不能因先前有限模块检索未见 producer 而重建一套状态系统。默认本包只测试现有生产路径，源码与锁不修改，不启动 SDK/宿主。

唯一新测试写入者可新增 `tests/test_pi_modern_native_state_boundaries.py`，使用现有实际 resolved profile、Workspace 派生路径、PiAdapter.native targets/prepare_runtime/launch spec 及 `test_pi_capability_manifest.py` 的合成 lock/fake installer。报告和即时记录独立存放，不复制/修改旧业务测试或加入隐式 Full 能力到 Base。

2026-10-09 前提纠正：当前公共 catalog/profile/defaults 实际只有 pi-base，尚无实际 pi-full 声明；既有 modern launch 测试中的 Full 是明确合成的 Base 派生 fixture。因此下面双 profile 形状测试改为实际 Base 加明确标注的 synthetic pi-full sibling，复用现有假 Full helper，不改公共声明来让测试通过。实际 Full 缺失单列环境/实现不足，不能记成 R03/Full 已通过；初轮因缺 Full 而在 fixture 初始化失败保留为前提不足，未到达行为断言。

验证四个具体边界：

- 在同一临时 machine/config/instance/state 总根下创建实际 Base 与明确合成的 pi-full sibling workspaces，两个 instance 和 state_root 均不同；各自 launch 的 HOME、PI_CODING_AGENT_DIR、sessions 路径按其自身 profile 绑定，没有第二套临时主 HOME。Base 只读公开 profile，Full 仅测试派生算法/未来契约形状，不证明实际 Full 组合；provider/model 按现有 fixture 假化，不读实际 local config。
- 在两实例创建 0700 native home/session 目录及 0600 合成 auth/session 哨兵。调用真实自有 prepare_runtime 时不覆盖内容、权限或原路径身份；两 profile 的写入不能改变另一组哨兵。auth/session 属于 runtime-owned，不能成为配置生成器的 owned target 或来源摘要。假哨兵不是凭据，禁止做账号/token/APIkey 内容或摘要测试。
- 对合成 Base current 锁使用现有 fake installer 的正常包修复/重装路径，确认仅内容寻址 runtime package 改变/恢复，Base 原生 auth/session 和 Full sibling 哨兵均不变。此项不安装真实 Full、不启动宿主、不证明真实账号的恢复兼容；source/recipe 过期时仍拒绝，不能修复声明绕过当前锁。
- 用现有 normal runtime fixture覆盖确切 pending/activity 写前拒绝条件，并断言 fake launch/installer 未调用、哨兵未改。若接口只能证明已有 pending 拒绝而不能直接构造活动租约，就明确未覆盖活动 OS 层，不用 mock 锁通过冒充实际竞争；原独立进程 T014 等证据不重跑。

使用临时 HOME/XDG、虚构 provider/model、阻网、fake subprocess；绝不执行上游、真实 npm/shell/模型，不修改实际 instances 或账号。验收只运行新模块及新测试涉及的最少现有 helper 回归；通过后不扩大重跑。数据文件只在 repo/临时 HOME，必要真实 owner 视图用固定默认 pytest 命令的自动工具审查，不降路径/权限保护。

先保存实际初次失败与受影响 green；若仅增加对正确现有行为的覆盖，忠实记录首次直接通过，不制造 fake red。新生产缺陷、事务/锁/恢复顺序不明、需要扩大源码写范围或两次有效修复仍失败，交 root 判断。写完停止，稳定 diff/pins 与结果再独立复核；T012/真实状态与产品不据此直接完成，正式8/100、Pi AUTO OFF。
