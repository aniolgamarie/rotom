# 初始化回复窗口：root冻结候选

2026-10-07，root采纳下列proposal作为待独立复核的纯窗口候选；这里没有实施授权。唯一未来新增文件为 `src/agentcfg/pi_durable_init_channel.py` 和 `tests/test_pi_durable_init_channel.py`，前提是九类初始化codec的稳定实现先通过独立代码审查及root验收。原五消息4096B codec/window/guards不修改。

root裁决：采用无参数constructor及 `arm → bind → feed → consume`、任意状态幂等 `retire`，只读四property。任何错误永久retire；**retire在不完整/已消费/已失效时仍合法，不是错误**，下文state表优先于其中“consumes/retire-before-complete”的歧义文字。consume过早或重复才永久拒。无finish/end；实际actor观察EOF、取消、期限或中断发送后retire，不使用EOF补完整候选。

采用五种exact expected shape。slot必须先arm再原一次Popen/heldpidfd/birth绑定，再bind完整P，bind前禁止feed；slot_identity是child首次产物。acquired保存原完整reserved R及P，只精确匹配已知context/token/SID/公编码含LF的R摘要/E deployment和controller；epoch/storage/lock为完整新结果，必须由原actor另核物理来源/实际持有/持久回执。无None wildcard，不因合法metadata取得授权。offer全十字段echo；两末端ACK全文匹配。三权限property永远False。

raw frame为4+65536=65540B；65541仅用于拒尾部的观察上限，不是总Python内存限制。constructor/arm/bind/feed/consume及candidate getter检查有限原公开依赖身份；retire和三False不调用已漂移来源。确切export/别名表在稳定codec验收后由root implementation包逐项固定，不能要求不存在的名字或自动扫描全模块。P的小标量捕获沿accepted codec域，不调用私有helper、不制造OwnerRecord。异常均fresh固定Conflict且actual cause/context None；token不进repr/log/通用hash，引用丢弃不宣称内存完全擦除。

默认证据只验自有DTO/bytes和纯状态，无实际pipe/SDK/host/信号/账号。公构窗口、consume或True complete都不代完整本地send及原postpure/source/current/grant；actual actor的真实顺序及完整R/E跨帧关联继续独立pending。本候选不补source/principal/原oncegrant/初始化IO/Node/DB/native/product gate。formal7/100与严格计量前AUTO OFF保持。

以下原proposal完整保留。其固定Python仅报告用途已披露；首pins在初次旧源码摘读之后，首末一致不覆盖此前所有阅读时刻。候选待独立设计复核，不将root方案判断或proposal自审当独立通过。

# Pure InitReplyWindow proposal 01

Executor configuration: `gpt-6.1-sol/medium`; no sub-agents. This is a proposal for root decision, not implementation authorization. Only the two requested /tmp artifacts are written. No current init-codec implementation bytes were read.

## Scope and exact API

Future unique NEW files proposed: `src/agentcfg/pi_durable_init_channel.py` and `tests/test_pi_durable_init_channel.py`. Existing Node/owner five-message 4096B codecs/windows and tests remain unchanged. Public API is one exact class `InitReplyWindow` with constructor `InitReplyWindow()`, `arm(reply_type)`, `bind(expected)`, `feed(chunk)`, `consume()`, `retire()`, and read-only `has_complete_frame`, `writer_lock_verified`, `database_allowed`, `can_take_over`. All methods except consume return None; consume returns exactly one independently captured InitMessage. The last three properties are always False, including after errors/retirement. No callback, source validator, clock, fd, IO, grant or boolean receipt parameter exists.

The object uses slots, has no public mutable buffer/candidate/expected view, and inherits ordinary object repr (or one fixed secret-free class/state-only repr). Private token/frame-bearing captures are excluded from any repr/debug/exception surface. It does not generate or hash tokens or secret frames.

## Exact expected inputs to bind

`expected` must be exact native dict; unknown/missing keys and subclasses are rejected before hooks. It has exactly one of these shapes, type matching the armed reply:

| armed type | exact expected keys and domains |
|---|---|
| slot | `type='slot', controller=exact LinuxProcessIdentity` |
| offer-ack | `type='offer-ack', offer=exact InitMessage(type='offer')` |
| acquired | `type='acquired', context_id=H, token=T, service_id=H, reserved_registration=exact ServiceRegistration(stage='reserved'), controller=exact LinuxProcessIdentity` |
| registered-ack | `type='registered-ack', reply=exact InitMessage(type='registered-ack')` |
| release-ack | `type='release-ack', reply=exact InitMessage(type='release-ack')` |

No None wildcard is accepted. Missing/inactive/uninitialized nested DTO slots are rejected. Native class checks precede any attribute reads; nested records receive public encode/capture/decode validation and independent clone. InitMessage validation uses the future accepted public encode/decode API, not a raw dict/asdict/private helper. P uses a small bounded exact-scalar capture of the eight public LinuxProcessIdentity slots, matching candidate line24; it must not manufacture an OwnerRecord or expose a new process capability. Keys are exact strings <=32chars before hashing, expected shape arity <=6; H/T are bounded exact64 lowercase hex. Actor-supplied token is a format-checked correlation secret, not an authentication claim.

