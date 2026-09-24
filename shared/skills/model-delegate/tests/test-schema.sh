#!/usr/bin/env bash
# model-delegate: schema 验证测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SCHEMA_DIR="$ROOT_DIR/schemas"

pass=0
fail=0

# 检查 jq 是否可用
if ! command -v jq &>/dev/null; then
  echo "FAIL: jq not found" >&2
  exit 1
fi

# 简单的 JSON schema 验证（基于 jq，仅检查必填字段和类型）
# 注意：这不是完整的 JSON Schema 验证器，只覆盖核心约束
validate_receipt() {
  local json="$1"
  jq -e '
    # 检查必填字段
    has("schemaVersion") and has("runId") and has("runDir") and has("status") and
    has("terminal") and has("timestamp") and has("backend") and has("cwd") and has("completion") and
    # 检查类型
    (.schemaVersion | type == "string") and
    (.runId | type == "string") and
    (.runDir | type == "string") and
    (.status | type == "string") and (.status | IN("completed", "failed", "cancelled", "timeout", "idle_timeout", "incomplete")) and
    (.terminal | type == "boolean") and (.terminal == true) and
    (.timestamp | type == "string") and
    (.backend | type == "object") and
    (.backend | has("id") and has("provider") and has("model") and has("resumeToken")) and
    (.backend | keys | all(IN("id", "provider", "model", "resumeToken"))) and
    (.cwd | type == "string") and
    (.completion | type == "object") and
    (.completion | has("status") and has("failure_mode") and has("resume_token") and has("resumable") and has("final_text") and has("feedback_quality") and has("usage") and has("has_agent_end")) and
    (.completion | keys | all(IN("status", "failure_mode", "resume_token", "resumable", "final_text", "feedback_quality", "usage", "has_agent_end"))) and
    (.completion.status | IN("completed", "failed", "cancelled", "incomplete")) and
    (.completion.failure_mode | IN("", "auth", "network", "invalid_input", "protocol", "invalid_output", "cancelled")) and
    (.completion.feedback_quality | IN("structured", "none")) and
    (.completion.has_agent_end | type == "boolean") and
    # 检查顶层额外字段（允许 resumedFrom）
    (keys | all(IN("schemaVersion", "runId", "runDir", "status", "terminal", "timestamp", "backend", "cwd", "completion", "resumedFrom")))
  ' <<< "$json" 2>/dev/null
}

validate_event() {
  local json="$1"
  jq -e '
    # 检查必填字段
    has("schemaVersion") and has("seq") and has("runId") and has("timestamp") and
    has("kind") and has("phase") and has("summary") and has("reportable") and
    # 检查类型
    (.schemaVersion | type == "string") and (.schemaVersion == "1") and
    (.seq | type == "number") and (.seq >= 1) and
    (.runId | type == "string") and
    (.timestamp | type == "string") and
    (.kind | type == "string") and (.kind | IN("started", "activity", "phase_changed", "terminal")) and
    (.phase | type == "string") and (.phase | IN("starting", "working", "finalizing")) and
    (.summary | type == "string") and (.summary | length <= 500) and
    (.reportable | type == "boolean") and
    # 检查额外字段
    (keys | all(IN("schemaVersion", "seq", "runId", "timestamp", "kind", "phase", "summary", "reportable")))
  ' <<< "$json" 2>/dev/null
}

# 测试 1: 合法的 receipt
valid_receipt='{"schemaVersion":"1","runId":"run-20260101-120000-00001","runDir":"/tmp/test","status":"completed","terminal":true,"timestamp":"2026-01-01T12:00:00Z","backend":{"id":"pi","provider":"bailian","model":"glm-5","resumeToken":"abc123"},"cwd":"/tmp","completion":{"status":"completed","failure_mode":"","resume_token":"abc123","resumable":true,"final_text":"Hello","feedback_quality":"structured","usage":{"input":100,"output":50,"totalTokens":150},"has_agent_end":true}}'
if validate_receipt "$valid_receipt"; then
  pass=$((pass+1))
else
  echo "FAIL: valid receipt rejected" >&2
  fail=$((fail+1))
fi

# 测试 2: receipt 缺少必填字段
invalid_receipt='{"schemaVersion":"1","runId":"run-20260101-120000-00001"}'
if validate_receipt "$invalid_receipt"; then
  echo "FAIL: invalid receipt accepted (missing fields)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 3: receipt status 值非法
