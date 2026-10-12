# 私有 owner 回复窗口：单 frame 有界接收

2026-10-07，root 从已接受的 controller 算法提取可独立实现的接收窗口。固定资产／注册引用仍另行设计；本包不启动 child、不发布 owner、不申请 native，不把组件测试算作 T081／T090 或 Full 验收。

只写 `src/agentcfg/pi_durable_owner_channel.py` 和 `tests/test_pi_durable_owner_channel.py`。旧五消息 codec、record/store、controller 算法、runtime、所有 guard 和原生材料保持原字节。executor 不另行设计 fd、pidfd、锁、持久事务或异常恢复。

## API 与不变量

唯一公开类 `OwnerReplyWindow(expected)`。expected 必须是原 `OwnerMessage` 的合法 hello、bound 或 closed；先经原 encoder 全字段重验，再 decode 为独立自有冻结值，保存期望的 canonical frame。它只是期待的元数据，不能证明消息产生者、持锁、进程退出或 IO 完成。构造不调用 expected 上的外来 hooks；原 codec 的固定错误统一为本模块固定 Conflict `Durable所有者回复窗口无效`，实际 cause/context 均为空。

每个实例只有一次接收窗口，不 reopen、不自动创建下一窗口。`feed(chunk)` 只接受 exact bytes，类型核验先于 truth/len/切片；空 bytes 不用来表示 EOF，直接永久失败。最多保存 header4 + payload4096 bytes，允许用于识别同次已读尾部的额外1字节，但不保存超限内容。原始 chunk 或累计长度超过4101时在复制／解码前失败。header 未满4时只保存片段；header 完整后长度必须1..4096；累计字节超过声明的 frame 长度立即失败，不截取前一个 frame、忽略尾部或把尾部留给下一窗口。完整 frame 用原 codec 解码并重新 canonical encode，全文等于 captured expected 才保存唯一候选；`feed` 返回 None，不向调用方提交候选。

已保存完整候选后再收到任何非空 chunk 永久失败，即使内容像下一合法消息。不宣称能观察尚在 kernel pipe 或未来才写入的字节；实际 controller 必须继续管理原 pipe、逻辑窗口、发送和全源核验，不能用 `feed` 当前未见尾部证明 producer 静止。

`take()` 只在完整匹配候选且未失效／消费时返回一次独立 `OwnerMessage`，随后永久 consumed；过早或第二次 take 永久失败。返回仍为无权限元数据。实际 controller 只在原 send/flush 全回执和随后全源核验完成后调用 take；本纯组件不接收或签发 send 成功 boolean、任何 wait／fsync／持锁 capability，也不检查外部 lifecycle 顺序。

`end()` 表示调用方在本次读取观察到 EOF。不完整时失败；有完整未消费候选时只记录观察，候选仍可 take；消费后允许一次 end，绝不重新打开。第二次 end 或 end 后 feed/take 已消费候选按上述失败规则。EOF 不代实际 waitid／producer join／held锁检查。`close()` 可在任何状态永久停止并丢弃候选，幂等、不运行清理 IO；关闭后 feed/take/end 均失败。只读 `has_complete_frame` 在合法完整未消费时为 True，其余 False；`writer_lock_verified`、`database_allowed`、`can_take_over` 恒 False。

实例采用 slots，不提供 public 可写状态或外露可变 buffer/candidate；上述四个 public properties 无 setter，禁止赋值或遮蔽。内部状态只保存在自有私有 slots，不承诺防护调用方任意 Python 私有访问或 object.__setattr__ 反射；本类本来就不签发 capability。普通构造／操作不调用外来 callback/producer，不提供配置项。

任何校验／来源异常永久 invalid，丢弃私有 buffer/candidate；异常文本仅固定错误，清除新造自有错误的实际 context/cause，不修改外来异常对象。模块首次正常 import 时保存有限原来源表：message 模块的 OwnerMessage、OwnerRecord、LinuxProcessIdentity、StorageIdentity、capture_owner_message、decode_owner_message_frame、encode_owner_message_frame、capture_owner_record、encode_owner_record；record 模块的 OwnerRecord、LinuxProcessIdentity、StorageIdentity、capture_owner_record、encode_owner_record。所有 class 别名必须是保存的同一原 class；调用只经保存的原 encode/decode 函数。只核上述出口及别名，不承诺捕获任意私有 helper 或全局 builtins 修改，也不检查外部 stdout／SDK producer。

构造、feed/take/end 在接触外来内容前及每次原 codec 返回后核上述表；漂移立即 invalid／抛固定错误，禁止调用替换后的函数。`has_complete_frame` 在未 close/invalid 时也核表，漂移则 invalidate并返回False，不抛异常；已 close/invalid/consumed 返回False。`close()` 与三个恒False getters不调用 source/codec，仅自有停止动作或返回False，使永久失败后的幂等停止／能力否定仍可观察。不 freeze 或改写外来输入／模块／class／原函数。

## 默认证据

固定命令为 `/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -m pytest -q tests/test_pi_durable_owner_channel.py tests/test_pi_durable_owner_message.py`。使用原 conftest 临时 HOME、断网及 subprocess guard；新测试不 import/调用 Node、SDK、SQL、真实 socket/pipe、proc、signals、locks或第三方宿主，不移除 guard。

必须先保存缺失实现的原状态和新测试首轮真实结果；缺失 import／环境失败仅记录为未实现，不能充当行为 red。实现后若需要同 final 测试与旧基线对比，独立可控 fixture 只模拟原 frame 拆片／返回值，不复制整个算法当 oracle。验证一字节片段、header/payload 每个切点、不同合法编码得到相同完整元数据、三种合法回复、上下文／epoch／record／writer／lock 不匹配、乱序帧、同 chunk 多帧／尾部、后到帧、EOF、重复消费／永久失败／幂等 close、exact 类型 hook 零次、上限先于 codec、captured 期望不受调用方后续改变、原 codec 漂移不调用替换函数。旧 codec 套件单列计数，不能将两组件通过报告为实际 pipe 或 controller 通过。

稳定写入后 root 和独立 executor 审查 diff、完整新 source／test、guard及旧依赖 pins；有问题同范围修复后复审，无新证据不重跑全仓。
