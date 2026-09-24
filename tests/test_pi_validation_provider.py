"""本地模型夹具的协议逻辑；不启动监听器，不调用外部模型。"""
import json
import pytest
from agentcfg.pi_validation_provider import ScriptedProvider, streaming_body


def test_synthetic_provider_requires_selected_model_and_never_claims_a_real_account():
  provider = ScriptedProvider(["agentcfg-native-reader"], maximum_requests=1)
  assert provider.response({"model": "real-provider"})[0] == 404
  status, result, _ = provider.response({"model": "agentcfg-native-reader", "messages": []})
  assert status == 200 and result["model"] == "agentcfg-native-reader"
  frames = streaming_body(result).decode()
  assert frames.endswith("data: [DONE]\n\n") and '"total_tokens":2' in frames
  assert provider.response({"model": "agentcfg-native-reader"})[0] == 429
  assert provider.snapshot()["requests"] == 2


def test_review_fixture_reads_code_and_artifacts_before_submitting_snapshot_bound_result():
  provider = ScriptedProvider(["agentcfg-native-reviewer"])
  request = {"model": "agentcfg-native-reviewer", "messages": [{"role": "user", "content": "Evidence: artifact:one, artifact:two"}],
    "tools": [{"type": "function", "function": {"name": "tk_read", "parameters": {}}},
      {"type": "function", "function": {"name": "structured_output", "parameters": {"properties": {"snapshot": {"const": "fixture-snapshot"}}}}}]}
  paths = []
  for _ in range(3):
    _, result, _ = provider.response(request)
    message = result["choices"][0]["message"]
    call = message["tool_calls"][0]
    assert call["function"]["name"] == "tk_read"
    paths.append(json.loads(call["function"]["arguments"])["path"])
    request["messages"] += [message, {"role": "tool", "tool_call_id": call["id"], "content": "synthetic delivered content"}]
  assert paths == ["code.txt", "artifact:one", "artifact:two"]
  _, result, _ = provider.response(request)
  function = result["choices"][0]["message"]["tool_calls"][0]["function"]
  assert function["name"] == "structured_output"
  assert json.loads(function["arguments"])["snapshot"] == "fixture-snapshot"


def test_quota_and_missing_result_are_explicit_native_fault_inputs():
  quota = ScriptedProvider(["agentcfg-native-reader"], scenario="quota")
  request = {"model": "agentcfg-native-reader", "messages": []}
  assert quota.response(request)[0] == 429 and quota.response(request)[0] == 200
  missing = ScriptedProvider(["agentcfg-native-reader"], scenario="missing-final")
  assert missing.response(request)[1]["choices"][0]["message"]["content"] == ""
  with pytest.raises(ValueError): ScriptedProvider(["real-account-model"])


def test_denial_fixture_targets_the_existing_private_config_instead_of_an_absent_file():
  provider = ScriptedProvider(["agentcfg-native-main"], scenario="deny-path", denied_path="/fixture/local.toml")
  payload = {"model": "agentcfg-native-main", "tools": [{"function": {"name": "read"}}], "messages": []}
  _, result, _ = provider.response(payload)
  call = result["choices"][0]["message"]["tool_calls"][0]
  assert json.loads(call["function"]["arguments"]) == {"path": "/fixture/local.toml"}


def test_review_evidence_list_of_bare_ids_is_read_before_the_verdict():
  identity = "artifact-" + "a" * 64
  provider = ScriptedProvider(["agentcfg-native-reviewer"])
  payload = {"model": "agentcfg-native-reviewer", "messages": [{"role": "user", "content": "Read tk_read artifact:<id>. Evidence: " + identity}],
    "tools": [{"function": {"name": "tk_read"}}, {"function": {"name": "structured_output", "parameters": {"properties": {"snapshot": {"const": "fixture"}}}}}]}
  for expected in ("code.txt", "artifact:" + identity):
    _, result, _ = provider.response(payload)
    message = result["choices"][0]["message"]
    call = message["tool_calls"][0]
    assert call["function"]["name"] == "tk_read" and json.loads(call["function"]["arguments"])["path"] == expected
    payload["messages"].append(message)
  _, result, _ = provider.response(payload)
  assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "structured_output"


def test_delegate_fixture_drives_each_parent_preset_once_and_child_reads_independently():
  provider = ScriptedProvider(["agentcfg-native-main", "agentcfg-native-reader"], scenario="delegate-presets", delegate_root="/fixture/project")
  payload = {"model": "agentcfg-native-main", "messages": [], "tools": [{"function": {"name": "model_delegate"}}, {"function": {"name": "read"}}]}
  for preset in ("general", "context", "challenge", "plan", "research", "review", "scout"):
    payload["messages"].append({"role": "user", "content": "Native delegate preset " + preset + ": inspect"})
    _, result, _ = provider.response(payload)
    message = result["choices"][0]["message"]; call = message["tool_calls"][0]
    arguments = json.loads(call["function"]["arguments"])
    assert call["function"]["name"] == "model_delegate" and arguments["preset"] == preset
    assert arguments["model_role"] == "scout" and arguments["cwd"] == "/fixture/project"
    payload["messages"].append(message)
    assert "tool_calls" not in provider.response(payload)[1]["choices"][0]["message"]
  child = {"model": "agentcfg-native-reader", "messages": [], "tools": [{"function": {"name": "tk_read"}}]}
  assert provider.response(child)[1]["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "tk_read"


def test_preset_delivery_is_observed_only_from_child_model_input_without_recording_prompt_text():
  purpose = "# general\nExact synthetic purpose text\n"
  provider = ScriptedProvider(["agentcfg-native-main", "agentcfg-native-reader"], delegate_templates={"general": purpose})
  provider.response({"model": "agentcfg-native-main", "messages": [{"role": "user", "content": purpose}]})
  assert provider.snapshot()["delivered_presets"] == []
  provider.response({"model": "agentcfg-native-reader", "messages": [{"role": "user", "content": purpose + "\nActual task follows."}]})
  assert provider.snapshot()["delivered_presets"] == ["general"]
  assert purpose not in json.dumps(provider.snapshot())
