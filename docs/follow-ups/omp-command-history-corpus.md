# 历史命令解析回归集

本轮在 `test/omp-command-history` worktree 中开发，基线 `139b277`。用户授权只读提取 Pi、Codex、OMP 的历史命令，脱敏后用于验证当前普通 Bash 审批解析器。原始命令、用户提示、工具输出、账号库和凭据不进入仓库；不会执行任何历史命令、启动 agent 或调用模型。

## 验证范围

测试对象为 `standalone-shell-analysis.ts` 中的纯解析函数及模式匹配函数，不是宿主 Shell 执行器。历史记录只证明命令曾被提交，不能证明执行成功、低风险或获得授权。解析完成也不等于自动批准。

两种集合分别维护：

- 本机私有候选语料：显式指定日志根，流式读取已知工具事件，只提取命令。脱敏、去重后保存在 0700 私有缓存目录内的 0600 文件。自动脱敏不是公开发布保证，命令内嵌代码、未知高熵值和未支持载体必须隔离并单独计数。
- 仓库内固定回归样本：从候选语料的语法形状中人工选择、用虚构路径和参数重建，并独立标注预期命令/参数/连接符或保守拒绝。这些样本不保存真实机器路径、项目数据、原文指纹和日志文件名。

统计必须包含三种来源的文件数、命令事件数、脱敏后唯一命令数、未知载体/坏记录/隔离数量，以及解析完成与拒绝数量。拒绝不能算成语法覆盖成功。已知未支持语法与必须保持拒绝的动态结构分开标记；接受率不是解析准确率，也不是风险审批准确率。

## 验收重点

支持样本检查完整的 argv 和连接符，不能仅检查“没有抛异常”。混合读取/写入的复合命令必须提取后续命令，不允许只看开头。引号中的分隔符、转义、管道、布尔连接和目录切换均有固定预期。动态替换、控制结构及截断输入检查失败边界。通配符、重定向和多行命令作为当前覆盖缺口显式报告，不以白名单或删掉解析守卫掩盖。

提取器使用虚构日志验证凭据哨兵、文件权限、去重、错误载体、输入不变及不执行命令；默认测试不读取真实 HOME。真实日志提取是本轮单独授权的只读步骤，后续默认 CI 只使用固定样本。

## 提取和重跑

`scripts/omp-command-history.py` 没有默认 HOME 搜索路径。每个来源可重复传入 `--pi-root`、`--codex-root`、`--omp-root`，输入只能是显式 JSONL 文件或目录。输出只能是仓库 `.cache` 或系统临时根（包括 `/tmp`）内的私有子目录，独占创建且拒绝子路径符号链接和覆盖已有文件。系统临时根的官方别名会规范化，临时根即使指向仓库公开目录也不能输出。不要将候选文件改为公开 fixture。

