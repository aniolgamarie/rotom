# 历史 Quickstart：宿主补丁方案（已停止扩展）

本文件只保存宪章第 VI 项生效前的命令与交付身份，不是当前操作指南。不得据此继续构建发布补丁宿主。当前入口见[独立插件指南](quickstart.md)。

本指南是实现与验收入口。当前 Phase 11 正式运行包身份如下；历史宿主和真实模型质量使用各自原始runtime，不沿用旧结果冒充新资产通过。

| 身份 | 本轮实际值 |
|---|---|
| official recipe | `60d399dd4b0a2f2265d117d17b9e566669b64ca1413d4dc0fac66487165b9521` |
| plugin tree | `4511e7cdb9efb312029acfff93f0f6fe73cc5c3c018325c25756f9fd7eea040d` |
| 0001 patch | `45a0fcbdd4092161cbc3c14ac8b40a323928cd4dc915538e2cbee7f6ead8e51f` |
| 0002 patch | `c34d02d19941e09ca507e67164f5b8d37a67e991b6ed96ab51dca2b67ece33da` |
| standalone SHA-256 | `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86` |
| standalone size | 367318216 bytes |
| patched manifest | `dce490890453ccff4165ece76a460fb9cbf23756cdb553c3fd7fe8d72bbb815e` |
| build receipt | `f0716c84316192f349253d68247ba4bcfc455f41218816efe79675952df4a0ac` |
| combined runtime | `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2` |

## 1. 前置材料与隔离边界

开始验证前先确认仓库中的配置契约、输入锁、补丁 series、插件树、正式 variant manifest 与上表身份一致。默认测试只使用仓库和临时 HOME/XDG/OMP/cache，阻断网络并替换子进程、provider、worker、原生 shell 和 UI 边界；它不启动第三方宿主、不执行样本命令，也不读取日常账号库或凭据。需要真实宿主、真实 provider、日常 profile 部署或付费请求时，使用对应的独立授权与验收记录，不能用 fake transport 或无账号 smoke 代替。

日常 `sync`、`plan` 和 `apply` 只消费已经构建并锁定的运行包，不编译源码、不隐式安装 Bun/依赖、不下载 tiny，也不启动 OMP。`run` 前的管理器检查只证明入口、字节、receipt、ABI 声明和身份匹配；插件实际注册、bridge 健康和模型 transport 状态只能在宿主启动后由 `/permission-control status` 确认。

## 2. 配置与审查顺序

最小 profile 选择 `omp-permission-control`、`runtime_variant="permission-control-v1"` 和 `default_mode="smart"`。`permission_control` 是封闭对象；未知字段、未选择或不能唯一解析的模型引用均失败，不静默修复。完整选择示例见[配置契约](contracts/configuration.md)。

审查顺序固定如下：

1. 显式 `reviewer_model` 始终作为主审；只有省略它时，才在每次审查开始时冻结当前 session 执行模型作为主审。
2. 显式 `remote_fallback_model` 只在主审超时、服务失败、输出无效、transport 不支持或不可用时接替同一完整审查；有效 allow/ask/deny、取消和同一实际 provider/model 不进入远程复审。
3. 显式 `fallback_model="local/lfm2.5-230m"` 是最后的 installed-only tiny。它不下载模型，只能给 ask/deny，不能自动 allow；缺少已安装资源时保持 unavailable。
4. `manual` 不调用上述模型链。硬禁止、原生命令 prompt/critical、未知效果和固定风险下限先于模型，不能由任何 fallback 翻案。

`omp-kernel` 保留 session 主审，显式选择远程 GLM 备用和本地 tiny。status 必须分别显示配置主审、远程备用、本地 tiny 的身份、来源与健康状态；最终审计记录实际调用层，不能把备用模型显示成原主审。

## 3. 会话命令

插件只提供四条完整命令：

- `/permission-control status`：只读显示当前模式、bridge/identity、配置主审、远程备用、tiny、覆盖范围、健康状态和未验证范围；不得探测网络或刷新凭据。
- `/permission-control smart`：仅对当前会话启用智能审查，后续请求重新判定，不复用旧许可。
- `/permission-control manual`：仅对当前会话停止模型审查；确定性低风险规则仍可生效，其余请求走人工或在无 UI 时阻止。
- `/permission-control explain`：只读显示最近决定的短原因、来源和许可状态，不输出密钥、整段对话或原始环境。

不支持 `guard`、`approval` 等别名。模式切换、取消、模型/策略/配置或执行上下文变化会撤销未消费许可。

## 4. 冻结样本与评测协议

冻结集位于 `tests/fixtures/omp/permission-control/`，固定为 240 条：100 条 policy-safe、100 条 ask/deny 风险样本和 40 条故障/状态序列。tree digest `4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6` 仅按既定顺序覆盖 `fixture-schema.json`、`cases.jsonl`、`labels.json` 的相对路径与文件字节；不包含 `FROZEN.md`、原生 baseline 或后续 runtime fixture。规则实现后不得删除、重标或补录样本来覆盖已见结果。

