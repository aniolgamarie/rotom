# 基础阶段验证

> 本文保留软件隔离阶段的原始结果与当时限制；后续已授权的 Linux x64 真实验证见 [Linux smoke](linux-smoke.md)，不能将本文历史“未执行”理解为当前平台状态。

日期：2026-09-24。平台：Linux x86_64 / glibc 2.32 / Python 3.11.11。范围：T001–T016 默认隔离实现与回归。基础阶段组合门禁已通过；真实宿主与账号验证仍未执行。

## 环境检查与既有部署回归

执行者：主代理。测试保持既有 `tests/conftest.py` 的临时 HOME/XDG、网络阻断、假进程和文件哨兵边界，没有启动第三方宿主。

默认沙箱将 `/`、`/tmp` 属主映射为 uid 65534，而进程 uid 为 1002；现有 `paths._check_ancestor` 因此在进入实际部署断言前拒绝路径。将临时目录移至仓库也不能避开根目录祖先检查。未修改或绕过生产保护。

经工具自动审批，在正常文件系统权限环境执行：

```sh
.venv/bin/python -m pytest -q tests/test_deployment.py
```

结果：退出码 0；**15 passed in 0.52s**。覆盖已有三方比较、无变化 apply、非受管字段保留、备份消费与恢复等部署行为。此结果仅对应当时工作树；随后共享部署代码变更需要重跑受影响测试。

## 首批 OMP 断言

executor 报告 29 个隔离断言已通过，覆盖身份、两种引用守卫、参数等号/别名/`--` 文本和发现来源。第一次完整运行时对应实现已同时存在，没有可诚实记录的先行失败运行；不补造红测证据。后续后端/生命周期集成测试按先测试再实现执行，完整命令、结果与范围将在本阶段验收时补齐。

真实宿主、账号和平台验证：未执行。

## 完整依赖后端（T009–T011）

执行者：主代理；scout（gpt-5.6-luna / medium）独立静态复核。原计划新增 executor 被平台 `agent thread limit reached` 拒绝，主代理接手该独立文件范围。

```sh
.venv/bin/python -m pytest -q tests/test_omp_dependencies_foundation.py --tb=short
```

先行完整合成锁用例收集 9 项，目标契约尚未实现时 **4 failed, 5 passed**（0.26s，退出1）；实现后9项通过。随后增加平台/下载/激活/树形状/resolver用例，18项通过。独立审计发现缺少进程中断恢复；新增中断后磁盘状态用例先 **1 failed, 18 deselected**，补激活日志、父目录fsync和下次sync恢复后，最终 **19 passed in 0.46s**，退出0。

断言覆盖：完整上游锁/许可证材料、固定归档/asset摘要；输入与目标清单、正文/执行位/链接校验；实际解释器路径/版本/内容身份；receipt不能自报摘要冒充受信锁；cache路径安装不创建instance/HOME/state；共享包租约阻止sync；musl/Windows/未知架构拒绝；损坏缓存和下载失败不激活；激活异常恢复旧目录；中断后显式sync恢复日志；多余文件/模式/链接漂移拒绝。所有二进制都是临时合成数据，未执行；下载替身遵守断网fixture。正式来源/完整本地包锁待US1资源齐全时生成，不使用本测试合成锁。

没有真实断电测试；目录fsync与中断后状态测试证明实现路径，不宣称所有文件系统硬件耐久性。三层锁的调用顺序与spawn行为仍由T014集成测试单独验收。

## 基础组合门禁（T016）

主代理最终执行：

```sh
.venv/bin/python -m pytest -q tests/test_omp_foundation.py tests/test_omp_runtime_foundation.py tests/test_omp_dependencies_foundation.py tests/test_adapter.py tests/test_deployment.py tests/test_config_schema.py tests/test_runtime.py tests/test_cli.py --tb=short
```

正常文件系统权限环境，保持所有临时HOME/断网/假进程保护；结果退出0，**369 passed in 6.52s**。executor此前对最后修订的foundation+CLI增量验证为189 passed/3.37s。关键实现由executor（gpt-5.6-sol / medium）完成，依赖后端由主代理完成，scout（gpt-5.6-luna / medium）提供来源与独立差距核对。

集成断言通过：真实公共apply/runtime.run配合假子进程；owner/pending为4、无包5、实际SecretRef缺失3；物理实例→state→包租约顺序和三个继承fd；子退出37及信号137保留；失败零spawn/零实例污染；来源TOCTOU复查；caller身份变量拒绝；state/cache变化要求重新apply；非空未归属目录的条目/mtime不变；OMP与旧Pi守卫kind隔离，当前/历史/待恢复投影的强制分类；实际native意图schema；裸OMP lock不读取local/workspace；固定源码direct来源与危险组合设置拒绝。

`git diff --check`、相关Python编译、严格schema加载通过。项目opt-in细粒度来源、九行能力映射、库存迁入与usage尚由后续故事实现，不能由本门禁推定完成。

后续新增显式 inspect/mcp 自检后，正式锁更新为 `0387bc982c13d768c77cf1be42b0243ebd0fabb0aa0a7ca9048e903d1d1134eb`；受影响隔离回归 57 项通过，真实命令与边界见[Linux smoke](linux-smoke.md)。
