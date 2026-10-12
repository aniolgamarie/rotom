# Modern npm 依赖定向覆盖

当前 Base 固定图已能由官方 npm 11.19.1 重新解析，但 `proxy-agent-negotiate@1.1.0` 没有已证实的版本绑定许可正文，安装门仍拒绝。当前拟选方案是在自有根项目使用 npm 公开 `overrides`，将 Pi AI 1.0.2 的两个代理依赖从官方 9.1.0 定向选为官方 9.0.0；Pi AI、宿主和代理库的发布字节均不修改。

两个 9.0.0 的官方 metadata、SRI/SHA1 匹配的原 tgz 和包内 LICENSE 已抓取。二者依赖 `agent-base@9.0.0` 与 `debug@^4.3.4`，不依赖 Negotiate。固定 Pi AI 的 Bedrock 调用点仅使用公开类的一参数构造器，静态签名兼容。此证据还不代表实际 npm 解析、安装、SDK 组合或网络代理行为通过。旧 9.1.0 图、候选及 unresolved 历史保留。

## 声明与边界

仅 modern profile 可声明可选 `npm_dependency_overrides`，而且必须同时有已审查的 `npm_resolution_seed`。该字段直接使用 npm 的有限两层公开形状，例如：

```json
{
  "@earendil-works/pi-ai@1.0.2": {
    "http-proxy-agent@9.1.0": "9.0.0",
    "https-proxy-agent@9.1.0": "9.0.0"
  }
}
```

父选择器必须精确等于本 profile 已选 npm source 的 `package@version`；子选择器必须是同包的 `package@精确版本`，替代值只能是精确 SemVer 字符串。拒绝范围、别名、URL、file/git、`$` 引用、嵌套对象、`.` 自覆盖、未知类型、空对象、超限和直接所选依赖替换。最多 16 个父、合计 32 个子；包名最多 214 字符、版本最多 128 字符。支持规范 SemVer 的 prerelease/build 字段，core 与 prerelease 的纯数字组件不接受前导零，build 组件按规范允许前导零。它是自有构建输入，不加入 published manifest 或 runtime 权限接口。

