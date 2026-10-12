# Controller Python 发行来源的信任起点

2026-10-08 root已接受的发行信任标准，接续 `durable-controller-python-source.md`。稳定候选4531B/97417275…的独立有限审查0P1/P2；root 18输入receipt `b2cda77711f6f7ce39adcd79823afe84b7199dfb8f8fb80a4c4ac07f65ed284a`。本稿明确发行来源的准入标准，不生成运行资格、启动controller或修改系统；旧取证与其当时的未验证结论保留。

## 采用官方分发的HTTPS信任起点

Linux首版沿用本机manager实际解释器安装。发行来源采用通常的发行商仓库信任模型：通过经证书验证的官方HTTPS文档确认发行商公开的仓库及签名key分发入口，固定从该入口取得的原key字节、指纹及时间，再验证相应RPM的完整签名和摘要。可信起点是受控本机及其TLS证书验证、官方文档域名和文档明确指定的发行入口；不是key自称的UID、RPM数据库、搜索命中或签名校验自身。

[Alibaba Cloud Linux官方文档](https://www.alibabacloud.com/help/en/alinux/getting-started/use-alibaba-cloud-linux-3-images-in-an-on-premises-environment)于2026-05-27更新，明确为Alinux 3的仓库启用 `gpgcheck`，并指定 `https://mirrors.aliyun.com/alinux/$releasever/RPM-GPG-KEY-ALINUX-3`。本机对应releasever为3。该官方声明提供发行分发授权关系；它没有刊载指纹，不称它是独立指纹证明。

同一个发行商的HTTPS分发与其签名key不是两条独立供应链。协议不声称能抵御同时控制上述官方域名、合法TLS身份和发行发布权限的攻击者，也不把已有受控操作系统和证书库的来源证明无限递归为新任务。后续如有独立指纹公告可以补强证据，但单独缺少第二份指纹公告不构成此路线必须失败的条件。这澄清的是工程信任标准，没有降低用户明确选择的发送前严格token上限。

## 本次材料与验收边界

已保存的 `controller-python-rpm-static-signature-source-review01/041-report.json` 和原采集器记录对固定HTTPS入口的无认证、无环境代理、无重定向读取，默认SSL证书验证及精确返回URL检查。取得的key为1670字节，SHA256 `b8f79e10cf214927dbc88787e92069e5f032c292f8c3d93c4b9c69026ff90eab`。已有show-only记录识别指纹 `B3F615E8A095461F089CC3E853FE0598CAC33616`；两份固定 `python3.11` 与 `python3.11-libs` RPM在独占临时数据库中对该key的签名和摘要校验成功。上述材料的原字节、工具结果和失败历史不重跑、不覆盖。

每次接受前均须核采集代码、实际成功报告、保存字节和官方文档之间的对应关系。本次root已按下文实际记录接受 `vendor_https_bootstrap` 发行来源事实；仅增加新文档或字段名不等于事实已接受。记录必须分别保留 `publisher_distribution_authority`、`signature_valid_under_pinned_key` 和 `independent_fingerprint_publication`；最后一项当前仍未证实，不能把前两项改写成独立信任证明。

此项接受只覆盖这些固定包的发行授权和签名，不能替代已安装完整字节与文件集合、递归loader与stdlib/extension来源、实际manager映射、原受管startup/接收validator、固定Full角色、持续来源持有，以及实际pidfd/信号/pipe行为。系统和自有源码的改变使旧资格stale；被核文件仍不是atomic exec或跨运行连续hold。签名通过也不证明可重现构建或每条加载路径已被观察。

## 更新与实现约束

key或官方分发授权关系改变时，重新进行显式来源审查；不能按当前key URL的同名新正文自动替换旧指纹，不能通过旧记录许可未知的新签名人。新发行包、Python patch、loader配置或平台变更分别触发受影响来源与行为重验，不自动接受旧资格。

后续资格producer只接受实际原manager来源与固定本机安装的材料，不接受client给出的路径、key、URL或 `verified` 布尔值。信任说明属于本地私有来源记录，不能赋予公开DTO、JSON或摘要创建DB/Node的权限。完整qualification接口仍由完整来源包冻结；本稿不授权新发行物安装、正式锁或产品部署。

有限审查需核：官方文档确切入口、原TLS/URL采集代码与成功记录、固定key/签名之间的对应；旧unknown不被追溯伪造成独立证明；无credential和secret摘要；更新不隐式信任；所有完整运行来源/Full/行为gate继续关闭。当前Base候选解析已经实际通过，许可安装门仍单独未通过；正式7/100、产品gate未通过、严格计量前AUTO OFF保持。

root实际观察 `/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/timeout --signal=TERM --kill-after=2s 65s /usr/bin/python3.11 -I -S -B .cache/pi-two-profiles/run-20261004/proxy-license-primary-http-preparation-review01/collector.py`，session14047/exit0。2026-10-07T16:45:24.757645Z至16:45:27.593892Z三GET完成，官方key原1670B/b8f79e…全bytes相等。此argv来自root真实tool调用，不从result.json反推；历史SSL CA环境未单列仍unknown。root接受 `publisher_distribution_authority=vendor_https_bootstrap` 与先前相同key的RPM签名事实，独立指纹公告仍未证实。只消除人为要求第二份指纹公告的发行阻塞项，其余完整来源、Full、过程行为和产品gate不变。

2026-10-08（本地）同一Alinux3官方分发入口和原1670B／b8f79…key起点已应用到21份固定system-library RPM，root receipt `a1b6b4ec91d681145c98170dd31f8b87089d4cc49f47c99d3f740bebfc426560`。全部Header V3／V3 RSA/SHA256与摘要验证成功，35个已接受inventory字节身份匹配signed file records。此处分别接受发行授权、固定key签名和历史字节对应；独立指纹公告仍未证实，目标当前文件未在此阶段重hash，完整运行／manager／sourcehold／Full仍未资格。先前“仅两份Python RPM”和Base安装未通过描述的是其当时记录，后续Base detached install01已另接受，不把本验签当成安装或产品passed。
