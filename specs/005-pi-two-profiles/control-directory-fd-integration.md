# 控制目录 FD 与真实宿主命名空间

2026-10-11，补齐真实宿主测试发现的控制通道缺口；不调整用户既定权限/预算边界。

实际 Base CLI 首次 get_state 前 exit4/0model/0Writer。原 Host 租约均有 verified 回收。通过原 manager 的固定 pi-bwrap、PID1/原根挂载形状执行只读 metadata probe：child uid/euid1002，/及/tmp属主65534，私有项目属主1002；原 Tree 私有路径打开以“路径祖先不属于可信用户”拒绝。故障来自 unprivileged user namespace 对系统属主的投影，旧外层空根场景未覆盖实际 root-owned /。四次原失败和固定阶段诊断记录均保留于 `.cache/pi-two-profiles/run-20261004/base-daily-native-product-review01/`。

实现采用原控制器已验证、固定住 inode 的私有控制目录句柄。全局 paths/storage 私有祖先检查不修改，不接受 overflow UID，不因无法解释真实属主而允许路径式访问。无 FD 的原 client 保持严格路径打开。

原 SupervisorServer 用 Tree 校验真实控制目录后保持独立 dup；它只向已分配且经过原出生身份/UID/namespace/grant 门控的现代 manager 与必要 worker 交付。优先复用原 host-gate，通过 SCM_RIGHTS 在原 G 放行交付恰一个目录描述符；不使用父多线程 preexec_fn、不覆盖父进程 FD3、不开放任意 FD 转发。子侧须拒绝空/多余/truncated ancillary、非目录、错误属主或非0700。先完成并关闭 gate socket，再在此子进程内映射目录为 FD3，保留到 Node exec。若某 worker 使用不同原 gate，须在同一授权时序交付，不能自建来源 issuer 或伪造安装资格。

Node 的自有 SupervisorClient 仅接可信 Host 启动上下文中的控制目录 FD，捕获 dev/ino/uid/mode 并在调用前重验，拒绝已关闭/复用的 FD。每个 Python client 的 stdio 显式将此句柄映射为其 FD3，环境只传固定 FD 编号。正文、模型参数或公共工具不能选择另一个目录或传入任意 FD。

Python pi-control 的可选 inherited_directory_fd 仅用于控制目录只读访问：固定 control.json、普通单链接文件、0600、同 UID、有限内容及前后文件身份检查；从已固定的目录 FD 作 no-follow 相对打开，不再沿不可信投影的/重走路径。禁止创建、写入或任意相对目标；复用原私有文件读取语义。原 socket inode/UID、peer UID、capability、owner、lease、generation 和生命周期授权一律保留。目录 FD 固定读位置，不能授予操作许可、延续旧 generation 或扩展 PreparedOperation 的范围。

父持有句柄、子接收句柄、每次调用 duplicate 都须清楚关闭；未证实终止仍保护执行/Writer，FD存在不是进程终止证明。源 API/声明与正常生成闭包需同步，SDK/agent 上游/二进制不修改。

验收分层：默认正反验证完整 handoff、错 FD/owner/mode/inode/extra/late cancel 与关闭；原命名空间正控制须证明路径打开仍拒绝而被交付 FD 可以读取同一原控制端点并完成握手；真实私有 CLI/原 Host/SDK 再执行普通工具和GCC/Shell/Neovim，只有实际输出/原收据/回收事实才计通过。此前全为合成 Provider；真实账号、真实模型质量、最新全组合和整进程恶意扩展能力继续另验。

已核对的MCP边界：当前 ordinary stdio MCP 在 `pi_commands.py` 返回默认 process_scope 的 SpawnCommand，原Host经generic `pi-exec.py`启动；`pi-project-check`的输入Tree读取发生在父侧路径视图，随后才exec业务隔离器。本轮根属主投影问题不适用于这个输入读取，不扩大control reader到任意文件，也不增加输入FD交付。未来若新调用者在PID namespace内复用该脚本，必须另做输入来源/句柄资格设计；不能沿用本次结论。
