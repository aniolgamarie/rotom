# 上手指南

[文档首页](../README.md) · [配置参考](configuration.md) · [排障](troubleshooting.md)

## 1. 准备运行环境

使用Linux、Node24.1.0；确认Git、bubblewrap（bwrap）及用户/PID命名空间可用。在插件目录执行：

```sh
npm ci --ignore-scripts
npm run prepare:adapters
```

这会安装包内锁定的Pi0.84.4和pi-subagents0.63.0，并仅补丁化本包依赖。重新安装依赖后需要重新prepare并重启Pi。

模型和凭证仍由Pi模型目录及认证机制管理，Task Keeper不创建账号或复制API key。以下的provider/model必须替换为Pi已有模型。包加入settings不等于启用；`/orch init`只创建禁用配置，已有文件不覆盖。

## 2. 普通对话：先启用统计与当前模型恢复

[ordinary.json](examples/ordinary.json)是可独立解析的配置，使用Pi当前模型，不需要Task Keeper路线表。将其保存为你选择的新配置文件；若已有配置，合并字段并保留原绑定。

从插件目录运行：

```sh
npm run launch -- --cwd /absolute/path/project --config /absolute/path/ordinary.json --provider YOUR_PROVIDER --model YOUR_MODEL --thinking off --tools read,write,edit
```

`--config`不会自动加载本页面示例，必须指向实际保存的文件。该命令的工具集合与ordinary示例profile一致。启动器控制扩展集合；不要同时加载另一套subagents或额外扩展再假定恢复已获支持。

进入Pi后检查：

```text
/orch doctor
/orch begin --group parser-fix -- 修复空字段解析
```

记下返回的taskId，然后正常描述工作。`begin`本身不调用模型。完成后：

```text
/orch usage <taskId>
/orch accept <taskId>
```

这里的accept只是用户认可，不会自动补跑测试。只结束统计、尚未认可时用`/orch finish <taskId>`。普通对话仍使用当前工作目录，不会自动隔离修改。

## 3. 受管任务：跑通一个完整示例

以下在新临时目录创建一个有真实测试的Node小项目；不会复用或覆盖已有工程。这个示例用于理解配置，接入真实工程时应替换检查命令和测试输入。

```sh
TASK_KEEPER_DEMO=$(mktemp -d /tmp/task-keeper-demo.XXXXXX)
cd "$TASK_KEEPER_DEMO"
git init -q
mkdir src tests
cat > src/sum.cjs <<'JS'
module.exports = (a, b) => a - b;
JS
cat > tests/sum.test.cjs <<'JS'
const test = require("node:test");
const assert = require("node:assert/strict");
const sum = require("../src/sum.cjs");
test("adds positive numbers", () => assert.equal(sum(2, 3), 5));
test("adds a negative number", () => assert.equal(sum(-2, 3), 1));
JS
git add src tests
git -c user.name="Task Keeper Demo" -c user.email="demo@example.invalid" commit -qm "Initial failing demo"
echo "$TASK_KEEPER_DEMO"
node --check src/sum.cjs
node --test --test-reporter=tap tests/sum.test.cjs
```

演示仓库需要一次初始提交，才能创建候选worktree；上述身份只用于这条演示commit，不修改全局Git配置。语法检查应通过，两个测试应失败。这是交给agent修复的真实错误；不要先降低测试要求来取得通过。

将[managed-demo.json](examples/managed-demo.json)保存到项目目录之外的新配置文件，编辑：

- 两条路线的`YOUR_PROVIDER_A/B`和`YOUR_MODEL_A/B`，以及相应`accountBinding=provider:<provider>`。可以使用同一供应商，先用同一个模型也可验证流程。
- 用当前Node的绝对路径替换`/ABSOLUTE/PATH/TO/node`，可通过`node -p process.execPath`查看。
- `projectRouteApprovals["*"]`示例允许全部项目使用这两条路线；正式配置可改成doctor报告的目标repository ID。

该示例的检查绑定只适用于上面的小项目。build的`inputs=[]`表示语法检查逻辑全部由已绑定的Node和参数定义；`src/sum.cjs`是被测源码。focused-tests将测试文件固定为验收输入，agent修改它会触发审批，而不能悄悄改测试。

从插件目录启动（项目路径使用上面输出的实际目录，切换终端时不要假设环境变量仍存在）：

```sh
npm run launch -- --cwd /absolute/path/task-keeper-demo --config /absolute/path/managed-demo.json --provider YOUR_PROVIDER_A --model YOUR_MODEL_A --thinking off --tools kernel_task
```

先执行`/orch doctor`确认功能已启用、绑定无缺口，再提交：

```text
/orch fix 修复 src/sum.cjs 的加法实现，保持测试要求不变
/orch status <jobId>
```

预期流程是：基线语法检查→A修复候选→语法检查和两个真实测试→独立必要审查。最终状态须为当前有效的COMPLETED；status会给出候选目录、工件和检查结果。原项目里的错误实现仍保持原样，插件不会自动合并候选。

如果检查或审查未通过，查看reason而不是反复新建job。确认候选后，再按你自己的Git工作流审查并采用修改；不能把worktree创建或模型输出Done当成验收。

## 4. 接入真实项目

将`verificationBindings`替换为真实构建/测试命令、超时和解析器。TAP需要真实汇总，JSON解析器需要`tests/passed/failed/skipped`计数；若希望实现错误自动修复，可信JSON结果还需`failureCategory: "implementation"`。绑定测试/构建脚本及其传递验收逻辑到`inputs`，不要把待修源码误标为验收逻辑。

本示例不会自动转接npm、pytest或其他测试框架的输出；必须确认所选解析器能识别实际输出。核对[配置参考](configuration.md)和[多模型指南](multi-model.md)后，再开启第二视角或定时选模。
