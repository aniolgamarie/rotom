# Worker 输入闭合契约与 SDK 执行实现分离

2026-10-09 root，Full 现代适配基础默认小包。neutral file imports已验收；backend仍为数据校验import整个managed-worker实现。现有validator只依赖Node createHash及managed-types纯数据函数；transport闭合规则仍openai-completions，不修改能力边界。

将原validateWorkerInput完整函数文本、仅供其使用的toolsAllowed Set与需要的最小imports移至新增 agents/pi/runtime/managed-worker-contract.ts。managed-worker.ts import同一函数并原样re-export，既有runManagedWorker仍用该原binding；managed-backend.ts直接import新contract。保持所有validator条件/错误code/exitCode/clone/完整digest及执行functionbody字节不变；不得为现代版本放宽schema/API、移除角色/根/数据库归属或声明认证/执行资格。不改SDK/宿主/vendor、models、worker版本或旧运行方式。

新contract只能import Nodecrypto及managed-types，不导入launch/SDK执行模块。既有runtime recipe source_path选择整个自有目录，只exclude tests/node_modules/.git，内部relative模块可自然复制；不新增public package export或types，不构建/发布历史宿主，也不把新模块加入Base未选Full的runtime manifest。现代Full实际source图仍待显式冻结。

唯一写范围新managed-worker-contract.ts、managed-worker.ts的import/reexport及validator移除、managed-backend.ts的validator import；如最小import清理必须先确认符号未用于执行body，不更改body。唯一writer证据 full-neutral-worker-input-implementation-review01。先即时3原文件前像和函数文本/执行body对比。机械提取不强造RED、不新增镜像test；固定默认fake runner只跑已有 managed-worker.test.ts、managed-backend.test.ts，两模块覆盖现有正反输入与执行callback行为。Node24.14.0 scripts/test-pi-mock.mjs，临时HOME/断网/假SDK/进程守卫；禁止直接worker-main/SDK/native执行。/tmp ENOSPC可本own0700/data TMPDIR加同命令require_escalated，保留限制和真实结果。

确认新module图/所有留存body不变，old/new import获得同一个函数引用。若现有validator有隐藏状态/authority引用或包装/新tests/harness/types/recipes写范围必要，升级root。两有效尝试仍失败升级root，不每小步等继续。完成稳定diff/pins/logs/STOP，与另一个executor不共享source文件，不回退别人，无子代理。正式8/100、AUTO OFF；现代worker/manager/SourceHold及Full资格未完成。