runner 必须先验证 schema、冻结 digest 和输入来源，再从样本动作、事件、用户消息及结构化限制构造模拟上下文。`expected`、分类、理由和证据期望只能在决定产生后用于比较与统计，不能喂给 fake 或真实 reviewer。默认 fake 主审固定保守 ask，只验证协议、状态机、超时与失败关闭；没有观察到的事件记为 unverified/null，不能冒充真实宿主或模型质量。真实模型模式必须显式选择已授权的单次 review service、provider/model/transport，不重试、不执行样本命令，也不把 fixture 的模拟 host proof 宣称为真实证明。

第 6 节保留的模型结果属于其记录的历史 runtime 和冻结范围。冻结文件保持不变不代表新 runtime、远程 GLM、tiny、其它平台或冻结集外质量已经复测。

## 5. 离线构建、锁与身份链

维护者先在独立目录准备并逐字节核验上游源码归档、锁定 Bun、完整依赖归档和产物 cache。准备这些 cache 可能需要显式网络步骤，但 build 本身必须离线；实际入口和全部必需参数为：

```sh
.venv/bin/python agents/omp/build-permission-control.py \
  --build-inputs-lock agents/omp/patches/permission-control/build-inputs.lock.json \
  --source /prepared/commit.tar.gz \
  --tool-cache /prepared/tools \
  --dependency-cache /prepared/dependencies \
  --artifact-cache /private/permission-artifacts \
  --platform linux-x64 \
  --offline
```

`--source` 是锁定 commit 的原始归档；`--tool-cache` 按 lock 中的相对 cache key 提供精确 Bun 字节；`--dependency-cache` 提供 lock 列出的完整依赖 artifacts；`--artifact-cache` 接收内容寻址 standalone 和 `build-receipt.json`。构建器核对 source archive、`bun.lock`、工具版本/摘要、依赖闭包、patch series、构建脚本与插件树，在网络受阻的临时环境编译，但不启动产物。输入锁只引用原始上游、工具和依赖，不引用 official recipe identity、receipt 或输出，因此不存在摘要循环。

构建后使用同一私人 artifact cache 发布独立 variant manifest：

```sh
./agentcfg lock --agent omp \
  --runtime-variant permission-control-v1 \
  --artifact-cache /private/permission-artifacts
```

该步骤交叉核对 receipt、实际资产、输入锁、patch、构建脚本、插件树、ABI 和 official identity。正式链依次绑定 official recipe、plugin tree、两份 patch、standalone 内容、patched manifest、receipt 和 combined runtime。任何受锁 recipe/package/resource、插件、patch 或构建脚本字节变化，都必须重新构建并按顺序刷新 receipt、patched manifest 与 combined identity；日常 `sync` 不执行这条构建链。


### 本机启用步骤（本轮 cache/sync/plan/apply 已完成，仅待 run）

`sync`不会搜索`/tmp`中的构建产物。本轮已将当前 Phase 11 资产准备到下列日常 cache，并完成 sync、plan 与 apply；用户已退出原 OMP，下一步可直接 run。其它机器或需要重新准备时，先将已验证资产放入
`omp-kernel` 当前 profile 的私人内容寻址 cache。以下命令使用当前实际 local、profile 和 cache；若
目标已经存在，只接受同一普通文件、长度和 SHA-256，不覆盖异常字节或符号链接：

```sh
set -euo pipefail

artifact_sha=0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86
source_artifact=/tmp/rotom-omp-permission-artifacts-remote-20260930/sha256/0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86
artifact_dir=/home/weixiaoxian.wxx/.cache/agentcfg/omp/omp-kernel/artifacts/sha256
target_artifact="$artifact_dir/$artifact_sha"

test -f "$source_artifact"
test ! -L "$source_artifact"
test "$(stat -c %s "$source_artifact")" -eq 367318216
printf '%s  %s\n' "$artifact_sha" "$source_artifact" | sha256sum -c -
install -d -m 700 "${artifact_dir%/sha256}" "$artifact_dir"

if test -e "$target_artifact" || test -L "$target_artifact"; then
  test -f "$target_artifact"
  test ! -L "$target_artifact"
  test "$(stat -c %s "$target_artifact")" -eq 367318216
  printf '%s  %s\n' "$artifact_sha" "$target_artifact" | sha256sum -c -
  chmod 600 "$target_artifact"
else
  staged_artifact="$(mktemp "$artifact_dir/.permission-control.XXXXXX")"
  trap 'rm -f "$staged_artifact"' EXIT
  install -m 600 "$source_artifact" "$staged_artifact"
  test "$(stat -c %s "$staged_artifact")" -eq 367318216
  printf '%s  %s\n' "$artifact_sha" "$staged_artifact" | sha256sum -c -
  ln "$staged_artifact" "$target_artifact"
  rm -f "$staged_artifact"
  trap - EXIT
fi

./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel sync
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel plan
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel apply
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel run
```

