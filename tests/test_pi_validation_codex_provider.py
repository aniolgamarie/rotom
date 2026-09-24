"""Responses 流只处理合成模型，并要求原生工具结果再给出最终回复。"""
import json
import pytest
from agentcfg.pi_validation_codex_provider import CodexProvider


def frames(raw):
  return [json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith("data: ")]


def test_codex_stream_exercises_read_and_mutation_before_final():
  provider = CodexProvider()
  payload = {"model": "agentcfg-native-codex", "input": [], "tools": [{"name": "exec_command"}]}
  first = frames(provider.responses(payload))[-1]["response"]["output"][0]
  assert first["name"] == "exec_command" and json.loads(first["arguments"])["cmd"] == "/bin/cat code.txt"
  payload["input"].append({"type": "function_call_output", "call_id": "native-read", "output": "original\n"})
  second = frames(provider.responses(payload))[-1]["response"]["output"][0]
  assert second["call_id"] == "native-write"
  payload["input"].append({"type": "function_call_output", "call_id": "native-write", "output": "read-only filesystem"})
  last = frames(provider.responses(payload))[-1]["response"]["output"][0]
  assert last["type"] == "message"
  assert provider.snapshot()["requests"] == 3 and provider.snapshot()["native_read_observed"] is True


def test_codex_fixture_rejects_external_model_and_unobserved_read():
  provider = CodexProvider()
  with pytest.raises(ValueError): provider.responses({"model": "real-model", "input": []})
  with pytest.raises(ValueError):
    provider.responses({"model": "agentcfg-native-codex", "input": [
      {"type": "function_call_output", "call_id": "native-read", "output": "denied"},
      {"type": "function_call_output", "call_id": "native-write", "output": "denied"}]})