For offer-ack, bind captures the original offer independently and derives only its reply type; all 10 other fields must equal the expected offer. For registered/release ACK, bind captures the complete supplied reply, and matching compares every field/canonical native value. The actor remains responsible for constructing these expectation hashes/generation from saved original R/E captures; no reply hash alone replaces those captures.

For acquired, bind independently captures the full reserved R with public encode cap, requires expected service_id == R.service_id, records public SHA256(encode_service_registration(R), including LF), original controller P, R.initial_deployment_identity and original context/token. Complete decoded acquired must match type/context/token/service_id, computed reserved_registration_identity, E.deployment_identity == R.initial_deployment_identity and E.controller == original P. E must still be an entire public-captured/encoded acquired OwnerRecord with writer=None; it is never reduced to a permissive partial record. Its freshly generated epoch/storage_identity and reply lock_identity are explicit new producer results, not prelaunch expectation values. The actor retains complete returned E/lock S and must independently verify their actual source/OFD/persistent receipts. Slot similarly matches complete expected P plus codec fd=3/close_on_exec=True; slot_identity is fully captured but newly produced, not guessed in bind.

Root has confirmed this known-versus-new distinction. Exact API/shapes above remain a proposal requiring root acceptance.

## State machine and call order

States: NEW -> ARMED_UNBOUND -> BOUND_READING -> CANDIDATE -> CONSUMED. RETIRED is terminal and reachable from every state. New objects are never rearmed for later stages. arm accepts only exact str in slot/offer-ack/acquired/registered-ack/release-ack; request types and other replies reject.

| call | legal precondition | result |
|---|---|---|
| arm(type) | NEW | save only reply literal; ARMED_UNBOUND |
| bind(expected) | ARMED_UNBOUND, exactly once | validate and clone original metadata expectation; BOUND_READING |
| feed(bytes) | BOUND_READING | fragment accumulation; incomplete stays reading, one complete verified reply becomes CANDIDATE; always returns None |
| consume() | CANDIDATE, once | return independent original complete candidate; clear window refs and become CONSUMED |
| retire() | any state | erase private references/buffer and remain RETIRED; idempotent, no source required |

Every invalid arm/bind/feed/consume, including empty feed, consumes/retire-before-complete, repeated calls, wrong type or source drift permanently retires and raises a fresh fixed own Conflict. Wrong calls never preserve a candidate for later recovery. All operations other than retire and constant False properties reject after RETIRED. has_complete_frame returns False for NEW/unbound/reading/consumed/retired; it returns True only for CANDIDATE after pure dependency identity checks. It never returns candidate bytes or claims send/source approval. Source drift observed in that getter retires and returns False without invoking replacement code.

No finish/end method is proposed: these persistent init pipes do not use EOF as an ACK boundary. The actor reports observed EOF, cancellation, deadline or interrupted local-send by calling retire, even if a complete early candidate is buffered; it must not consume afterwards. A partial frame never succeeds on EOF. A finish marker would not prove absence of future tail and could conceal wrong late data. This differs deliberately from old OwnerReplyWindow.end and does not modify that old contract.

Slot order is mandatory: construct -> arm('slot') before original one-shot Popen -> original child/heldpidfd/birth binding -> bind complete original controller P -> only then read/feed bytes. arm needs no prelaunch P; bind/feed cannot be replaced with wire PID lookup. The pure class cannot prove Popen association; external actor must enforce this. For other replies, arm+bind happens before first send that could trigger that reply. read/feed may accumulate early ACK while send is partial/in-progress; feed returns no DTO. Only after the original complete local send receipt and original post-send source/context checks succeed may the actor call consume. Publicly calling consume early can return metadata, never IO/grant authority; actor tests must establish the real ordering. There is no `approved=True`, `send_complete=True` or fake receipt object in this API.

## Buffer and fragment bounds

Header4 announces payload1..65536, complete raw frame<=65540. The only extra byte allowance is tail detection: total raw input accepted into a window's observation attempt <=65541. Each chunk must be exact nonempty bytes and <=65541, and cumulative length is checked before copying. Before header completes, copy at most its missing bytes; check announced size immediately and reject 0/>65536 before any payload copy/decoder call. Then compare remaining input to outstanding payload size. Any tail byte in the same chunk or later chunk rejects permanently; tail bytes are not cached for the next window and need not be stored. After a full candidate, any further nonempty feed rejects before codec invocation. Huge/two-frame chunks reject before slicing/copying beyond the four-byte header or calling codec.

The private bytearray stores <=65540B and is cleared once decoded. Canonical expected/candidate copies, full R/E clones and temporary bytes have their own finite codec-derived caps; 65541 is raw stream accumulation, not a false claim that total Python memory including clones/input caller storage is only65541B. At decode at most one raw frame and its bounded native result exist; expected metadata is independently retained. After decode, canonical/native comparison tolerates permitted raw whitespace/order but does not normalize invalid scalar forms. No retained caller mutable structures/chunks, no arbitrary FIFO of frames. All decode/encode and expected record caps come from accepted pure codec contracts.

