# 不修改 agent 上游源码：历史偏离与迁移盘点

2026-09-30，维护者将“不修改任何 agent 上游源码”确立为项目基本原则。依据[宪章 VI](../../.specify/memory/constitution.md#vi-不修改任何-agent-的上游源码)，新功能仅使用官方配置、公开扩展 API、官方 CLI 与本仓库自有适配实现；不继续维护或构建发布宿主补丁。

原则记录并不表示已有部署全部合规。本清单保存已发现的历史来源和迁移状态，不授权自动停止宿主、修改账号、删除历史证据或顺带迁移其它工具。

| 范围 | 已发现来源 | 当前状态与下一步 |
|---|---|---|
| OMP 权限管控 | `agents/omp/patches/permission-control/`、`locks/omp/permission-control/` | 当前明确授权改为官方运行包与独立插件，仓库实现与官方宿主隔离验收完成；本机日常实例已按后续授权完成 sync/plan/apply，官方二进制与启动准入通过，账号库未访问 |
| Pi 历史构建 | `agents/pi/build/` 中的 permission-system、processes-supervisor 等 patch | 待逐项核对宿主/插件边界、运行配方引用和公开接口替代；不把所有 patch 文件都直接认定为修改 agent 宿主，也不沿用旧许可继续修改宿主 |
| DSH/Cursor 历史 vendor | `locks/dsh/vendor/cursor-managed.patch`、`cursor-provenance.json` | 待核对其是否修改受本原则约束的 agent 运行代码，以及恢复官方版本后的登录、更新与来源边界 |
| 插件及包元数据 | `agents/pi/packages/subagents-patch/`、`locks/dsh/vendor/tui-bundled-metadata.patch` | 待核对是否独立插件或仅包元数据；不能只凭文件名与后缀断言宿主源码已修改 |

实施每项迁移前应确认官方公开能力、受管配置差异与冲突、运行包身份、账号/会话保护及受影响验证。真实宿主和账号测试仍按默认隔离边界获得独立授权。历史验收身份不可转移到新实现；无法通过公开接口保留的能力必须明确说明。