Pi/OMP 只读取 assistant 的已知 Bash 工具事件；Codex 支持 JSON 工具参数和显式开启的 JavaScript 静态提取。JavaScript 必须成对提供 `--bun` 和 `--js-parser-module` 的绝对现有文件路径。后者是受信的本机 `@babel/parser` 模块，不是历史文件；代码通过公开 [Babel parser API](https://babeljs.io/docs/babel-parser) 解析历史文本，绝不求值。没有这两个参数时，JS 载体计为 unsupported，不会猜测命令。

JS 仅提取字面 `tools.exec_command({cmd: "…"})` 或不含插值的模板字符串；变量、拼接、展开、别名、解构、可选调用等不推断。无法解析的引用/调用点记入 `jsUnresolvedCalls`，这个字段包含引用点，不能当作实际执行次数。AST 中找到的调用也可能位于不会执行的分支，因此只能称为候选命令。

```bash
.venv/bin/python scripts/omp-command-history.py \
  --pi-root /explicit/pi/sessions \
  --codex-root /explicit/codex/sessions \
  --omp-root /explicit/omp/sessions \
  --bun /explicit/bin/bun \
  --js-parser-module /explicit/node_modules/@babel/parser/lib/index.js \
  --output .cache/command-history-private/candidates.json

bun scripts/check-omp-command-history.ts \
  --corpus .cache/command-history-private/candidates.json

.venv/bin/python -m pytest tests/test_omp_command_history.py -q
bun test ./tests/omp_command_history.test.ts ./tests/omp_command_history_js.test.ts
```

纯解析测试不依赖 Babel 或宿主 SDK。默认 JS 测试使用合成 AST，真实库集成用例明确 skip；只有显式设置 `OMP_HISTORY_JS_PARSER_MODULE` 为已准备的解析模块时才执行该用例，输入仍全部虚构。现有 Python CI 自动收集提取器测试；新增 `omp-command-parser` job 固定 Bun 1.4.0 跑合成回归和缺口报告。setup action 固定为官方 [v2.2.0 commit](https://github.com/oven-sh/setup-bun/commit/0c5077e51419868618aeaa5fe8019c62421857d6)，不安装或运行 OMP、Pi、Codex。

自动脱敏会排除大量内嵌代码、动态结构、高熵串和无法可靠确定边界的值；路径/秘密归一化也可能合并不同原始命令。因此私有集合存在选择偏差，不能反推完整历史的支持率。坏引号可能在脱敏阶段已跳过，固定样本另外检查这类截断边界。未知日志格式无法全部识别，统计不声称完整捕获所有工具调用。

## 已确认的解析问题

固定集合共 79 条：39 条完整拆分、23 条动态/无效语法拒绝边界、14 条当前覆盖缺口、3 条注释语义错误。前三类检查当前合同的稳定性；拒绝边界和覆盖缺口都不计作语法覆盖成功。后 3 条保持 Shell 语义的正确预期，报告 `semanticConformancePassed=false`。

- `echo ok # note`：注释被当作 argv。
- `echo ok # $(id)`：注释内字符触发不支持判断，而不是被忽略。
- `printf '%s' value # ; rm -rf /`：注释里的分号被当作后续命令。

这些字符串只做纯函数输入。本轮没有修复生产解析器，也没有刷新权限包身份、锁或本机部署。后续应先修复注释词法处理，再分阶段扩展通配符、`2>/dev/null` 等明确重定向和多行语法；使用固定正确预期与历史语料共同验收，不能将守卫整体删除来提高接受率。

## 2026-10-05 验收结果

最终保存的私有候选包含 31,742 次命令出现、跨来源去重后 16,103 条。当前解析器接受 8,640 条、拒绝 7,463 条、抛异常 0；接受率 53.65%，受上文脱敏选择偏差影响，不是完整日志支持率。来源内唯一数存在跨来源重叠，不能直接相加。

| 来源 | 日志文件 | 保留命令出现 | 来源内唯一 | 接受 | 拒绝 |
|---|---:|---:|---:|---:|---:|
| Pi | 594 | 20,769 | 8,337 | 2,911 | 5,426 |
| Codex | 1,052 | 10,958 | 7,792 | 5,755 | 2,037 |
| OMP | 11 | 15 | 8 | 7 | 1 |

脱敏阶段跳过 61,952 次候选命令；未知/不支持载体按记录计数，命令出现按字符串计数，两个单位不能相加。Codex 静态分析了 39,006 份 JS 文本，找到 41,387 个字面命令候选，未解析引用/调用点 1,271 个，坏 JS 45 份。固定集合确认 3 个注释错误；历史集合的局部注释 oracle 可判定输入为 0，不能据此声称历史注释正确。

提取器与隐私合成测试 53 pass；显式已有 Babel 集成 90 pass / 401 assertions；无 Babel 默认测试 89 pass / 1 明确 skip / 388 assertions；现有 standalone/native 64 pass / 543 assertions。默认与显式测试区别只在真实 Babel 集成用例，历史评测另行授权且未执行任何命令。GitHub workflow YAML 本地校验，远程 CI 尚未运行；实际 macOS 和 Windows 未运行，Windows 提取暂不支持。

实际工具链为 Linux x86_64、Python 3.11.11、Bun 1.4.0、Babel parser 7.29.9；未下载新工具链。executor 为 gpt-6.1-sol / medium，scout 为 gpt-6-luna / high。独立审查发现并修复 curl 用户/代理认证与 OAuth 值遗漏、JS 别名统计遗漏；系统临时根用合成测试验证，真实平台不计作通过。

机器可读的[汇总证据](../acceptance/omp-command-history-20261005.json)只含数值和固定样本身份。当时的私有语料保存在 main 的 `.cache/omp-command-history/20261005/candidates.json`（该候选文件在后续二次检查和精简后已替换清理），0700 父目录/0600 文件，未纳入 git；同目录保存不含命令的 `parser-report.json`。本轮中间导出已清理，原始日志未写入或删除。日志可能持续追加，本节是已保存候选集合的快照，重提取的数量可能改变。

## 任务记录

| 状态 | 内容 |
|---|---|
| 完成 | 独立 worktree；三来源只读提取、私有脱敏语料、公共固定样本、纯解析评测、隔离 CI 配置、独立审查与修复 |
| 进行中 | 无本轮实现工作 |
| 失败待决策 | 无交付阻塞；生产解析器的 3 个注释错误及 14 条语法缺口已记录，修复需作为下一轮行为变更 |
| 环境不足未验证 | 远程 CI、真实 macOS/Windows；智能审批准确率、真实宿主行为和跨平台 Shell 执行不属于本轮通过结论 |

## 2026-10-06 二次脱敏与场景精简

用户要求修复隐私 review 发现的问题，再次检查并删除重复测试信息。开发在 `fix/omp-history-scenarios` worktree，基线 `f264d22`；原 Phase 16 汇总保留为历史快照。重新只读提取授权的三个来源，不复用旧脱敏文本作为可信输入。日志持续追加，数量变化不单独归因于脱敏改进。

修复内容：凭据值的引号拼接、引号后缀及反斜线边界不可靠时整条隔离；URL userinfo 不再被邮箱脱敏吞掉 `scheme://`，裸 URL 与控制符分界、查询短值及 fragment 分别遮盖；个人路径补充 `/var/tmp`、`/opt`、`/workspace(s)`、`/private` 和 scp 的冒号前缀。新增重复可传的 `--identity-term`，既做字面身份替换，也检查 shell 引号/转义拼接后的残留；身份值不写入产物或汇总。

提取器输出 `redactionVersion=2`，另一个检查函数扫描已脱敏结果，残留整条跳过并记录 `secondPassSkipped`。精简器进入时对全部候选再扫描，发现问题则拒绝整个输入。最终独立检查另外读取原文视图与 shell 拼接视图，覆盖凭据标记、邮箱、IP、个人路径、身份、URL 凭据及 marker 后缀；16,178 条候选、11,504 条代表及 79 条公开虚构样本中，已识别残留为 0。首次粗 URL 扫描的 9 个候选均在嵌入文本中，按引号和控制符边界复核为误报，不能把粗匹配值当作真实凭据。检查结果不保证未知短秘密全部消失，因此自动语料始终为 `private-review-required`，不转为公共 fixture。

### 分类合同

`scripts/omp-history-scenarios.py` 使用独立词法形状归并，选每组字节数最短、字典序最前的代表；保留成员数、来源并集和出现次数。普通文件名、数字及数据参数可以归一化，未知命令名和普通 flag 按形状归一化；环境变量名、已列出的关键命令和危险选项保留。归并是解析回归的测试抽象，不表示完整命令语义相同，也不能用于缓存风险批准结果。

形状保留命令和连接符顺序、重复命令、参数个数、空参数、引号类型/拼接、转义、未引用 glob 的前后位置、重定向类型及两端 fd、根路径/系统目标。复制类参数保留相同操作数的关联，普通名字的双射重命名合并；`cp a a` 与 `cp a b` 不合并。`sh -c` 的内层命令递归分类，wrapper 和未知 launcher 后可见解释器也保守区分脚本；其它嵌入程序内容按已脱敏文本指纹区分，避免把不同程序都当成一个普通字符串。递归深度超过三层时保留 opaque 指纹，不执行或推断脚本行为。

主类别互斥，按 invalid/control/dynamic/heredoc/redirect/multiline/glob/comment/compound/simple 的优先级选取；附加 features 可以重叠，因此不能将类别数当作全部通配符或多行命令数。没有按生产解析器的“unsupported”结果合并，也没有设定最大条数而静默丢掉不同形状。79 条公开 oracle 独立保存，不随历史语料去重而删除。

| 最终主类别 | 代表数 |
|---|---:|
| compound | 4,294 |
| redirection | 3,599 |
| simple | 1,294 |
| multiline | 1,212 |
| dynamic | 488 |
| glob | 374 |
| control-flow | 243 |

本次保存候选 16,178 条、31,914 次出现，精简为 11,504 个词法场景，合并 4,674 条（28.89%），出现次数全部保留。每条代表增加分类元数据，未压缩 JSON 不一定比旧候选文件小，因此最终用固定 mtime、无原文件名的 gzip 存储：5,230,069 → 1,796,841 字节，减少 65.64%，约 4.99 → 1.71 MiB。数量仍较多是因为复合命令的次序、参数/引用片段及程序内容不同；没有为追求更小体积把这些差异抹掉。

### 重跑与结果

```bash
.venv/bin/python scripts/omp-command-history.py \
  --pi-root /explicit/pi/sessions --codex-root /explicit/codex/sessions \
  --omp-root /explicit/omp/sessions --identity-term example-identity \
  --bun /explicit/bin/bun \
  --js-parser-module /explicit/node_modules/@babel/parser/lib/index.js \
  --output .cache/command-history-private/candidates-v2.json

.venv/bin/python scripts/omp-history-scenarios.py \
  --input .cache/command-history-private/candidates-v2.json \
  --identity-term example-identity \
  --output .cache/command-history-private/scenarios.json.gz

bun scripts/check-omp-command-history.ts \
  --corpus .cache/command-history-private/scenarios.json.gz

.venv/bin/python -m pytest tests/test_omp_command_history.py tests/test_omp_history_scenarios.py -q
bun test ./tests/omp_command_history.test.ts ./tests/omp_command_history_js.test.ts
```

输出仍须私有目录，独占创建并拒绝符号链接；gzip 支持在评测时直接读取。评测文件读取前和解压结果均限制为 64 MiB。Bun 命令使用显式 `./` 文件路径，避免将文件名当过滤条件扫入 `.cache` 中的旧 worktree 或复制仓库测试。

本轮受影响范围：Python **166 pass**；已有 Babel 显式集成 **92 pass / 413 assertions**；默认无 Babel **91 pass / 1 明确 skip / 400 assertions**。新增测试覆盖二次扫描失败、身份拼接、关键形状差分、成员/出现数、确定性压缩、损坏 gzip 和过大输入；最终 gzip CLI 评测退出 0；解压 64 MiB 上限有实现，但未单独构造超限压缩输入测试。workflow YAML 本地校验通过，远程 CI 未运行。一次误扩大的全库测试尝试有大量临时目录祖先所有权准入错误，未作为通过证据；没有放宽产品文件系统保护或据此修改无关代码。

全量候选解析完成 8,706 / 拒绝 7,472 / 异常 0；精简场景完成 5,345 / 拒绝 6,159 / 异常 0。各来源的 unique/场景数存在跨来源交叠，不能直接相加。场景代表统计的接受率 46.46% 与全量唯一文本 53.81% 使用不同抽样单位，不能直接当作退化/改进比较，也不是准确率。79 条 oracle 的当前基线通过，3 个注释语义错误仍报告 `semanticConformancePassed=false`，14 个语法缺口保留。本轮未修生产解析器、配置、锁或运行包。

最终私人集合位于 main `.cache/omp-command-history/20261006/scenarios.json.gz`，同目录保留 `parser-report.json`；目录 0700、文件 0600，均不纳入 git。替换验证后清理旧 main 和旧 worktree 的候选副本，以及本轮候选/中间场景导出；共清理 10 个旧副本/中间产物（33,794,532 字节）；原始日志从未写入或删除。新的[数值验收记录](../acceptance/omp-history-scenarios-20261006.json)区分二次检查、去重、存储和两种统计单位。

| 状态 | 本轮结果 |
|---|---|
| 完成 | 脱敏修复、重新提取、全量与代表二次检查、分类去重与压缩、受影响范围验证、最终代码审查、私有副本清理 |
| 进行中 | 无 |
| 失败待决策 | 无本轮交付阻塞；既有生产注释错误与语法缺口另行修复 |
| 环境不足未验证 | 全库回归环境准入未通过；远程 CI、真实 macOS/Windows、审批质量、真实宿主执行未验证 |

executor 实际为 gpt-6.1-sol / medium，scout 为 gpt-6-luna / high；executor 容量失败后由主代理接手最终验证。全程历史 Shell/JS 执行、宿主启动和模型请求均为 0。

## 2026-10-06 Phase 18：公开测试集与插件修复

用户进一步要求用集合修复插件，直到每个场景正确解析或明确安全拒绝，并将测试数据加入Git。
用户已确认：这不意味着所有动态脚本自动批准。开发分支 `fix/omp-shell-corpus`，基线 `54e37fa`。
前面Phase16/17的数字与缺陷记录是当时快照；本节为更新后的当前验收。

生产改动只在自有独立插件：修复三个注释错误，支持LF分隔/续行、参数glob、静态文件/fd重定向，
完整保留argv、连接符、glob位置、重定向顺序/操作符/两端描述符。原命令和参数不改写。
79个独立固定anchors现全部符合正确Shell词法预期：54支持、25明确保守边界；其中12个旧语法缺口
已扩展，heredoc与brace展开两个场景明确保守拒绝，不靠删除测试隐藏缺口。
`semanticConformancePassed=true`，不再容忍三个历史注释错误的错误结果。

原文hard deny在解析之前检查，换行不能躲过wildcard；解析失败时已知前缀在24KiB/256token上限内
只能加强deny，绝不批准部分分析。可见命令和每条重定向效果检查native规则；glob可能与同命令
deny参数相交时保守deny，与prompt相交时人工。代码选项/已识别wrapper、find执行型选项、awk/sed
执行形态及Shell状态/处理器脚本人工，无UI阻止。固定模式不是进程沙箱；没有命中固定deny的未知
脚本仍可由人明确授权。这不宣称分析了任意外部程序的全部间接行为。

凭据审核也补齐了命名字段/长选项、Basic/Bearer、URL userinfo、curl认证短选项（含粘连）、
字段名/值引号拼接及续行：原文和不求值的词法拼接视图共同防止向审批模型发送疑似凭据；人工
预览使用完整word span遮盖复杂值。新canary检查模型、backend及人工标题；普通`ls -u`不会被
当成curl认证参数隐藏。

### Git中的测试数据

文件位于 [`tests/fixtures/omp/command-scenarios/corpus.json.gz`](../../tests/fixtures/omp/command-scenarios/corpus.json.gz)，
**1,223,214字节，约1.17MiB**。它是固定词表和fixture数据重建的公开虚构版本，不是私有集合的
直接复制；不复制日志来源、账号/机器路径、provider、原始指纹或原参数值。
引用/转义、运算符、空值、glob位置、描述符及已知关键命令/选项保留；凭据信号规范化且值重建。
重建后相同文本再次合并31例：11,473个公开用例计入全部11,504个原场景，词汇闭包与已知身份
残留检查均0未知/残留。目录README解释schema、预期合同和复验方式。

每例`expected`由独立Python/shlex oracle生成，`expectedGate`指明固定fake配置下的模型/人工路径。
oracle不导入生产解析器；79条另行硬编码语义预期和高价值安全canary作为anchors。
两种有限语法实现的一致性不是完整POSIX/zsh/Brush语义证明；虚构数据重建也不是原始命令完整
语义等价保证。故原始私有集合另行逐条纯解析验证，不仅依赖公开版本：

| 集合/层 | 正确静态解析 | 明确拒绝/阻止 | 差异/异常 |
|---|---:|---:|---:|
| 原私有11,504例：完整argv/connector/glob/redirect预期 | 9,461 | 2,043 | 0 / 0 |
| 公开11,473例：独立词法预期 | 9,442 | 2,031 | 0 / 0 |
| 公开11,473例：fake native hook→review→delegate/headless | 9,430 | 2,043 | 0 |

12个公开例虽可静态解析，但含凭据信号，走人工边界而不发给模型。
fake native层逐例证明审查一次、委托一次及原参数/结果保持；被阻止者无模型/委托。
模型均返回固定虚构响应，Settings、API key与backend全是假对象；没有执行测试命令、启动宿主
或请求真实模型。这验证机制接线和声明词法合同，不证明真实风险模型对11,504例的正确率。

复验：

```sh
bun scripts/check-omp-shell-scenarios.ts
bun scripts/check-omp-command-history.ts
bun test ./tests/omp_shell_scenarios.test.ts ./tests/omp_command_history.test.ts \
  ./tests/omp_command_history_js.test.ts \
  ./agents/omp/packages/omp-permission-control/standalone.test.ts \
  ./agents/omp/packages/omp-permission-control/native-bash.test.ts
.venv/bin/python -m pytest tests/test_omp_command_history.py \
  tests/test_omp_history_scenarios.py tests/test_omp_public_corpus.py -q
```

最终受影响Python测试183pass；显式已有Babel Bun 166pass，默认无Babel 165pass/1明确skip；
固定pristine18.4.5 SDK严格tsgo退出0。官方普通锁离线读取固定已校验source/checksums刷新，资源、
plugin tree与公开fixture recipe闭包核验通过；官方版本/source/assets、退休patched记录及其它
agent锁不变。没有修改agent上游源码、重新编译宿主或本机部署。

依赖/kernel相关隔离Python104pass/7skip，7个skip来自退休的patched-host材料，不继续构建。
默认沙箱将根目录与/tmp的属主映射为nobody，导致两次同范围33fail/71pass/7skip；换临时路径
不能修复根属主。核对真实文件系统root属主为UID0后，在真实FS专用临时目录重跑通过，文件保护
原样保留。此前全库环境红灯不自动冒充全库通过，本次只验收受影响范围。
远程CI、其它实际OS、真实宿主Shell行为与真实模型审批质量未新增验证。

原私有压缩集合继续保存在原私有缓存，未加入Git；本轮临时oracle/中间导出验收后清理。
新的[机器可读验收](../acceptance/omp-shell-scenarios-20261006.json)只包含公开集合身份与聚合结果。
本机OMP需部署新的官方锁/插件资源后才能使用这些修复；本轮不触碰账号、会话或本机配置。

| 状态 | 本轮结果 |
|---|---|
| 完成 | 私有逐例预期、公开虚构集合、语法/保护修复、fake native逐例验收、隐私canary、锁刷新、稳定diff审查 |
| 进行中 | 无本轮实现任务 |
| 失败待决策 | 无本轮交付阻塞；初始失败已定位并修复或转为明确的环境诊断 |
| 环境不足未验证 | 远程CI、实际其它OS、真实宿主Shell语义、真实模型质量及日常机器部署；不计作通过 |

scout实际为gpt-6-luna/high；执行子代理受线程额度限制无法启动，实现/修复/最终验证由主代理完成。

## 2026-10-06：用户授权后的本机审查、同步与部署

针对已合入main的`18b89d5`做稳定版本审查，scout未发现阻止部署的回归。
公开11,473例重新检查差异/异常均0；受影响Bun测试71pass、0fail、12,171断言。
本阶段不重复执行历史命令，也没有启动真实宿主或请求模型。

确认日常`omp-kernel`没有活动实例、配置漂移或恢复待处理后，在物理实例锁和状态锁内制作
私有完整备份（179项、124个文件、0600），核验归档内容及备份期间来源未改变。
随后按官方可信锁完成`sync → plan → apply`，部署两项受管更新。
部署后`doctor`为`offline-ready`，依赖已安装、已部署运行包匹配当前锁，待变更0、漂移/冲突/恢复待处理均无。
官方18.4.5二进制SHA256与锁定资产一致，没有修改或重编译上游宿主。

120个应保留文件的字节与权限核验通过，账号、会话、所有权、本机机器配置均保留；原生配置
除受管扩展入口外保持一致。模式仍为smart，主审跟随会话、远程兜底仍已配置，执行模型和smol角色保留。
备份、私有文件路径与逐文件指纹只保存在机器私有目录，不加入Git。

以用户日常项目为启动目录，通过公开管理器`run`流程检查zsh/local-embedded启动准入，
启动操作替换为验证回调并排除SecretRef绑定；结果通过，但实际宿主启动数和模型请求数均0。
因此本节证明部署完整性及启动准入，不新增实际Cursor连通性或真实智能审批质量的通过证据。
聚合结果记录在[机器可读验收](../acceptance/omp-shell-scenarios-20261006.json)的`dailyDeployment20261006`。

| 状态 | 本阶段结果 |
|---|---|
| 完成 | 稳定版本审查、私有备份、同步、计划、部署、文件保留及启动准入核验 |
| 进行中 | 无 |
| 失败待决策 | 无 |
| 环境不足未验证 | 实际宿主启动、真实模型审批和Cursor连通性本阶段未测试；此前历史证据不替代本轮验证 |
