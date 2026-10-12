# owner launch 的部署来源与固定资产

2026-10-07，root 根据限定静态证据决定固定资产路线。本文冻结来源和角色映射的设计，不授权生成正式锁、下载／运行 Node、部署、修改上游或实现 controller lifecycle。尚待独立审查；实际 resolver 文件包、私有启动材料传递与原生资格另行冻结。

## 已观察的接口

已归档三组 scout（gpt-6-luna/high）证据：`durable-owner-controller-assets-static-review01` 的5源、`...assets-static-followup-review01` 的2源、`...registration-static-review01` 的4源。`PiBackend.read_lock` 产生核验过的 PiLock 和原 package/lock bytes，`runtime_identity`／`root`／`status` 提供已选择运行包身份与完整 sealed tree。runtime_files 另锁仓库自有源和转换后字节，但它们没有现成的 Node 可执行角色对象。资产安装允许通用 bin target；现有启动链仍用命令名 node。这个发现只覆盖所读模块，不等于全仓不存在其他接口。

可信 manager 当前从 Workspace 的已解析 binding 和 `deployment.json.current.launch` 选择 runtime，再验证运行包和 Pi manifest。新路径复用该来源；不将收到的 hash、同 UID、PID／PPID、任意路径或调用方构造的 dataclass 当作授权。已经部署的实例／当前选择／包安装通过与 owner 独立请求授权仍是不同检查。普通 Pi／Base 启动不读取可选 Durable 资产、不创建 Durable 目录或进程。

## 固定 Node 路线

选择在正式锁内声明独立原版 Node executable 资产，固定相对 target `bin/pi-node`；不在 owner 启动时解析 PATH、shutil.which、shell或系统 fallback，也不把 `node --version` 的文本当原 binary 身份。依赖安装使用已有 asset/archive／平台校验与完整运行包 inventory；另明确 Node 角色、精确 toolchain 版本、归档来源和摘要、解出的原 binary 摘要、许可与通知来源。需要通过官方发行材料核实并固定这些真实值后才加入 recipe／lock；不能从当前临时 probe 的本机 Node 猜一个正式 provenance，不能复制未知许可或捏造声明。当前不新增未核实 source row，也不生成正式 manifest。

owner 固定选择该 runtime 下的 `bin/pi-node` 绝对路径。它是已验证登记引用解析的结果，不是 client 字段。原目录／文件对象、完整物理身份、摘要和 source producer 由专用 controller 捕获并逐启动窗口复核；Node 与 bootstrap 还必须包含在同一 sealed runtime 的完整 inventory 中，不能接受“任意路径＋调用方 supplied hash”。首版选择 path exec，不使用 `/proc/self/fd/N`，因为 accepted 算法规定 Node 的 pass_fds 只含原3；不为 fd-exec 临时加隐式高号继承或修改上游 Node。path/hash/fstat 的复核不是 kernel atomic exec／同 UID 恶意改写阻断保证，外部改写使证据 stale；用户、未受管进程和拥有任意同 UID 文件修改能力的外部环境不受受管锁约束。若后续威胁模型要求 kernel 固定 exec 原对象，需要重新设计 helper／继承和 qualification，不能宣称当前路径已经做到。

正式资产启用前，候选实际 Node／公共库只用于已经明确授权的隔离探针。factory 对 candidate selection、缺许可、缺角色资产、未固定 version/binary provenance、无当前 installed receipt或相关资格未验证都 fail closed；没有自动退回已部署 legacy 包的 owner 入口。

## 自有代码角色

正式 Full slice 需声明且仅声明以下 owner 固定角色，不通过同名插件市场内容替换：

- `owner_node` → `bin/pi-node` 的已锁原版资产。
- `owner_bootstrap` → `runtime/durable-owner-bootstrap.mjs`，来源为仓库新增 `agents/pi/runtime/durable-owner-bootstrap.ts`，仅 builtin 和下面纯 codec；零 SDK／DB／后代。
- `owner_codec` → `runtime/durable-owner-message.mjs`，来源为已接受 `agents/pi/packages/durable-service/src/owner-message.ts`，不复制实现／产生第二套 schema。
- `owner_controller` → `supervisor/scripts/pi-durable-owner-controller.py` 及其声明的自有 Python source 闭包；包中固定已接受 record/store/message/channel 和所需路径、Tree、LinuxProcesses 依赖。不动态扫描扩大集合。

现有 runtime_files 的来源白名单不能安装 packages 下的 codec：未来只为上面的确切 source→target→transform 映射增加一个分支，保持现有 unknown/source/path/transform 失败规则。不开放任意 packages 或任意目标，也不修改当前 codec 字节。controller/script 与 runtime bootstrap 采用已有自有源规则。以上文件全部纳入相同完整 slice／runtime identity；替换插件提供者后重新生成身份并使相关 qualification stale，不在活动任务上热换。

角色不是任意 recipe 回调。拟在 Full slice 增加闭合 `durable_owner` 声明（schema1、上述固定角色、依赖清单和 protocol1）；锁生成、schema、source核验、sealed package核验、resolver都复核固定映射。Base slice 不声明此组角色；若未来共享 Node 资产，Base 只显式安装 Node 角色，不因此拥有 owner/bootstrap/SDK 能力。尚不把 schema草案写成已支持的配置字段。

## 稳定存储注册

服务存储根不能用 runtime/deployment digest 创建一个新的空数据库来绕过旧任务／未知预留。可信 manager 从固定 Full 实例与其 state_root 派生唯一 `<state_root>/durable/storage`，持久登记 service id、原 binding／实例、目录身份和首次部署兼容信息；service id 的生命周期独立于 runtime。客户端只引用该 service id，不提供 root／SQLite路径／epoch／Node路径。目录首次创建仍只在专用 controller 预留原 fd3且完成登记／部署检查之后；manager 的只读解析不提前打开数据库或创建 owner。

首次创建与已有登记是两条路线：缺首次创建完整授权／当前原 manager 来源即拒绝；目录已存在（包含空目录／缺记录）不能走 fresh path。重部署、profile 或 provider 更换不删除登记、自动换 service id、清空累计预算或重写 owner epoch。新 deployment 不兼容既有 storage 先停止准入并保留原对象；原 runtime和迁移／恢复引用保留，恢复／已授权迁移另行验证。登记不是“旧 PID 不在”的接管资格，首次包只支持全新排他目录。

上面是 manager 的可信内部接口目标，不新增面向 client 的任意 launch 参数。root 在实现 resolver 前还须冻结：实际 registered reference 的原对象和 validator、原 current.launch／receipt 的完整关联字段及写／读身份、manager 到专用入口的私有初始化传递（不能占用未知 fd3）、版本／源 drift 的关闭动作和授权独立来源。executor 不用 public hash/capability boolean 补齐这些空白。此处尚未授权 resolver／controller lifecycle 的代码包。

## 分层验收

纯回复窗口可先独立完成，因为它不选择资产／路径、不启动或清理 IO。固定 source角色与完整包 resolver 的默认验证使用临时 Tree、假 Node asset bytes／完整 fake sealed receipt、原 fake manager producer及虚构身份，证明不读 secret、无 PATH fallback、未选择零可选读取、外来字段拒绝、旧登记不 reset；fixture不冒充正式可运行 Node或上游许可。正式Node来源闭合之后准备单独的真实版本／exe／CLOEXEC／pidfd／私有pipe／锁竞争资格，所有实际宿主／native仍按 AGENTS.md:42 单独取得授权。

本设计没有运行任何新二进制、写入正式依赖锁／用户配置或部署；Full/owner/database 三项 gate 继续关闭，T079／T080／T081／T090 未完成。
