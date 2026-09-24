# US1 八类九行配置生命周期

> 本文保留软件隔离阶段的原始结果与当时限制；后续已授权的 Linux x64 真实验证见 [Linux smoke](linux-smoke.md)，不能将本文历史“未执行”理解为当前平台状态。

日期：2026-09-24。主代理实际执行adapter/pipeline/capture/resources四文件：**35 passed in 2.75s**。executor受影响组合为295 passed in 5.27s。以下为隔离证据，尚未宣称原生生效。

覆盖main+smol、两规则、完整技能与执行位、prompt、完整theme及变量语义、Ctrl+P和空数组、绝对锁定扩展入口、stdio/HTTP映射；真实catalog/fixture经resolver和RenderContext生成确定性产物。生命周期覆盖无owner/无包首次plan、无变化apply、未受管字段保留、owner初始化中断、apply/rollback两条pending恢复、备份消费、静态doctor与allowlist capture。后续[迁入端到端](us3.md)补完整fixture synthetic sync/apply/run/capture。

## 独立资源（T022–T024）

主代理准备固定源码完整主题/schema、只读review prompt、无外部依赖原生TS扩展和stdlib echo MCP；源码/许可见 `agents/omp/resources/NOTICE.md` 与各包LICENSE。扩展API按固定v18.3.0 `registerCommand` 和 `ctx.ui.notify`核对，未执行宿主加载。

```sh
.venv/bin/python -m pytest -q tests/test_omp_resources.py -k mcp --tb=short
.venv/bin/python -m pytest -q tests/test_omp_resources.py --tb=short
```

MCP纯函数骨架先收集2项并失败（2 failed, 1 deselected/0.18s，退出1），实际实现后完整测试**4 passed in 0.11s**（退出0）。测试只导入本地自写协议模块，不启动进程；覆盖初始化、tools/list、echo、非法请求/参数、notification无回复、JSON-lines帧以及解析失败不回显输入哨兵。主题样例满足完整上游schema，删必需颜色或添加未知字段时失败。后续适配器另校验颜色变量/循环/值，不能仅凭schema声称所有颜色输入合法。

样例标记：`ROTOM_OMP_HEALTH_OK`、测试echo正文 `你好 ROTOM_OMP_ECHO_OK`。当时扩展代码没有runtime import或外部依赖；MCP解释器精确身份由后端receipt记录。

当时规范包树摘要（后续诊断扩展已更新）：

- rotom-health：`da9707f1fac93194f4da621856afe30143748394ed181c03dc0985c1ec4852fa`，入口`index.ts`。
- echo-mcp：`c10617b101717ec6ce399da846e165d7a6f1cfb5c2aad02d2f6c405cd187faf4`，入口`server.py`。

真实主题加载、提示词展开、扩展命令及OMP调用MCP：未执行。

## 首轮正式锁（T026）

后端resolve_lock读取已独立验证的不可变commit归档和官方SHA256SUMS，生成完整正式`locks/omp`，随后由未修改的read_lock重新核验来源、schema、全部正文/执行位和配方闭包。首轮身份`7fb87fae17e9310ef94f1d13a628592811be442daa774195b8c910ce174e579c`，101项资源、2个包、14项配方输入、5份完整上游材料；没有下载/执行发布二进制。

验收fixture仅选本地echo-stdio；HTTP server仍在fixture registry中，单独通过隔离映射验证。临时验收仓库将registry/profile复制到公共目录后会新增配方输入，因此必须显式lock再sync；不为方便测试豁免新输入的完整性检查。

最终配方增加固定发现清单校验，正式锁重新解析为 `2227b4e7de27f28f2963e33facdf6d977d4d6924e72bbed35690e884bb3c74c2`，101 资源/2 包/15 配方输入/4 平台，见[最终依赖证据](us5.md)。

后续新增显式 inspect/mcp 自检后，正式锁更新为 `0387bc982c13d768c77cf1be42b0243ebd0fabb0aa0a7ca9048e903d1d1134eb`；受影响隔离回归 57 项通过，真实命令与边界见[Linux smoke](linux-smoke.md)。
