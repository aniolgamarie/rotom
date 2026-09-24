# US5 依赖维护与平台隔离证据

> 本文保留软件隔离阶段的原始结果与当时限制；后续已授权的 Linux x64 真实验证见 [Linux smoke](linux-smoke.md)，不能将本文历史“未执行”理解为当前平台状态。

日期：2026-09-24。执行者：主代理；scout（gpt-5.6-luna / medium）独立复核后端闭包。只有临时仓库、独立合成锁与摘要匹配的假资产，不启动第三方宿主、不访问真实HOME或账号。

```sh
.venv/bin/python -m pytest -q tests/test_omp_dependencies.py tests/test_omp_platforms.py --tb=short
.venv/bin/python -m pytest -q tests/test_omp_dependencies.py tests/test_omp_platforms.py tests/test_omp_dependencies_foundation.py --tb=short
```

第一轮 **1 failed, 20 passed in 0.52s**，退出1：未声明空目录未被完整性检查发现。增加目录集合、0700和所有者检查后，组合 **40 passed in 0.79s**，退出0。命令使用正常文件系统权限视图，保留测试本身临时HOME、断网和假进程保护。

断言覆盖：固定版本/commit/资产SHA/上游闭包缺项/包入口/执行位/解释器要求；二进制同size且恢复mtime的篡改、receipt解释器身份、硬链接、未知目录；离线缓存复用与显式修复、未损坏sync零重写、lock和HOME哨兵不变；新锁生成另一运行身份、旧包正文保留且旧部署不得自动跟随；stage失败及激活失败恢复、pending恢复、共享包租约阻止维护。四平台仅模拟选择与假资产安装，musl/Windows/未知平台失败5且不查全局OMP。

资源与配方稳定后已执行最终正式锁重解析，结果如下。没有SIGKILL/真实断电、真实发布二进制或任一平台宿主通过证据；macOS机器未提供。

最终对同一真实 commit 归档及官方校验清单重新执行 resolver，并断言 read_lock 读取结果与解析产物一致。发现清单 JSON 新增为配方输入，该阶段身份 `2227b4e7de27f28f2963e33facdf6d977d4d6924e72bbed35690e884bb3c74c2`，101 资源/2 包/15 配方输入/4 平台；没有占位摘要。完整上游 bun.lock、MIT LICENSE、THIRD-PARTY-NOTICES、provenance 和 NOTICE 均保留。此步骤没有执行二进制，未改变既有 HOME。最终全量见[回归](regression.md)。

后续新增显式 inspect/mcp 自检后，正式锁更新为 `0387bc982c13d768c77cf1be42b0243ebd0fabb0aa0a7ca9048e903d1d1134eb`；受影响隔离回归 57 项通过，真实命令与边界见[Linux smoke](linux-smoke.md)。

后续提交前审查补齐 PERSONALITY 来源与 PI_CONFIG_DIR 门禁，清单和正式锁再次更新；最新结果见[提交前审查](precommit-review.md)。上述测试计数及摘要保留为各阶段历史证据。