Consume can occur after any finite successful observed read batch; no no-data peek/finish/readable flag proves kernel/future tail absence. After consuming, actor keeps the old window object for rejecting deliberately routed late bytes; future new stage uses a new expected window and full actor protocol/phase checks. A delayed old type at new window rejects by type/full fields. The whole-session pump/window-routing and uniqueness of actual producer remain later actor obligations.

## Pure dependency identity and errors

Like old channel lines7-19, freeze selected own public class/functions at module initialization and check original aliases before/after each called public codec/record operation. Exact monitored list in the implementation package must include InitMessage/capture/encode/decode, their imported public registration/owner class/function aliases, and public ServiceRegistration/DirectoryIdentity/InitialBinding/OwnerRecord/LinuxProcessIdentity/StorageIdentity plus record capture/encode/decode exports used. This is local dependency-drift detection, not full installed-source/manager qualification. No replacement callable is invoked, and a restored alias cannot resurrect a retired window. Implementation must list every used public alias explicitly rather than accepting caller-supplied modules/functions. No private codec helper is called.

All errors are exact fresh Conflict('Durable初始化回复窗口无效'), actual __cause__/__context__ None, no foreign JSON/token/frame/field value or exception chain. The foreign exception is not modified. Retire discards expectation token/offer/frame/R/E/candidate references; it makes no Python-memory/traceback erasure claim. Retire and three False getters work even with drifted dependencies. No logs, callbacks or hash of token-containing frames.

## Cross-frame responsibility retained outside the window

Window enforces only its explicit expected subset/full reply plus the full single-message codec schema. External actor holds original full offer/reserved R/acquired E/P/S and exact public record bytes: original source/current/principal/oncegrant, reserved durable write before fresh, acquired actual persistence/OFD, registered R 11 immutable fields and storage match with E, index generation reserved+1 without wrap, full hashes including LF, index retire/quiescence/close before release, and source/policy/cancel/deadline/native checks. The window neither constructs R transitions nor grants Node/DB readiness. A valid acquired/ACK does not certify physical source or grant. Required candidate source/private-channel/index lines45,51-59,85-95/19-27/35-45 remain gates.

## Proposed acceptance package (not executed)

Only two future NEW files; root must accept proposal then freeze executor ownership. Proposed tests use own DTOs/bytes and existing temporary fixtures; no real IO/pipe/process/signal/SDK. Command after implementation authorization: `.venv/bin/python -m pytest tests/test_pi_durable_init_channel.py tests/test_pi_durable_init_message.py tests/test_pi_durable_owner_channel.py tests/test_pi_durable_owner_message.py tests/test_pi_durable_registration_record.py tests/test_pi_durable_owner_record.py` (actual repo runner/available test names to be confirmed in that package).

- State matrix: new/armed/bound/partial/candidate/consumed/retired, every wrong order permanently closes; idempotent retire, no rearm/double bind/consume, properties read-only/False and secret-free repr.
- Five replies positive, slot arm with no P then bind required before feed; original P complete match and newly returned S; acquired full reserved R/P known links, newly generated epoch/S/lock accepted only as full bounded metadata. One mutation per expected linked field rejects, wrong reply/request rejects, no wildcard or reduced record.
- Full offer echo field equality; complete registered/release ACK field equality, original record digest including LF. Actor retains original R/E; fixture proving valid metadata still threeFalse.
- Single-byte/header/payload split boundaries, raw whitespace/key ordering, full65536 payload with legal whitespace, invalid0/65537 header, cumulative65541 and >cap, twoframes/same-chunk one-tail byte/late-byte, malformed/deep/duplicate/incomplete/empty bytes, EOF/cancel modeled by retire. Reject pre-header/overlong/tail before original decoder hook.
- Early candidate feed returns None; external own fake sequence records local-send/postpure success before consume. Interrupted send/source check calls retire and loses candidate. This checks caller algorithm ordering only, never real send/grant.
- Exact native checks/hooks0 including byte/dict/str/int/DTO subclasses, hostile key/property, inactive fields and uninitialized slots; original caller slot mutation after bind cannot change stored expected; returned DTO independent of caller.
- Every frozen alias drift before constructor/arm/bind/feed/candidate consume/getter; before/after actual original codec call drift; no replacement invoked, no restore resurrection. Own fixed error/cause/context/token repr and foreign-error preservation, cancellation drops private references without erasure claim.

## Pins and execution limits

Five stable selected inputs have identical first/last SHA256+bytes in companion JSON. The first explicit pin call followed the initial bounded old-channel excerpts; therefore those pins establish the subsequent report interval, not an atomic no-change guarantee during earlier reads. No current init codec file was read, avoiding concurrent writer output as evidence. Fixed `/usr/bin/python3.11 -I -S -B` was used solely for authorized own pins/report generation; this executed Python for report work, not subject-runtime qualification. No product imports/tests/host/Node/SDK/pipe/signal/network/account action; no repo writes or evidence deletions. Reports O_EXCL0600. Pending root decisions: accept exact API/expectation keys, omission of finish, local alias list and two-NEW-file plan. STOP.
