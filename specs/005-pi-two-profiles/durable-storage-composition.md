# Durable 公开 SQLite 组合的候选实现边界

状态：2026-10-06 root 决定，T082 的独立离线增量；未形成 Full 安装、服务所有者或 SDK/SQLite 运行通过证据。输入为已固定 `pi-durable@1.0.1` 发行包的公开 `./storage/sqlite` 和 `./storage/sqlite/node`。

## 接口与职责

在仓库自有 `agents/pi/packages/durable-service/src/storage.ts` 提供 `createDurableStorageInitializer({nodeSqlite, sqlite, path, options, verifyOwner, closeContext})`。输入为受信导入的 `nodeSqlite`/`sqlite` 公开模块、规范 Linux 绝对数据库文件路径、显式 Node 连接选项、受信 `verifyOwner` 回调及用于公开关闭接口的 Chord `closeContext`。返回惰性、单次 memoized 异步初始化函数，构造阶段不打开文件或数据库；相同函数重入共用同一次初始化，失败后不能靠再次调用它隐式重开。

固定发行声明的 `SqliteStorage.close(context)` 要求公开 Chord Context。`closeContext` 必须由未来服务组合提供，工厂只捕获同一非空对象引用，不创建虚假 Context、不检查其私有字段，不把默认测试的 opaque 替身当真实 Context 通过证据。storage 取得后，正常关闭及失败清理均调用其公开 `close(closeContext)`；facade 的公开无参 `close()` 只用于未取得 storage 的清理。返回的自有 `close()` 共用捕获的 Context。

`verifyOwner` 由未来服务 owner 实现，重新证明其仍持有同一所有权及部署/私有目录身份，必须返回 exact true。这里不创建 owner 锁、不把 caller 标签当权限、不实施服务恢复，不用 fake true 签 owner 通过。未来产品组合仍必须先取得 owner 并核对格式，再调用本工厂。数据库目录及恢复/迁移策略由该 owner 层拥有。

当前连接选项只接受 `busyTimeoutMs`（0 至 60000 的原生安全整数）和 `walAutoCheckpointPages`（0 至 2147483647 的原生安全整数），缺省明确固定为 5000 和 1000。未知字段、bool/NaN/Infinity、getter/proxy 或非数据对象失败。Node 组合使用公开 `node:util` 的 `types.isProxy`，在 descriptor/prototype 检查前拒绝 Proxy；这不是通用 JavaScript 的透明 Proxy 检测承诺。2026-10-06 固定 Node v24.14.0 已对自有合成值验证该接口，不据此认定其他 Node 版本通过。受信公开模块可以是 ESM namespace，facade/storage 的公开方法可来自类 prototype；只捕获允许的公开数据方法，不读取 accessor 或私有字段。路径须非根目录、词法规范、非空且有 UTF8 大小上限；不接受 `:memory:`、file URI、相对路径、NUL 或 `..`。合法中文路径保留。规范捕获在调用任何 owner/SDK 函数前完成。

## 调用顺序

1. 捕获选定的公开函数和私有参数；等待 `verifyOwner`，复核模块公开函数身份及参数绑定。
2. 仅调用 `openNodeSqliteDatabase(path, options)`，得到自有 facade；不调用便利 `openNodeSqliteStorage`，不访问其私有 DatabaseSync 字段。
3. 每个异步边界后重新核对当前 owner 和原公开函数身份；通过公开 `exec` 明确设置 WAL 和 FULL。
4. 用公开 `get` 读回 `PRAGMA journal_mode` 和 `PRAGMA synchronous`；要求明确 `wal` 与原生数字 2，缺失、错误或异常拒绝，不用设置语句成功代替读回。
5. 将同一 facade 交给公开 `SqliteStorage.open(db)`；它可能执行迁移，不把失败称为回滚。
6. 保留自有 facade 再次用公开 `get` 核验 WAL/FULL，防止后续初始化降低设置；最后再次核对 owner，才向未来服务返回 storage、固定设置观察及自有 close 门面。

公开模块函数的变更、owner 漂移、任何设置/读回/初始化失败均永久拒绝这一初始化函数。数据库 handle 已取得但 storage 未取得时，只清理自己得到的 facade；storage 已取得时，用其公开 close 清理，不触碰其他服务实例。close 只运行一次并返回同一 Promise。清理失败明确 `cleanup-unknown`，不声称数据库已关闭、迁移回滚、文件未创建或服务安全接管。数据库 opener 未返回 handle 时的错误保留 `open-unknown`，不能证明零文件副作用。SDK 异常原文、路径、SQL 参数或凭据不进入错误消息。

## 验证与未覆盖项

默认 Node 测试只运行自有模块与假公开 SDK/facade，不导入或启动 Pi Durable、node:sqlite、第三方宿主，不创建真实数据库、不读账号或调用模型。以可观察调用顺序验证惰性、并发单次打开、显式设置、两次 readback、漂移拒绝、私有字段不可访问、错误正文清理、失败后不重开及只清理本函数 handle。多组失败应断言具体未到达的后续调用，不只断言 throw。

通过这组测试只说明公开组合和本地控制流。真实 Node SQLite、WAL/FULL 返回值、fsync/进程退出、满盘/只读、owner 竞争、兼容迁移和断电边界仍需独立材料与对应授权；不以默认替身通过勾 T082 或开启 Full。
