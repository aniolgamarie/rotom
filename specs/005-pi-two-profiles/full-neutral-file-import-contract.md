# 受管后端中立私有文件原语接线

2026-10-09 root，离线 Full 迁移基础小包，与正在执行的Base探针互不影响。静态证据确认 managed-backend -> launch -> managed-backend 的直接ESM循环；launch 已从 private-files.ts 原样 import/re-export privateFile/writePrivate。无需复制函数或改文件读取语义。

唯一写者只修改 agents/pi/runtime/managed-backend.ts 的 privateFile import 以及 managed-worker-main.ts 的 privateFile/writePrivate import，从 ./launch.ts 改为已有 ./private-files.ts。不改函数body、SDK/legacy运行方式、版本、权限、worker生命周期/队列/任务/身份/锁，不新增Host patch或公共API。launch旧导出继续保留，旧caller兼容。此包只清除这两个直接依赖及观察到的backend循环，不声称所有transitive legacy依赖消除或Full已经现代运行。

唯一代码写范围这两文件；自有证据目录 full-neutral-file-import-implementation-review01。先即时前像、静态证据/两个精确import差异；低影响可逆import重定向不新写镜像测试，也不为RED修改无关fixture。固定默认fake runner只跑现有 agents/pi/runtime/tests/managed-backend.test.ts（必要时managed-worker.test.ts若有新影响证据）。Node24.14.0 scripts/test-pi-mock.mjs，临时HOME/断网/假SDK/进程守卫，禁止直接import/执行managed-worker-main入口或真实SDK/宿主。根盘/tmp ENOSPC可用该自有目录0700/data TMPDIR和同固定命令require_escalated正常owner路线。不能重跑旧native/改变授权材料，也不改harness。

完成稳定两个imports diff/pins、意义现有回归/无变body检查及STOP。与其他writer并行，不回退别人更改，不派生子代理。扩大写范围/语义/SDK执行或两有效修复无解升级root。正式8/100、AUTO OFF，Full/SourceHold及实际worker现代迁移仍待实现。
