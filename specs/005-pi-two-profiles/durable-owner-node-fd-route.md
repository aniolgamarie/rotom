# Node 原控制 fd 的候选启动路线

这是 root 根据固定 Node v24.14.0 官方资料提出的下一阶段候选，不是已冻结的进程生命周期接口或实际持锁资格。原 owner 记录范围先独立完成默认验收；Node 启动、原 writer 绑定、closing/released、SDK 开库和恢复接管仍须分别实现、复审与实际验证。

## 已核官方事实

Node [fs.fstatSync](https://nodejs.org/download/release/v24.14.0/docs/api/fs.html#fsfstatsyncfd-options) 可以只观察 fd，不隐式关闭；使用 bigint 避免 device/inode 的 Number 精度截断。默认 stream 会 autoClose，不应用来包装原控制锁 fd。fstat 的相同元数据不证明同一个 open-file-description，也不证明 flock 仍在。

[spawn 的 stdio 配置](https://nodejs.org/download/release/v24.14.0/docs/api/child_process.html#optionsstdio) 描述显式 stdio 的传递，不能据此证明所有从 Python 进入 Node 的额外原 fd 都设为 CLOEXEC。[Node 同 tag 初始化](https://github.com/nodejs/node/blob/v24.14.0/src/node.cc#L780-L784)通常调用继承标志设置；[同 tag libuv 实现](https://github.com/nodejs/node/blob/v24.14.0/deps/uv/src/unix/core.c#L753-L761)无条件尝试 0–15，之后遇第一个失败停止。因此高号原 fd 与中间空洞不能依靠默认行为签发“后代零继承”。这是从官方源码作的条件推论，目前未观察实际泄漏，也未核已安装二进制等同该 tag。

## 候选约束

专用 Python 监督进程启动时，在任何并发/路径/SQLite/SDK活动前拥有一个预留低号 fd 槽位（候选为 3）。若该槽位已经被未知对象占用，直接失败，不覆盖或关闭未知 fd；不能在普通 Pi 主进程或多线程进程中盲目 dup2。正常 stdio/私有控制通道也必须固定，不能从客户端传入任意 fd 数值。

排他取得物理存储原 EX 锁后，专用监督者在自己原预留槽上 dup 同一个原 open-file-description，保留原父持锁 fd；启动固定未改动的 Node CLI/自有 bootstrap，pass_fds 只允许这份原低号描述符与经过明确设计的私有通道。启动脚本、Node 二进制、参数和环境需要固定/核验，不依赖插件自行选择 Runtime 或 loader；Node startup 可绕过标志设置的嵌入模式不纳入候选。

Node 自有 bootstrap 对控制 fd 只作原 fstatSync(bigint) 与显式必要的本机 fd 标志检查，不交给 fs stream、SDK、backend、tools 或模型返回数据。只有实测原低号 fd 在 entry 仍存活且实际 CLOEXEC/后代不保留，才可能纳入正式路线。一般 fd/inode/JSON 检查不签权限；只能在受信专用控制面完成同一持有链的资格后继续评估原 writer 身份与私有握手。

本候选不扩展现有 `OwnerRecordScope` 的公开接口，也不从其冻结 record 取 fd。跨进程能力和生命期必须由 root 另冻结自有控制器的私有接口；不能把当前无 Node 的 finally/close-only 范围直接套在活 Node 外面。原父异常退出、writer 仍活、启动回执丢失及 fd 资格不足仍保持 unknown，不自动重启、换 epoch或补写 released。

## 未来具体运行材料应验证

在私有临时目录、断网、自有 Python/Node脚本、零 SDK/数据库/模型/账号下，固定原 EX 锁、original-fd→dup→pass_fds 链；竞争者必须打开同一个原锁路径，不允许换锁文件制造测试通过。父/Node 同时持有、Node 退出父仍活、父正常或 SIGKILL退出而 Node仍活、最后句柄关闭等切点分别观察 EX/NB竞争结果与原进程身份。SIGKILL 不冒充断电，进程 poll/stdio EOF不冒充完整物理退出。

后代检查不能仅问“fd3是否存在”，因为 Node可能把关闭后的编号用于其他内部资源；要查是否仍有原锁物理身份对应的 fd，以及其实际继承路径。任何高号/gap负例、低号正例、close/exit/丢ack/未知路径都以实际 raw日志和固定材料记录，未运行不得记 PASS。此试验即使通过也只签固定自有启动路线的 fd 基础，不替代完整 owner/SDK/恢复/Full验收。真实独立进程材料需另审查并取得该范围的明确授权，已有 admission SDK7授权已闭合。
