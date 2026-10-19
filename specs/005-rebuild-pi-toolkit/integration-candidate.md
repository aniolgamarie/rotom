# Pi 集成审阅候选（2026-10-19）

本记录覆盖从当前 `main` 准备的本地审阅候选。原 `design/pi-toolkit-reboot` 工作树保留，
[本轮交付验收](current-delivery-acceptance.md)中的真实运行结果继续绑定其原源码和锁。
本候选的隔离检查、原生未执行范围及提交状态单独记录。

## 来源与重放范围

目标 `main` 为 `93e4f7899725336c1180e53b4ec239eea5f984ce`，原 reboot HEAD 为
`8ac50aaa8168b8a377c59736eaa1aebeb83a48c6`，共同祖先为
`5e1a042ec05afe99a80ade84f4aded06cd7c1a9a`。两侧分别有四个和一个线性提交。
分叉本身不证明历史是否经过公开清理；本轮选择从 `main` 重放已审阅内容，避免引入额外父历史。

新工作树分支为 `review/pi-toolkit-reboot-main`，HEAD 仍是上述目标 `main`。
未复制旧提交元数据。任务路径清单共 2369 项，八份旧设计草稿的退出已包含在其中：
152 项复制、2198 项删除、8 项在目标中原本不存在、11 项交集交由主代理处理。
机械阶段非交集逐字节和模式核对通过，89 项仅 `main` 变更的路径与目标 Git 对象一致。
后续按现行 Pi 契约适配其中的 cli_help 和两份交互测试，其余 86 项继续保持目标内容。

11 项交集包括六份文档、CLI/config/presentation/runtime 四个公共模块及模型默认值测试。
保留 `main` 的 DSH SSH、CLI 交互、身份与计划环境检查、部署待恢复和依赖锁提示；
同时保留 Pi 新 runtime/backend/lifecycle 接线、verification/feature_readiness 投影和旧执行链退役。
presentation 的七处冲突按上述边界处理；known-issues 的一处冲突保留两侧有效内容。

宪章临时 Sync Impact Report 已按治理要求移出提交内容，审阅副本保存在私人存储。
宪章条文、版本和原始批准日期待确认项未变。没有读取真实密钥、认证或会话数据。

当前生产输入为 318 文件，摘要为
`7e73dcee00f3d5a0b8f24825974dfa36a574137338970e817c0a8b2762202972`。
范围为 Git 可见且实际存在的 src、agents、shared、schemas、profiles 文件；按路径排序的
`[path,mode,sha256(body)]` 紧凑 JSON、`ensure_ascii=True` 再 SHA256。
相对原 305 文件新增 13 项 main 来源文件。默认 Pi 锁仍为
`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`。
下列完整回归期间测试输入保持不变，回归结束后生产摘要也与运行中记录一致。

## 整合修复

- 逐文件删除留下空目录，首次退役断言失败。确认 31 个明确退役根在原工作树均缺失，
  新树下没有任何文件或符号链接后，用 rmdir 清理 220 个空目录，删除正文 0；失败单验通过。
- main 新帮助及两份测试仍使用旧 Pi recover/project、from-starter、pi-default 和旧能力投影。
  帮助改用现行命令和 pi-base 示例，退役语法明确拒绝；未恢复旧执行接口。
  身份/恢复/锁优先级、无 I/O、payload 不变和敏感值不回显继续覆盖。
  12 项位置 ID 完整性改验仍有效的 service_checks；另验恢复期间保留六阶段 verification
  和三项 feature_readiness，Pro held/not_ready 与运行未验分列。
- 新上游 Apache LICENSE 使用 CRLF。保持原文 SHA256
  `9a7110fc2d2f964038e5dc49128f908f29f47a574c961cba16085914e879cbda`，
  仅在 .gitattributes 为此文件声明 `-text whitespace=cr-at-eol`，不改许可证正文。

## 检查进度

| 状态 | 检查或后续工作 |
| --- | --- |
| 已完成 | 非交集字节/模式、main 来源保留和 11 项交集处理；稳定代码审阅 0 发现；33 文件完整定向回归 890 passed、exit0；自有 Node observer 7/7、exit0 |
| 进行中 | 本地提交；最终暂存来源与后置检查保存于独立审阅材料 |
| 历史失败已修复 | 首次 346 passed/1 failed 为空目录；第二次 388 passed/1 failed 为退役能力测试接缝；随后单验、80 项接缝与完整 890 项均通过，原失败日志保留且不叠加计数 |
| 待必要决定 | 当前仓库本地 noreply 身份配置完整且作者/提交者一致；本会话缺明确公开身份批准，尚未提交 |
| 未执行 | 新重放摘要下的原生宿主、真实模型/工具、服务与性能复验；原工作树运行结果保留其原摘要，不作为本候选新通过 |

默认测试使用仓库与临时 HOME/XDG、假 provider/model、阻网与假进程，不启动第三方宿主。
默认沙箱的根目录属主映射不满足路径保护基线，定向回归在获准的外层执行器中保持原保护和隔离运行。
完整实际 argv、退出码、来源摘要与原始失败记录保存在私人存储，公开只报告脱敏结果。
完整定向回归包含 20 个 test_pi 文件，以及 agentcfg doctor identity/interaction、CLI environment、
home discovery、model defaults、paths、DSH optional/SSH/auto-review、deployment、runtime、
runtime preparation recovery、OMP runtime foundation 共 13 文件。参数使用
`-B -m pytest -q -rs --tb=short -x -p no:cacheprovider`，隔离临时目录及保留策略随实际 argv 记录；
pytest 报告 283.20 秒，执行器耗时 283.61 秒。测试清单摘要与运行前后正文一致。
写入后的公开内容检查覆盖 867 个当前文件，发现 0；31 份 feature/正式 Pi 文档的 186 个
本地链接有效，工作树 `git diff --check` 为 exit0。实际暂存树与最终后置结果由审阅材料绑定。

## 交付边界

任务仍为 87/96，T064–T071 和 T096 开放。Pro 继续社区路线并等待满足原约束的上游；
Brave/Cursor 真实账号验收按用户决定延后。新候选不改变这些决定，也不新增自有执行器或修改上游。
本地提交、合入、远端发布和完整 feature 归档各自保留其治理门禁。
