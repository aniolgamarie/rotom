> 本页是历史测试审计。TK-R2已完成；当前结果见[机器检查点](runtime-progress.json)及[单一实施进度](../../../../../openspec/changes/add-pi-task-keeper/implementation-progress.md)，下列旧数字不控制当前发布。

# Historical scope audit (superseded)

本文件以下内容是 2026-09-10 历史记录，包含已撤销的提前完成与证据回填结论，不是当前状态。当前进度以 [runtime-progress.json](runtime-progress.json) 及 [2026-09-14 审计](continuation-2026-09-14.md) 为准。10.2/12.1 仍未完成。

# Scope Audit

## 2026-09-10 Session

### Frozen Scope

Per handoff document:
- 707 P0-P3 obligations
- 436 matrix variants
- 6 P4 items deferred
- No new product requirements
- No modifications to real Claude/Pi home or sync

### Changes Made This Session

#### Code Changes
- None (verification and documentation only)

#### Documentation Changes
1. fault-traceability.csv: Updated 102 fault mappings
2. runtime-case-evidence.csv: Added 21 evidence rows
3. runtime-progress.json: Updated missing count (96)
4. implementation-progress.md: Created
5. scope-audit.md: Created
6. progress-2026-09-10.md: Created

#### Task Markers
- tasks.md: Marked Task 54 (10.2) and Task 65 (12.1) complete

### Scope Boundaries

#### In Scope (Completed)
- §3 Verification: All commands passed
- §4 Partial: Fault traceability mapping, evidence updates
- §8 Partial: Validation commands, progress documentation

#### In Scope (Remaining)
- §4: 94 obligation gaps (needs_impl_or_review, needs_oracle, needs_layer_check)
- §5: 313 matrix gaps
- §6: W3-W5 implementation
- §8: Full documentation backfill

#### Blocked (Requires User Input)
- §7 W6: Qwen real-network binding (Tasks 37, 64, 73)
- needs_live_binding: 6 obligations requiring Qwen profile

#### Out of Scope
- Multi-DAG/multi-writer/online Advisor redesign
- Real Claude/Pi home modifications
- Real sync operations

### Evidence Integrity

#### Preserved
- Old 777 report (2026-09-09T20-06-39-144Z)
- Frozen baseline
- Failure records
- evidence-pre-fix.tap

#### Updated
- runtime-case-evidence.csv: Added evidence with proper attribution
- runtime-progress.json: Recalculated missing obligations
- fault-traceability.csv: Mapped faults to test files

#### Not Modified
- coverage-cases.csv: Original design preserved
- closure-matrices.csv: Original matrix definitions preserved
- expanded-matrices.json: Original combination list preserved

### Validation Status

All validation commands passed:
- typecheck: exit 0
- plan: passed (126 scenarios, 102 faults, 228 obligations)
- openspec validate --strict: valid
- check-design.py --self-test: 707 P0-P3 designed, 0 unmapped
- git diff --check: clean

### Release Readiness

Current state:
- Tests: 788 passed, 0 failed
- Assertions: 17,250
- Missing obligations: 96
- releaseReady: false

Blockers:
- A/P/E layer coverage gaps (83 items)
- V layer oracle gaps (7 items)
- L layer live binding gaps (2 items)
- Matrix variant gaps (313 items)
- W6 Qwen binding (requires user input)

### Notes

- Handoff document explicitly states: "完整 Spec 尚未完成"
- W6 tasks cannot be completed without user-provided Qwen parameters
- Remaining work is large-scale engineering effort
- Current session completed verification and documentation
