# Pi 配置与依赖管线：隔离验证

本页记录 US2 的 mock 范围；不作为 Pi 原生加载、Task Keeper 生命周期或账号调用通过证据。

## 已实现范围

- PiAdapter 注册及四个显式 profile；模型、认证 owner、角色、资源、引擎与参数预检。
- `$ENV` 原生凭据引用，五类所有权；规则、APPEND_SYSTEM、初始化快捷键、完整技能与精确模型角色生成。
- 独立 PiLock、每配方完整 npm 文件对、source/slice/platform/toolchain 组合运行身份。
- 确定性本地 vendor 归档，源码/执行位/许可记录；显式锁解析、frozen 安装、内容收据与原子修复。
- 封闭 SDK loader，factory 前选择、禁止原生包安装/更新、显式项目资源、受管角色覆盖冲突。
- bootstrap 允许登录界面，拒绝任务与未绑定模型请求；项目设置不参与自动发现。
- run 使用保存的 runtime_identity，运行前拒绝凭据字面漂移、损坏运行包与不匹配的精确工具链。

## 测试方法

Python 测试只使用仓库和临时目录、假安装器、假宿主、虚构 provider/model。
`tests/test_pi_pipeline.py` 在普通路径及含中文空格的另一组路径执行真实 CLI/adapter/backend：
validate → render → plan → sync → apply → 再次 apply → run（假进程）。
重复 apply 检查 `changes=0`；验证缺凭据、缺必要入口、错误 agent、保护参数及凭据漂移拒绝。

Node mock runner 以 permission 模式隔离文件访问，阻断网络、子进程和发信号：

```sh
node scripts/test-pi-mock.mjs tests/fixtures/pi/mock-boundaries.test.mjs agents/pi/runtime/tests/resource-loader.test.ts agents/pi/runtime/tests/launch.test.ts
.venv/bin/python -m pytest -q -p no:cacheprovider
```

Node 的源码测试使用当前测试工具链 24.1.0，不把它算作目标 Node 24.14.0 的 native 通过。
安装测试精确版本输出由显式替身提供；不下载包、不运行 npm 生命周期、不导入实际 Pi SDK。

## 本轮结果（2026-09-16）

- 全量 Python：887 passed，7 subtests passed，52.90 秒。
- 收尾的来源缺失/角色绑定/资源验证：24 passed，1.68 秒。
- Node mock：12 passed；网络、进程、未知 factory、bootstrap、CLI、项目角色编译均覆盖。
- `git diff --check` 通过。未执行原生宿主、真实安装或账号调用。

新增 preflight/argv 钩子为可选，未提供钩子的旧适配器继续使用旧契约。
按 schema 内容缓存结构检查；本地引用目标和修改后的 schema 仍全量验证。

## 发布限制

当前真实配方尚缺后续任务迁入和改造的 Task Keeper、model-delegate 及管理者 vendor。
真实依赖锁必须等这些源码收敛后统一生成；fixture 锁只存在于测试临时目录，不进入 `locks/pi`。
真实源码未就绪时拒绝锁构建，不删除必需能力、不回退旧包、不借用全局 node_modules。

角色通过新的显式清单交给后续管理者桥接。`loaded_manifest` 只表示加载，不能证明任务成功；
四个平台的 native 和真实账号 live 均尚未执行。最终验收以 Phase 9 的身份匹配证据为准。

## 启动环境补充

Bun 入口显式固定 bunfig/tsconfig，关闭自动安装、dotenv 和宏；保留 BUN_OPTIONS 与转译缓存变量，防止本机覆盖注入启动代码。
行为依据为 [Bun runtime flags](https://bun.sh/docs/runtime)、[环境加载说明](https://bun.sh/docs/runtime/environment-variables)
及 [bunfig 配置](https://bun.sh/docs/runtime/bunfig)。这些是声明与 mock 检查，目标 Bun 1.4.0 的 native 验证仍未执行。
运行收据另外绑定平台与工具链身份；关键受管启动文件漂移会拒绝 run，UI 允许的偏好仍沿用字段所有权。
