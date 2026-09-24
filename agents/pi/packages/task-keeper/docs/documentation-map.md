# 发布文档地图

[文档首页](../README.md)

这里记录面向使用者的主题覆盖，不引用测试通过率作为文档覆盖率。发布时只需插件包内的这些Markdown、JSON示例和Schema；本地规划和运行工件不是阅读依赖。

| 主题 | 原理/约束 | 操作/配置 | 示例或排障 |
|---|---|---|---|
| 安装与启用 | [发布范围](release-notes.md) | [上手](getting-started.md) | [普通配置](examples/ordinary.json) |
| begin与受管任务区别 | [原理](architecture.md) | [日常使用](usage.md) | [受管演示](getting-started.md) |
| 当前模型恢复与小时等待 | [请求准入](request-admission.md) | [恢复配置](configuration.md) | [排障](troubleshooting.md) |
| task/job/workScope身份 | [原理](architecture.md) | [日常使用](usage.md) | [预算排障](troubleshooting.md) |
| 多轮统计/费用/套餐 | [原理](architecture.md) | [配置](configuration.md) | [统计命令](usage.md) |
| 受管工作树与验收 | [原理](architecture.md) | [真实Node演示](getting-started.md) | [验收排障](troubleshooting.md) |
| B质疑、修订和复用 | [多模型](multi-model.md) | [B配置](configuration.md) | [受管配置](examples/managed-demo.json) |
| 主agent规划与多job依赖 | [多模型](multi-model.md) | [主agent提示示例](multi-model.md) | [使用手册](usage.md) |
| 一次性时间与选模 | [原理](architecture.md) | [配置](configuration.md) | [定时命令](usage.md) |
| 暂停/停止/重启/unknown | [请求准入](request-admission.md) | [使用](usage.md) | [排障](troubleshooting.md) |
| 配置、验收版本和状态升级 | [配置](configuration.md) | [维护](state-maintenance.md) | [排障](troubleshooting.md) |
| 能力、审查与测试覆盖 | [发布说明](release-notes.md) | [测试复现](testing/README.md) | [覆盖口径](release-notes.md) |

这张表证明上述主题有发布入口；不承诺覆盖所有语言、框架、供应商或本机环境的部署细节。配置示例经过结构校验，演示检查可以本地执行；真实模型调用需要读者自己的Pi模型和认证绑定。

维护约定：新增/修改功能时同步更新原理、配置、命令示例和对应排障项；公开入口不链接到本地规划目录、被忽略的reviews或test-results。历史设计/开发记录不是当前用户手册。