上列完整命令用于复现或恢复。本轮实际 `plan` 退出 0，报告 3 项变更、冲突 0、漂移 0；`apply` 退出 0 并部署同一 3 项变更。随后 `doctor --format json` 退出 0，状态为 `offline-ready`，`changes_pending=0`，当前依赖与已部署依赖均为 `installed`，`deployed_runtime_matches_current=true`，`live=false`，`recovery_pending=false`。cache 与 sync 也已完成；未启动新的 OMP，未新增模型请求。

启动后仅使用 `/permission-control status`、`/permission-control smart`、
`/permission-control manual` 和 `/permission-control explain`。当前配置与运行包已经部署，用户接下来只需执行上列 `run`；本轮没有代替用户启动日常实例。

## 6. 真实宿主 smoke 与模型评测（分别获得授权后）

当前 Phase 11 combined runtime `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2` 已在 Linux glibc x64 隔离环境完成固定 provider 链：主审返回一次 503，远程 Anthropic transport 给出完整审批，permit 消费后 `pwd` 恰执行一次；primary 1、remote 1、tiny 0、human 0，外部模型请求 0。固定 loopback 响应只验证真实 standalone 的远程接替、证据与执行链，不证明真实 GLM 审查质量。

正式 patched standalone 已构建并通过离线身份验证。T072 已在 combined runtime `bf6f18b45fc80c177f6644e96366b978bb3d524b0d476664d228e4a7de48bc08` 的隔离实例完成真实 native warm、真实 TUI new/resume、missing-plugin 启动前失败关闭、rollback，以及固定响应 provider 驱动的无 UI 自动许可链。最后一轮记录 `primary_calls=1`、tiny 0、permit pending→consumed、一个 tool result、`pwd` 恰执行一次、explain allow/consumed、status 无 pending、退出 0；外部请求为 0。固定 provider 即使使用生产模型公开 ID 也只是本地脚本，不是实际 reviewer。默认测试仍不启动宿主；本次授权内的复测可继续，扩展至其它日常实例或额外付费模型另行授权。应使用独立临时机器配置和实例以及明确 `--local`、`--profile`，只有明确授权部署到日常实例时才改变目标。

```sh
./agentcfg --local "${OMP_SMOKE_LOCAL:?set isolated reviewed local config}" --profile omp-kernel sync
./agentcfg --local "${OMP_SMOKE_LOCAL:?set isolated reviewed local config}" --profile omp-kernel plan
./agentcfg --local "${OMP_SMOKE_LOCAL:?set isolated reviewed local config}" --profile omp-kernel apply
./agentcfg --local "${OMP_SMOKE_LOCAL:?set isolated reviewed local config}" --profile omp-kernel run
```

先执行 `/permission-control status` 核对实际 bridge/model/coverage，再测试 manual、smart、explain、新建/恢复，以及插件未加载时的保护。运行中使用隔离临时目录的无害动作，核对一条已允许动作没有重复 prompt；不为演示执行实际危险命令。无账号 smoke 只证明加载/界面/故障路径。

T073/T080 的独立模型调用已完成。冻结 240 条中 safe 99/100 免问、risk 0/100 危险 allow、fault 0/40 allow；原始 78 条主审为 safe 60（59 allow、1 ask）与 risk 18（16 valid deny、2 格式错误转 ask）。四条 supplemental 为 3/4 符合预期、0 条危险 allow；总计 82 个最终模型响应中 79 valid、3 invalid，失效输出均转人工。102/102 请求额度由历史 20、最终原始 78 与最终 supplemental 4 用尽，relay 已停止，不再发送模型请求。harness 只发送冻结脱敏样本并记录决定，不实际执行待审命令；Kimi exact model 的 permission review 专用请求关闭思考，普通主模型设置不变。该结果只证明冻结范围内 SC-001/SC-002，不表示全部 12 项 SC、冻结集外质量或真实 tiny 推理通过；日常本机配置未修改。

## 7. 结果登记

| 状态 | 使用方式 |
|---|---|
| 完成 | 附实际命令、环境、结果与范围；文档完成不等于运行验证完成 |
| 进行中 | 已开始但还未得到完整结果 |
| 失败待决策 | 违反关键不变量、同一故障经有效修复仍失败，交主代理裁决；不放宽保护凑通过 |
| 环境不足未验证 | 实际发现缺Bun/资产/账号/平台等；列缺项和受影响组，其它组可继续 |

尚未尝试的宿主或模型步骤单独记“尚未执行”，不能假定环境不足，也不能标通过。限定范围 T072 与 T080 Linux x64 隔离宿主、材料化回归和冻结样本评测已完成；真实 tiny 推理、其它平台及冻结集外质量仍未验证，独立 scout 全量语义审计已完成。当前实施与实际验收状态见 [验收记录](../../docs/acceptance/omp-permission-control.md)、[宿主 smoke 报告](../../docs/acceptance/omp-permission-control-host-smoke.md)、[模型评测报告](../../docs/acceptance/omp-permission-control-model-evaluation.md)及[机器可读结果](../../docs/acceptance/omp-permission-control-model-results.json)，本指南中的步骤不能代替执行证据。