使用版本限定子选择器，因为 npm 的嵌套覆盖包含父的后代；普通不带版本的 `https-proxy-agent` 会误覆盖 Pi AI 后代 gaxios 当前使用的 7.0.6。实际解析必须证明 7.0.6 与原图其他身份保持。公开说明见 [npm package.json overrides](https://docs.npmjs.com/cli/v11/configuring-npm/package-json/#overrides)；文档当前版本不是固定工具 11.19.1 的实际行为证据。

校验复用只在 producer 按需导入的 `pi_npm_seed.py`，不增通用插件框架或上游补丁。所有无该字段的 modern 和 legacy 路径保留。modern 非法覆盖在 TemporaryDirectory、checked 或发布前给固定 `ConfigError("pi-build-dependency-overrides-invalid")`，退出码 2，清除 cause/context，不携带输入正文。legacy 继续由原未知字段门拒绝。

解析器只在已有 seeded 分支把已校验映射放入自有根 package.json 的 `overrides`。原 npm lock-only 命令、ignore-scripts、SRI 补齐、seed 全图九身份比较、完整 license 与 readback 门保持。不会用新字段绕过 seed，也不会自动更新锁或放宽 unresolved。构造器静态兼容不是权限或沙箱资格。

## 分步实施与验收

先做默认代码包：唯一 executor 可写 `src/agentcfg/pi_npm_seed.py`、`src/agentcfg/pi_vendor.py`、新 `tests/test_pi_npm_dependency_overrides.py`。暂不修改当前声明、seed、许可证或正式锁。默认正/负控制验证精确映射写入原 stage、版本选择器保留、缺 seed/非法输入零 checked、旧 manifest 保持、输出不暴露构建字段、九身份漂移仍拒绝及 legacy/无字段原行为；临时 HOME、断网、fake subprocess，禁止真实 Node/npm/SDK。旧 seed suite 与已受影响的 generator selectors 仅在代码稳定后跑一次。

然后在私有临时开发项目使用固定官方 Node/npm，复制原实际四个自有归档和 canonical seed，添加以上自有根覆盖，运行原 lock-only 命令生成候选新图。审查全图差量、原本地 URI/SRI、直接依赖、所有不相关节点和 nested gaxios 7.0.6；只有意图内变化才可更新自有 seed/声明及新的 profile 专用 REGISTRY。两个 9.0.0 使用实际 tgz 内 LICENSE 与 package.json 摘要，来源另存固定 provenance，旧历史 registry 不覆盖。出现额外图变化时交 root 决定，不自动接受。

新材料接入后重做受影响默认数据验证、完整源码采集和原 PiBackend 候选解析/read_lock，随后准备实际安装/SDK/代理组合验收。正常开发依赖解析由长期实施授权覆盖；新增真实 SDK/宿主 smoke 按 AGENTS.md 在材料可审查后独立询问用户。既有 native 授权已闭合，不复用为新组合。Full/解释器/sourcehold/产品门及 strict input_tokens 下 AUTO OFF 继续单独验收。

2026-10-08（本地）三个默认 target 已 STOP 后接受，85 输入 root receipt `3c74789f265422bee1b1db6a2dcc0b1b8cc84ad6ff875cba217921fd4d1ca4d7`。Root 读完整 helper/test 和 vendor 有限真实 delta，独立有限审查 0P1/P2。正控原1fail→new01一次77pass，affected01另次64pass，均零skip；不同轮不相加为一次验证。只接受默认构建入口，不签实际 SDK 或安装。

固定 Node/npm 的开发 lock-only 已实际生成新完整图，12 输入 root receipt `8ff6e1458eb91b30c8c27758bdbc337797e482f418b1bab27447d5938dc5dcd2`。执行02为 2026-10-07T17:19:08.698475Z–17:19:11.417981Z、outer与三个tool exit0，版本stdout为 v24.14.0/11.19.1。新 raw lock 72,246B，SHA256 `d30083ff2d5c081ed799c06b66dbe899671f5847d9cab4d93a2876e536a11d61`。原root/top头部和全部148共同raw记录相同，删top两个9.1及Negotiate，新两9.0在PiAI私有node_modules；远程图145，其中143不相关身份/正文记录保留，gaxios的7.0.6及四local相同。两新节点URL/SRI与已抓取原tgz metadata相同。未产生node_modules，临时根已删除，npm1943字节和Node/旧seed首末匹配；不是sourcehold或SDK验证。

首次执行01的 npm 命令也 exit0，但开发采集器使用含atime的whole stat比较，未保留完整新锁，outer1/status unknown；11输入失败 receipt `7ede68b226bc4cd592ece9236680dd6416307fee681085b152033e207b32422d` 保留。受控合成文件证实只atime会变化而其它stat稳定；只改比较/新输出execution02后重新实际执行，不把二次成功外推第一次完整图。

Root 已按实际新图和官方包材料准备 profile 专用 `REGISTRY-pi-base.json`、`PROXY-PARENTS-SOURCE.json` 与原bytes新seed，8输入冻结 receipt `84ae38b6861bbd623f35ba7a1750634e1f978fc97f8de658c664a200bfbc6e5c`。旧 global REGISTRY 和 source records 保留，不改上游。唯一writer的五文件接线正在进行；仅可适配旧actual材料test从本profile声明选唯一registry，不能把当前9.0/145或历史cache写成永久升级障碍。新声明仍candidate，原PiBackend/read_lock及installed license门另验。

五文件接线已 STOP 后接受，66 输入 root receipt `752c8850dcc171feff2c39818ebf03b9057e9999fc8f6b0d85f1e30037eb351a`，默认两个实际材料 selectors 一次2pass/零skip，独立有限0P1/P2。三个材料与预备字节全同，root自行逆回全部原声明和原test；旧全局 registry/来源和此前已接受helper/vendor等保持。zero active unresolved仍仅新图材料事实，没有签installed gate或SDK。

新完整源码已实际采集/冻结，8 输入 receipt `1a3d745594d7d8512d2947e51f3e4c7d0869c3a1dab1e3c2b7d552a003851190`：2,206 files、231 dirs、48,645,711B，首后完整hash/bytes/执行位及目录端点/六资产/Node核对；对旧8a9来源只6项预期改变/新增、零移除，唯一缺可选 `agents/pi/profiles` 仍明确，不漏runtime source。collector只有OUT literal改变且整字节可逆。后续执行器允许适配receipt path/hash、2206count和新inventory suffix；目录仍231，原producer完整字节/行为、工具布局、WNOWAIT/结束保存清理及600s保持。此处只准备下一原候选解析，不据静态源码pins签sourcehold或产品。

2026-10-08（本地）execution05 原候选解析已执行并接受，38输入 root receipt `7a31bff152192cd72a4a1d404653126ed7359eb4f1108316cf4af071a5abbfa1`。实际 UTC 2026-10-07T17:47:37.806281Z–17:47:47.740486Z、9.934205s、session84684、UID/EUID1002/GID100、inner/wrapper0；原 PiBackend.resolve_lock→read_lock 返回唯一 schema2/pi-base/candidate identity `2f99a9e46a4eff58d917a15a49063515d14510aa12203bbcfb023b125b763b3d`。原 captured/retained package831B/6e9c9b…与lock72246B/d30083…分别全bytes相同，lock等于新seed；145远程节点九身份字段有序匹配新profile registry，无unresolved记录，gaxios HTTPS7.0.6保持。Root独立核canonical manifest/slice/resource/pair身份，executor有限核20输出条目（13regular/7dirs）、2212完整复制记录及35原module来源记录；原副本已清理，不声称重开模块或持续hold。最低观测空间1,090,895,872B，groupempty/TMPabsent，保存先于清理；成功checked内部stdout与Node内部spawn仍未观察。原validator/readback真实运行，但installed许可检查尚未执行，正式manifest仍absent，Full/来源/角色/产品未签，AUTO OFF。01–04历史按原事实保留，不重复resolver/validator/pytest。

原 PiBackend.sync/_sync 在创建stage前都拒candidate，现有API不能直接安装candidate而不激活。Root决定后续独立开发安装子步骤：固定锁对/本地归档布局、官方Node/npm及临时HOME运行 npm ci --ignore-scripts --no-audit --no-fund，再由原copy runtime_files和installed-license validator核实际解包材料；不调用sync/_sync，不seal/activate/status/current，也不把开发结果升级为正式runtime资格。新的SDK/host组合仍须材料准备完后独立授权。当前仅脚本准备，未实际安装。

2026-10-08（本地）install01 独立开发安装已执行并接受，37输入 root receipt `3749a2962388ee5236231b47196537b023b1dd871beb8fff1782ec8575f2feb2`。session15143、UTC 18:35:25.499171–18:35:44.214203、18.715032s、UID/EUID1002/GID100、producer/wrapper0；raw版本确认为 Node v24.14.0／npm11.19.1。npm ci exit0并报告added124packages；原 source allow_unresolved=False 与 installed-license validator 均真正运行，registry145行检查通过，无source unresolved。固定pair保持831B／6e9c9b…与72246B／d30083…，binding仍candidate，public install_files107完成。只读保存树16653条（15184regular／1460目录／9contained relative .bin链接）、124615286 regular字节经独立scout逐项全SHA/type/member集核对无差异；2212源／资产复制记录与34原module来源记录匹配冻结。原副本已清理，module核对不冒称重开；首个比较器字段误用的13假不匹配输出保留，修正比较结果零差异。

本次采用env -i且无proxy继承，raw日志仅有deprecated与npm update notice，不据notice升级工具。最小观测空间1004605440B，自有组empty、保存先于TMP清理、源脚本首末pin相同。没有sync/_sync/seal/activate/current、SDK/agent或正式manifest发布，未取得sourcehold／运行包／Full／产品资格。后续当前保存闭包的SDK6另准备实际runner与授权，旧SDK6授权已闭合；bwrap --new-session使外层groupempty不能证明namespace全部后代退出，因此新work在成功/失败都保留为私密证据，不自动回收。
