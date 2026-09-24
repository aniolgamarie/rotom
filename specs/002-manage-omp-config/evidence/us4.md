# US4 usage 隔离证据

日期：2026-09-24。执行者：主代理。只有假子进程、临时HOME/配置和虚构输出，没有登录或请求真实usage。

原生封装先行7项失败后实现，7 passed in 0.16s；受管参数/门控先行21项失败后实现，首次组合1 failed/33 passed，失败暴露共享OMP参数钩子尚未分发usage。接入独立usage tail判定后：

```sh
.venv/bin/python -m pytest -q tests/test_omp_usage_native.py tests/test_omp_usage_managed.py tests/test_omp_usage_results.py -k 'not cli' --tb=short
```

**34 passed, 8 deselected in 0.44s**，退出0。该阶段另有8项CLI接线测试先执行并失败，后续接线及验收如下。

后续CLI接线已完成：两种模式三个测试文件与现有CLI组合 **147 passed in 2.63s**。原生模式在读取local/工作区之前分发；前置local/machine无显式profile失败2，usage之后的参数全部归原生tail。此后输出字节测试也扩展到受管模式，两模式共12项逐字节检查，见最终全量回归计数。

覆盖原生PATH、cwd和完整env、只剥离一层`--`、缺binary5、signal退出143；受管精确native profile argv、中性HOME、三层租约、无关secret缺失不阻塞、活动/pending4/缺包5/身份env2。查询grammar保留`-p` provider、`-r` redact、clients/invalidate/history/days及未知原生查询选项，不误套用会话参数含义。

`usage-cases.json`明确是合成输出，不冒充原生schema或账号证据。测试对无账号/国内不支持/kimi部分失败/zai窗口缓存/codex客户端等字节流逐字节比较，包括非UTF8和NUL，管理器没有解析、补零、改provider名称或包装stdout。固定上游/国内官方支持范围见[来源复核](usage-sources.md)。真实usage未执行。
