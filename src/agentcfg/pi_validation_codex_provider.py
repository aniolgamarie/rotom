"""官方 Codex Responses 流的合成模型；命令内容固定，绝不连接真实服务。"""
import json
import shlex
from pathlib import Path

from .pi_validation_provider import ScriptedProvider


class CodexProvider(ScriptedProvider):
  def __init__(self, *, write=False, denied_paths=(), maximum_requests=8):
    super().__init__(["agentcfg-native-codex"], maximum_requests=maximum_requests)
    self.write = write
    self.read_observed = False
    self.mutation_result_observed = False
    self.native_write_denied = False
    if any(not Path(path).is_absolute() or "\0" in path for path in denied_paths): raise ValueError("native-codex-private-path")
    self.denied_paths = tuple(denied_paths)
    self.privacy_denial_observed = False

  def responses(self, payload):
    if payload.get("model") not in self.models or not isinstance(payload.get("input"), list): raise ValueError("native-codex-model")
    with self.mutex:
      self.counts[payload["model"]] += 1
      number = sum(self.counts.values())
      if number > self.maximum: raise ValueError("native-codex-limit")
      self.events.append({"model": payload["model"], "request": number})
    outputs = {row.get("call_id"): row.get("output") for row in payload["input"] if isinstance(row, dict) and row.get("type") == "function_call_output"}
    if "native-read" in outputs:
      self.read_observed = "original" in str(outputs["native-read"])
    if "native-write" in outputs:
      self.mutation_result_observed = True
      output = str(outputs["native-write"]).lower()
      self.native_write_denied = any(message in output for message in ("read-only file system", "read-only filesystem", "permission denied", "operation not permitted"))
    if "native-private" in outputs:
      output = str(outputs["native-private"])
      self.privacy_denial_observed = ("synthetic-native-key" not in output
        and any(message in output.lower() for message in ("permission denied", "no such file or directory", "operation not permitted")))
    tools = {row.get("name"): row for row in payload.get("tools", []) if isinstance(row, dict)}
    if "native-read" not in outputs:
      call_id, command = "native-read", "/bin/cat code.txt"
    elif self.denied_paths and "native-private" not in outputs:
      call_id, command = "native-private", "/bin/cat " + " ".join(shlex.quote(path) for path in self.denied_paths)
    elif "native-write" not in outputs:
      call_id, command = "native-write", "printf 'changed\\n' > code.txt"
    else: call_id, command = None, None
    if call_id:
      if "exec_command" in tools:
        name, arguments = "exec_command", {"cmd": command, "shell": "/bin/sh", "login": False, "yield_time_ms": 1000, "max_output_tokens": 1000}
      elif "shell" in tools:
        name, arguments = "shell", {"command": ["/bin/sh", "-c", command], "timeout_ms": 10000}
      else: raise ValueError("native-codex-shell-tool-missing")
      item = {"type": "function_call", "id": "item-" + call_id, "call_id": call_id, "name": name, "arguments": json.dumps(arguments), "status": "completed"}
    else:
      if (not self.read_observed or not self.mutation_result_observed or not self.write and not self.native_write_denied
          or self.denied_paths and not self.privacy_denial_observed): raise ValueError("native-codex-tool-evidence")
      item = {"type": "message", "id": "native-final", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "Synthetic Codex native validation complete.", "annotations": []}]}
    response = {"id": "native-response-" + str(number), "object": "response", "created_at": 1, "model": payload["model"],
      "status": "completed", "output": [item], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    frames = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
      {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress"}},
      {"type": "response.output_item.done", "output_index": 0, "item": item}, {"type": "response.completed", "response": response}]
    return "".join("event: " + row["type"] + "\ndata: " + json.dumps(row, separators=(",", ":")) + "\n\n" for row in frames).encode()

  def snapshot(self):
    return {**super().snapshot(), "native_read_observed": self.read_observed, "native_mutation_result_observed": self.mutation_result_observed,
      "privacy_denial_observed": self.privacy_denial_observed, "native_write_denied": self.native_write_denied}
