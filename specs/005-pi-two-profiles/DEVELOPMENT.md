# 开发分支续接

分支：`feat/pi-toolkit-upgrade`。本检查点保存当前未完成实现，正式32/100；Base、Full 和总交付均未通过，AUTO OFF。不要把 checkout、安装成功或历史组件证据解释成产品验收完成，也不要直接部署到日常实例。

## 在另一台机器取得工作

```sh
git clone --branch feat/pi-toolkit-upgrade https://github.com/aniolgamarie/rotom.git
cd rotom
git status --short --branch
uv sync --locked
```

Python要求3.11+；默认插件测试使用 Node24.14.0。`uv sync --locked` 会准备本机 `.venv`，可能需要下载锁定依赖。Linux x86_64 是本次必需平台；其他平台没有因此获得支持资格。

此分支已同步本地主干 `e1a9b13`，旧分支23个patch等价历史不重复重放；开发检查点为主干之上的新增提交。提交前按AGENTS核对仓库级身份，不沿用新机器全局账号或系统推导值。确认HEAD所记录的身份符合项目拥有者后，可在新clone本地设置：

```sh
git config --local user.name "$(git show -s --format=%an HEAD)"
git config --local user.email "$(git show -s --format=%ae HEAD)"
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

先读 `AGENTS.md`、`STATE.md`，再读本目录 `spec.md`、`tasks.md`、`acceptance.md` 和 `implementation-status.md`。Spec Kit工作流和constitution已随仓库保存；机器专属 `.specify/feature.json` 不随Git迁移，需要时使用显式 feature目录：

```sh
export SPECIFY_FEATURE=005-pi-two-profiles
export SPECIFY_FEATURE_DIRECTORY="$PWD/specs/005-pi-two-profiles"
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
```

此处 `$PWD` 是新 checkout，不能复制历史材料中的原机绝对目录。

## 可以先运行的默认验证

以下使用临时HOME、假进程/Provider和原守卫，不启动第三方宿主或真实模型。先确认所需工具和临时目录容量；不要为了通过而关闭权限或网络守卫。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_pi_delegate_execution_evidence.py \
  tests/test_pi_reviewer_prompt_projection.py

node scripts/test-pi-mock.mjs \
  agents/pi/packages/task-keeper/tests/evidence-producer-service.test.ts \
  agents/pi/packages/task-keeper/tests/evidence-validity.test.ts \
  agents/pi/packages/task-keeper/tests/evidence-producer-artifact-failure.test.ts
```

Node测试文件顺序有意义：服务夹具先安装受管runtime，独立producer测试随后加载。此处是有界续接检查，不是声称全仓库测试全部绿色。`tests/test_pi_temporary_overlay.py` 当前故意暴露未应用模式的缺口，单独作为下一候选任务的RED测试；其他历史失败和未验证项见STATE。

本次准备 push 时已重跑上述两个有界检查：Python **81 passed**，Node **74 passed**；没有启动SDK、真实账号或模型。当前外层执行沙箱首次运行时触发祖先UID检查和NETLINK_ROUTE限制，未计为通过；改用全新受信私有临时目录及原有默认测试守卫后通过，未修改产品权限逻辑。新机器若遇到同类环境不足，应先修环境并单列记录。

同步整理后的主干时，扩大到共享配置/凭据展示、隔离守卫和Pi fixture的检查记录为222 passed、28 skipped、1 failed；失败是新增测试引用旧 `kimi_openai`，已按主干当前 `kimi_code_openai` 修正，相关模块最后4 passed。28项为默认未显式启用的独立OS测试，不能计为OS行为通过；各轮有重叠，不累加。同步后的Node受影响74项也通过。

待提交Python414个文件的语法和JSON86个文件的解析检查通过；候选patch十个base文件及patch SHA256核对通过。有限凭据模式和路径检查没有发现真实凭据证据，不作为全面安全审计或产品最终验收。

## 资产与构建边界

`locks/pi-modern/`、现代声明/配方、npm resolution seeds、本地包归档、固定Node Linux归档、bwrap归档与build record/build inputs均随本检查点保存。Node归档约56MB，因此clone需要相应带宽和磁盘；保留它是为了避免续接依赖原机器缓存。旧Pi的大型Codex/模型资产仍按已有ignore规则不上传。

固定资产校验/获取的现有入口为：

```sh
.venv/bin/python scripts/fetch-pi-assets.py --profile pi-base
```

它只获取带固定URL/摘要的公开资产。带build record的自建bwrap要求已存在匹配归档；缺失时返回`pi-built-asset-import-required`，不会偷偷重编译或换来源。不要把`lock --agent pi`作为新机器初始化步骤：它是改变依赖的维护操作。

部分历史探针和 `scripts/pi-build-current-base.py` 仍使用原机Node/npm材料与 `.cache` 路径，不是跨机器一键重建入口。恢复对应原生阶段前，按公开入口重新准备固定工具、私有来源与场景计划，或先将这些准备脚本参数化；不得借原机摘要冒充新环境资格。

## 未应用候选与证据

`checkpoints/temporary-overlay/proposal.patch` 保存中断时10个候选源码文件相对于正式源码的差量；`manifest.json`记录两边SHA256。它是未审查、未完成、未应用的候选，不在实际运行/安装路径中。恢复时阅读其README，在新的临时来源副本中继续，先补完整helper和有意义默认测试，再冻结审查。

首轮生产编辑曾被自动审批明确拒绝，原源码未改变。保存候选是交接，不构成对该拒绝的绕过或应用批准；新机器必须按届时有效的权限和工具审核流程处理。

`.cache/`原始日志、私有安装树、临时SQLite、运行账号、capability/nonce、活动实例和会话不随分支上传。STATE里的Root收据和历史通过数仅帮助定位工作，不等于Git携带原始证据。在新机器重跑必需检查并记录新身份；不要重新创建旧lease/permit/Writer状态，或根据PID/心跳猜旧机器执行已经终止。

## 给接手代理的指令

> 继续本分支的Pi双Profile长期任务。先读AGENTS.md、STATE.md和specs/005-pi-two-profiles的spec/tasks/acceptance/implementation-status；正式32/100、所有产品gate false、严格计量前AUTO OFF。当前优先处理临时overlay完整候选与真实成功检查/当前性缺口；候选patch未应用且其RED测试不是绿色基线。不修改上游，不复制账号，不把原机或合成证据算成当前真实验收。核对新机器工具、目录权限、容量和执行身份，以有意义默认反例推进，稳定后审查，再按实际权限执行必要低风险原生验证。