invalid_receipt='{"schemaVersion":"1","runId":"run-20260101-120000-00001","runDir":"/tmp/test","status":"invalid_status","terminal":true,"timestamp":"2026-01-01T12:00:00Z","backend":{"id":"pi","provider":"bailian","model":"glm-5","resumeToken":""},"cwd":"/tmp","completion":{"status":"completed","failure_mode":"","resume_token":"","resumable":false,"final_text":"","feedback_quality":"none","usage":{},"has_agent_end":false}}'
if validate_receipt "$invalid_receipt"; then
  echo "FAIL: invalid receipt accepted (bad status)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 4: receipt completion.failure_mode 值非法
invalid_receipt='{"schemaVersion":"1","runId":"run-20260101-120000-00001","runDir":"/tmp/test","status":"failed","terminal":true,"timestamp":"2026-01-01T12:00:00Z","backend":{"id":"pi","provider":"bailian","model":"glm-5","resumeToken":""},"cwd":"/tmp","completion":{"status":"failed","failure_mode":"unknown_mode","resume_token":"","resumable":false,"final_text":"","feedback_quality":"none","usage":{},"has_agent_end":false}}'
if validate_receipt "$invalid_receipt"; then
  echo "FAIL: invalid receipt accepted (bad failure_mode)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 5: receipt 有额外字段
invalid_receipt='{"schemaVersion":"1","runId":"run-20260101-120000-00001","runDir":"/tmp/test","status":"completed","terminal":true,"timestamp":"2026-01-01T12:00:00Z","backend":{"id":"pi","provider":"bailian","model":"glm-5","resumeToken":""},"cwd":"/tmp","completion":{"status":"completed","failure_mode":"","resume_token":"","resumable":false,"final_text":"","feedback_quality":"none","usage":{},"has_agent_end":false},"extraField":"not allowed"}'
if validate_receipt "$invalid_receipt"; then
  echo "FAIL: invalid receipt accepted (extra field)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 6: 合法的 event
valid_event='{"schemaVersion":"1","seq":1,"runId":"run-20260101-120000-00001","timestamp":"2026-01-01T12:00:00Z","kind":"started","phase":"starting","summary":"Run started","reportable":true}'
if validate_event "$valid_event"; then
  pass=$((pass+1))
else
  echo "FAIL: valid event rejected" >&2
  fail=$((fail+1))
fi

# 测试 7: event 缺少必填字段
invalid_event='{"schemaVersion":"1","seq":1}'
if validate_event "$invalid_event"; then
  echo "FAIL: invalid event accepted (missing fields)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 8: event seq 必须 >= 1
invalid_event='{"schemaVersion":"1","seq":0,"runId":"run-20260101-120000-00001","timestamp":"2026-01-01T12:00:00Z","kind":"started","phase":"starting","summary":"Run started","reportable":true}'
if validate_event "$invalid_event"; then
  echo "FAIL: invalid event accepted (seq < 1)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 9: event kind 值非法
invalid_event='{"schemaVersion":"1","seq":1,"runId":"run-20260101-120000-00001","timestamp":"2026-01-01T12:00:00Z","kind":"unknown_kind","phase":"starting","summary":"Run started","reportable":true}'
if validate_event "$invalid_event"; then
  echo "FAIL: invalid event accepted (bad kind)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 10: event summary 超过 500 字符
long_summary=$(printf 'x%.0s' {1..501})
invalid_event="{\"schemaVersion\":\"1\",\"seq\":1,\"runId\":\"run-20260101-120000-00001\",\"timestamp\":\"2026-01-01T12:00:00Z\",\"kind\":\"started\",\"phase\":\"starting\",\"summary\":\"$long_summary\",\"reportable\":true}"
if validate_event "$invalid_event"; then
  echo "FAIL: invalid event accepted (summary too long)" >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 11: schema 文件存在
if [[ -f "$SCHEMA_DIR/receipt-v1.json" && -f "$SCHEMA_DIR/event-v1.json" ]]; then
  pass=$((pass+1))
else
  echo "FAIL: schema files missing" >&2
  fail=$((fail+1))
fi

# 测试 12: schema 文件是合法 JSON
if jq empty "$SCHEMA_DIR/receipt-v1.json" 2>/dev/null && jq empty "$SCHEMA_DIR/event-v1.json" 2>/dev/null; then
  pass=$((pass+1))
else
  echo "FAIL: schema files are not valid JSON" >&2
  fail=$((fail+1))
fi

printf '\n== schema tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
