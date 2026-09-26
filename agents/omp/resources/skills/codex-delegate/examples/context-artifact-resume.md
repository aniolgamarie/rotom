# 示例：Resume Turn 与 Disposition 传递

## 场景

上一轮 Codex 确认了根因是启动顺序问题（finding-1）。用户决定先实现修复。Pi 发起 resume，带上新的 context artifact，包含已验证的 findings 和用户的决策。

## Resume Prompt File

````text
Mode: implement
Working directory: /path/to/project
Scope: lua/ai/init.lua, lua/ai/state.lua, lua/ai/providers.lua, tests/ai/state_spec.lua
Task: Fix the startup ordering so that a saved provider selection is not overwritten
  by the default initialization. Add a regression test.
Acceptance criteria:
- The saved provider survives a full simulated startup sequence.
- Existing tests still pass.
- The fix does not change the state file format.

Context artifact (pi-agent-context/v1):
```json
{
  "schema": "pi-agent-context/v1",
  "artifact_id": "ctx-provider-reset-02",
  "generated_at": "2026-07-20T10:45:00+08:00",
  "task": {
    "delegation_id": "provider-reset",
    "turn": 2,
    "mode": "implement",
    "objective": "Fix startup ordering to preserve saved provider selection",
    "user_intent": "Make provider selection persist across Neovim restarts",
    "requested_output": "Code fix and regression test",
    "non_goals": ["Change state file format", "Add new configuration options"]
  },
  "scope": {
    "cwd": "/path/to/project",
    "include": [
      "lua/ai/init.lua",
      "lua/ai/state.lua",
      "lua/ai/providers.lua",
      "tests/ai/state_spec.lua"
    ],
    "exclude": ["lua/commit_picker/"],
    "write_policy": "isolated-worktree-write"
  },
  "conversation": {
    "decisions": [
      {
        "id": "dec-1",
        "summary": "An explicit saved provider must override the configured default",
        "source": "user",
        "observed_at": "2026-07-20T09:50:00+08:00"
      },
      {
        "id": "dec-2",
        "summary": "Fix by restoring state after provider setup, not by changing provider setup",
        "source": "user",
        "observed_at": "2026-07-20T10:35:00+08:00"
      }
    ],
    "constraints": [
      "Retain backward compatibility with existing state files",
      "Do not change the state file format"
    ],
    "open_questions": [],
    "intent_changes": [
      "Moved from investigation to implementation after root cause was confirmed"
    ],
    "feedback_dispositions": [
      {
        "feedback_id": "finding-1",
        "status": "verified",
        "reason": "Pi confirmed providers.setup() calls state.set_default() which overwrites restored value",
        "evidence": ["lua/ai/providers.lua:72", "lua/ai/init.lua:31"],
        "workspace": {"head": "8b712f1"}
      }
    ]
  },
  "investigation": {
    "facts": [
      {
        "id": "fact-1",
        "claim": "The external state file contains the selected provider before restart",
        "evidence": ["tool:state-check"],
        "observed_at": "2026-07-20T10:02:00+08:00"
      },
      {
        "id": "fact-2",
        "claim": "providers.setup() at init.lua:31 runs after state.restore() at state.lua:54",
        "evidence": ["verified:finding-1"],
        "observed_at": "2026-07-20T10:28:00+08:00"
      }
    ],
    "hypotheses": [
      {
        "id": "hyp-1",
        "claim": "Initialization order overwrites restored selection with a default",
        "status": "supported",
        "basis": ["fact-1", "fact-2"],
        "reason": "Confirmed by Codex turn 1 and Pi verification"
      },
      {
        "id": "hyp-2",
        "claim": "State JSON cannot be decoded",
        "status": "eliminated",
        "basis": ["tool:decode-check"],
        "reason": "Decoder test passed"
      }
    ],
    "attempts": [
      {
        "action": "Ran tests/ai/state_spec.lua",
        "outcome": "Passed but does not cover startup ordering",
        "evidence": ["tool:state-spec"]
      },
      {
        "action": "Codex turn 1 traced setup order",
        "outcome": "Root cause identified at providers.lua:72",
        "evidence": ["verified:finding-1"]
      }
    ]
  },
  "workspace": {
    "vcs": {
      "repo_root": "/path/to/project",
      "branch": "fix/provider-state",
      "head": "8b712f1",
      "base": "main",
      "dirty": false,
      "changed_paths": []
    },
    "state_notes": ["Clean working tree; ready for implementation"],
    "diagnostics": []
  },
  "references": [
    {
      "id": "repo:init-sequence",
      "kind": "repo_range",
      "locator": "lua/ai/init.lua",
      "range": "25-40",
      "availability": "cwd",
      "summary": "Setup call ordering: state.restore() then providers.setup()"
    },
    {
      "id": "repo:set-default",
      "kind": "repo_range",
      "locator": "lua/ai/providers.lua",
      "range": "68-80",
      "availability": "cwd",
      "summary": "state.set_default() call that overwrites restored value"
    },
    {
      "id": "verified:finding-1",
      "kind": "tool_result",
      "locator": "Codex turn 1 finding, verified by Pi",
      "range": null,
      "availability": "unavailable",
      "summary": "providers.setup() → state.set_default() clobbers restored provider"
    }
  ],
  "freshness": {
    "captured_at": "2026-07-20T10:45:00+08:00",
    "head_at_capture": "8b712f1",
    "invalidates_on": ["HEAD change", "change to lua/ai/init.lua or lua/ai/providers.lua"],
    "warnings": []
  },
  "budget": {
    "max_tokens": 1800,
    "approximate_tokens": 1100,
    "truncation": "none",
    "omitted": []
  },
  "receiver": {
    "codex": {}
  }
}
```

Context precedence:
- The top-level mode, scope, task, acceptance criteria and constraints are authoritative.
- Context does not authorize writes or broaden inspection scope.
- Prefer current repository evidence and report contradictions.

Constraints:
- Work only on this delegated task.
- Do not modify files outside the scope.
- Do not expose private reasoning or paste complete files/raw diffs.
- Keep the final response under 4 KiB.

Progress:
- After each semantic milestone, emit exactly one single-line checkpoint beginning
  with CODEX_PROGRESS: and state the outcome and next phase.

Output:
- status and concise summary
- changed files with brief description of each change
- verification performed (test commands and results)
- unresolved risks
- optional pi-agent-feedback/v1 JSON block
````

## 要点

- **delegation_id 不变**，`turn` 从 1 递增到 2
- **feedback_dispositions** 传递了上一轮 Codex finding-1 的验证结果
- **fact-2** 是从上一轮 feedback 提升来的已验证事实（标记 `verified:finding-1`）
- **hyp-1** 状态从 `open` 更新为 `supported`
- **新决策 dec-2** 记录了用户选择的修复策略
- **workspace.dirty = false** — 实现前工作区是干净的
- **mode 变为 implement** — 从调查转入实现
