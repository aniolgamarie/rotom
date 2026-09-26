# 示例：带 Context Artifact 的 Investigate 委托

## 场景

Pi 调查了一个 Neovim bug：用户选择的 AI provider 在重启后被重置为默认值。Pi 已确认状态文件包含正确的 provider，排除了 JSON 解码失败，但现有测试不覆盖完整启动顺序。Pi 委托 Codex 做根因分析。

## 生成的 Prompt File

````text
Mode: investigate
Working directory: /path/to/project
Scope: lua/ai/init.lua, lua/ai/state.lua, lua/ai/providers.lua, tests/ai/state_spec.lua
Task: Identify the root cause of the selected AI provider being reset during Neovim startup.
Acceptance criteria:
- Distinguish verified facts from hypotheses.
- Cite repository file and line evidence.
- Explain the relevant startup sequence.
- Recommend the smallest deterministic regression test.
- Do not implement a fix.

Context artifact (pi-agent-context/v1):
```json
{
  "schema": "pi-agent-context/v1",
  "artifact_id": "ctx-provider-reset-01",
  "generated_at": "2026-07-20T10:15:00+08:00",
  "task": {
    "delegation_id": "provider-reset",
    "turn": 1,
    "mode": "investigate",
    "objective": "Find why restored provider selection is reset on startup",
    "user_intent": "Preserve explicit provider selection across restarts",
    "requested_output": "Root cause, evidence, sequence, and regression-test design",
    "non_goals": ["Modify files", "Change provider storage format"]
  },
  "scope": {
    "cwd": "/path/to/project",
    "include": [
      "lua/ai/init.lua",
      "lua/ai/state.lua",
      "lua/ai/providers.lua",
      "tests/ai/state_spec.lua"
    ],
    "exclude": ["lua/commit_picker/", "plugin dependency updates"],
    "write_policy": "read-only"
  },
  "conversation": {
    "decisions": [{
      "id": "dec-1",
      "summary": "An explicit saved provider must override the configured default",
      "source": "user",
      "observed_at": "2026-07-20T09:50:00+08:00"
    }],
    "constraints": [
      "Retain backward compatibility with existing state files",
      "Unavailable saved providers may fall back, but valid providers must persist"
    ],
    "open_questions": ["Does registration or setup overwrite restored state?"],
    "intent_changes": [
      "The user initially requested diagnosis of lost state; persistence format is now known valid"
    ]
  },
  "investigation": {
    "facts": [{
      "id": "fact-1",
      "claim": "The external state file contains the selected provider before restart",
      "evidence": ["tool:state-check"],
      "observed_at": "2026-07-20T10:02:00+08:00"
    }],
    "hypotheses": [
      {
        "id": "hyp-1",
        "claim": "Initialization order overwrites restored selection with a default",
        "status": "open",
        "basis": ["fact-1", "repo:ai-init", "repo:state"],
        "reason": null
      },
      {
        "id": "hyp-2",
        "claim": "State JSON cannot be decoded",
        "status": "eliminated",
        "basis": ["tool:decode-check"],
        "reason": "The focused decoder returned the saved provider correctly"
      }
    ],
    "attempts": [{
      "action": "Ran tests/ai/state_spec.lua",
      "outcome": "Passed; tests exercise state functions but not complete setup ordering",
      "evidence": ["tool:state-spec"]
    }]
  },
  "workspace": {
    "vcs": {
      "repo_root": "/path/to/project",
      "branch": "fix/provider-state",
      "head": "8b712f1",
      "base": "main",
      "dirty": true,
      "changed_paths": ["tests/ai/state_spec.lua"]
    },
    "state_notes": [
      "The dirty test change belongs to the user; do not modify or discard it"
    ],
    "diagnostics": [{
      "tool": "LuaLS",
      "target": "lua/ai/state.lua",
      "summary": "No diagnostics",
      "observed_at": "2026-07-20T10:08:00+08:00",
      "evidence": []
    }]
  },
  "references": [
    {
      "id": "repo:ai-init",
      "kind": "repo_range",
      "locator": "lua/ai/init.lua",
      "range": "1-80",
      "availability": "cwd",
      "summary": "AI setup sequence"
    },
    {
      "id": "repo:state",
      "kind": "repo_range",
      "locator": "lua/ai/state.lua",
      "range": "1-120",
      "availability": "cwd",
      "summary": "State loading and selection updates"
    },
    {
      "id": "tool:state-check",
      "kind": "tool_result",
      "locator": "Pi state inspection",
      "range": null,
      "availability": "unavailable",
      "summary": "Saved provider field was present and valid"
    },
    {
      "id": "tool:decode-check",
      "kind": "tool_result",
      "locator": "Pi focused decoder check",
      "range": null,
      "availability": "unavailable",
      "summary": "Exit 0; provider field decoded correctly"
    },
    {
      "id": "tool:state-spec",
      "kind": "tool_result",
      "locator": "tests/ai/state_spec.lua",
      "range": null,
      "availability": "cwd",
      "summary": "Focused state suite passed"
    }
  ],
  "freshness": {
    "captured_at": "2026-07-20T10:15:00+08:00",
    "head_at_capture": "8b712f1",
    "invalidates_on": [
      "HEAD change",
      "change to an included file",
      "new contradictory startup trace"
    ],
    "warnings": []
  },
  "budget": {
    "max_tokens": 1800,
    "approximate_tokens": 990,
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
- Do not modify files or delegate further.
- Do not expose private reasoning or paste complete files/raw diffs.
- Keep the final response under 4 KiB.

Progress:
- After each semantic milestone, emit exactly one single-line checkpoint beginning
  with CODEX_PROGRESS: and state the outcome and next phase.
- Do not put secrets, code, diffs, or multiline content in checkpoints.

Output:
- status and concise summary
- ranked findings with file/line evidence
- verification performed
- unresolved risks
- optional pi-agent-feedback/v1 JSON block
````

## 要点

- **user_intent** 不只是字面请求，而是用户真正想达成的结果
- **facts** 有 tool 证据支撑；**hypotheses** 是 Pi 的推断，标注了状态
- **eliminated 假设** 保留了 basis 和 reason，防止 Codex 重复已排除的路径
- **references** 用 pointer-first，不粘贴完整文件
- **freshness** 绑定 HEAD，让 Codex 知道上下文何时可能过期
- **workspace.state_notes** 警告 dirty changes 属于用户
