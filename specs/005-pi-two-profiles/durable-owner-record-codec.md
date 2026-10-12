# Linux owner 记录的首个编码接口

这是[原锁持有链](durable-owner-custody.md)的有界基础组件。只捕获/编解码非秘密元数据，不取得锁、不生成epoch、不读/proc、不写文件、不启动进程或SDK。可重构记录永远不是所有者授权；后续原锁下的记录操作和Node持有链分别实现/验收。

Python自有模块`src/agentcfg/pi_durable_owner_record.py`新增三个函数：`capture_owner_record(value)`、`decode_owner_record(data)`、`encode_owner_record(record)`。捕获/解码返回自有冻结slots dataclass；编码只接受这些精确原class的结构值，重新验证全部字段。拒dict/class子类、mapping、自定义可执行对象和非法JSON值，不从异常输出原字段名、文本或值。所有非法输入统一抛自有`Conflict("Durable所有者记录无效")`且不携带原异常。

记录schema1恰七字段：`schema, deployment_identity, storage_identity, epoch, controller, writer, stage`。schema是精确int1；deployment_identity与epoch是64个小写十六进制字符，不据其字符串授予权力。storage_identity恰`device,inode`，精确int，device为0..2^64−1、inode为1..2^64−1，bool/float拒绝。epoch在此只读既有值；真正新epoch以后由原控制面随机生成，客户端不得通过此codec提供owner配置。

controller/writer使用同一精确闭合Linux元数据结构，恰`platform,boot_id,pid,ppid,pgid,start_time,namespace,uid`：platform为linux；boot_id为小写8-4-4-4-12十六进制UUID，不推导boot退出；pid/pgid精确int1..2^31−1，ppid精确int0..2^31−1；uid精确int0..2^32−2；start_time为0或无前导零的十进制字符串，数值0..2^64−1；namespace为`pid:[N]`，N无前导零且1..2^64−1。不得将字符串数值自动转换为数值字段或规范化非法值。若writer存在，原controller/writer PID不同、boot_id与uid相同；namespace可不同，PPID/PGID关系不作活性或父子证明。

stage恰acquired/bound/ready/closing/released。acquired必须writer=null；bound/ready必须有writer；closing/released允许null或完整writer。ready/released在本组件只是一种合法记录形状，不证明真正持锁、可开库或已经退出。OwnerRecord上的`writer_lock_verified`、`database_allowed`、`can_take_over`只读属性永久False，不在持久七字段中编码，也不接受为输入字段。

decode只接受精确bytes，最多16384字节；严格UTF-8与JSON、所有层重复键拒绝，不允许NaN/Infinity或解析失败回退。未知字段、缺字段、错误类型、超界或阶段/进程关系矛盾均固定失败。encode返回确定性UTF-8 JSON（sort_keys、无多余空格、尾换行），再次核完整结构/长度；capture不修改或冻结调用方原dict，返回值不保留其可变引用。parser与编码不调用原对象getter、__iter__、__str__或自定义JSON hook。

默认测试只用原Python值与合成Linux身份，不运行锁、/proc、子进程、SDK或模型。覆盖所有合法阶段、完整capture→encode→decode、源变更不污染输出、冻结/准确class、闭合字段、bool/float/整数边界、namespace/starttime/boot/epoch形式、阶段writer关系、重复JSON键、UTF-8/容量/深度失败、伪可执行对象零调用以及异常隐私。新功能缺实现导入失败不冒称行为红；写完稳定后root与独立executor验收。仅此codec通过不勾T081/T090或单写owner/Node/Harness产品资格。
