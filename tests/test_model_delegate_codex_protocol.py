"""只使用仓库内原样 public schema 的离线协议验收。"""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft7Validator
import pytest

from agentcfg.model_delegate_codex_protocol import build_codex_delegate_request
from agentcfg.schema import ConfigError


FIXTURE = Path(__file__).parent / "fixtures/pi/codex-protocol-0.154.0"
BINDING = {"model": "synthetic-model", "model_provider": "native-alias", "cwd": "/fixture/project"}
CASES = [
  ("thread_start", "thread/start", "ThreadStartParams", {}),
  ("thread_resume", "thread/resume", "ThreadResumeParams", {"thread_id": "thread.exact:1"}),
  ("turn_start", "turn/start", "TurnStartParams", {"thread_id": "thread.exact:1", "text": " /skill literal\0 中文 "}),
  ("turn_steer", "turn/steer", "TurnSteerParams", {"thread_id": "thread.exact:1", "turn_id": "turn.exact:2", "text": "/template literal"}),
  ("turn_interrupt", "turn/interrupt", "TurnInterruptParams", {"thread_id": "thread.exact:1", "turn_id": "turn.exact:2"}),
]


def request(action="thread_start", **fields):
  return {"action": action, "request_id": "父请求:1", "binding": dict(BINDING), **fields}


@pytest.mark.parametrize("action,method,schema_name,fields", CASES)
def test_five_actions_match_independent_public_schemas(action, method, schema_name, fields):
  value = request(action, **fields)
  result = build_codex_delegate_request(value)
  assert set(result) == {"id", "method", "params"}
  assert result["method"] == method
  assert result["id"] == value["request_id"]
  schema = json.loads((FIXTURE / (schema_name + ".json")).read_text())
  Draft7Validator.check_schema(schema)
  Draft7Validator(schema).validate(result["params"])
  params = result["params"]
  if "thread_id" in fields: assert params["threadId"] == fields["thread_id"]
  if action == "turn_steer": assert params["expectedTurnId"] == fields["turn_id"]
  if action == "turn_interrupt": assert params["turnId"] == fields["turn_id"]
  if "text" in fields:
    assert params["input"] == [{"type": "text", "text": fields["text"], "text_elements": []}]
  if action in {"thread_start", "thread_resume"}:
    assert params == {"model": BINDING["model"], "modelProvider": BINDING["model_provider"], "cwd": BINDING["cwd"],
      "approvalPolicy": "never", "sandbox": "read-only", **({"threadId": fields["thread_id"]} if fields else {})}
  if action == "turn_start":
    assert params["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    assert params["model"] == BINDING["model"] and params["cwd"] == BINDING["cwd"]
    assert params["approvalPolicy"] == "never"
  forbidden = {"allowProviderModelFallback", "permissions", "config", "path", "history", "fork", "name"}
  assert not forbidden & params.keys()


def test_fixture_hashes_pin_unmodified_schema_license_and_notice():
  source = json.loads((FIXTURE / "SOURCE.json").read_text())
  assert source["commit"] == "6b9826e3aa83b1a5947db50f4332cb9c65f1b340"
  assert source["archive_sha256"] == "848c7ffac62e21b14edc2048d2e5b7c82b31c556afa4b0d305da0f7d5aa794f4"
  assert set(source["files"]) == {case[2] + ".json" for case in CASES} | {"LICENSE", "NOTICE"}
  for name, metadata in source["files"].items():
    assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == metadata["sha256"]


def test_request_id_unicode_and_boundaries_preserve_original_scalars():
  for request_id in ["x", "界" * 200, "😀" * 200, "raw \n id"]:
    assert build_codex_delegate_request(request(request_id=request_id))["id"] == request_id
  for invalid in ["", "x" * 201, "x\0", "\ud800", None, 3, True]:
    with pytest.raises(ConfigError) as failure:
      build_codex_delegate_request(request(request_id=invalid))
    assert failure.value.code == "codex-delegate-request-invalid"


def test_unknown_fields_and_action_combinations_are_closed():
  for field in ["role", "approved", "budget", "rawconfig", "config", "history", "path", "name", "fork", "--last"]:
    with pytest.raises(ConfigError): build_codex_delegate_request(request(**{field: True}))
  for action, _method, _schema, fields in CASES:
    value = request(action, **fields)
    for key in fields:
      missing = dict(value); del missing[key]
      with pytest.raises(ConfigError): build_codex_delegate_request(missing)
      invalid = dict(value); invalid[key] = None
      with pytest.raises(ConfigError): build_codex_delegate_request(invalid)
    for key in {"thread_id", "turn_id", "text"} - fields.keys():
      with pytest.raises(ConfigError): build_codex_delegate_request({**value, key: None})
  with pytest.raises(ConfigError) as failure:
    build_codex_delegate_request(request("open_recent"))
  assert failure.value.code == "codex-delegate-action-unsupported"
  with pytest.raises(ConfigError): build_codex_delegate_request(request(action=None))


def test_binding_native_aliases_models_and_lexical_cwd_are_validated():
  for field, invalid in [("model", ""), ("model", "x\n"), ("model", "x\u200b"), ("model", "\udfff"), ("model", "界" * 21846),
      ("model_provider", ""), ("model_provider", "p" * 257), ("model_provider", "p\0"), ("model_provider", None),
      ("cwd", "/"), ("cwd", "relative"), ("cwd", "/a/../b"), ("cwd", "/a/./b"), ("cwd", "/a/"), ("cwd", "//a"), ("cwd", "/a//b"),
      ("cwd", "/a\0"), ("cwd", "/\ud800")]:
    value = request(); value["binding"][field] = invalid
    with pytest.raises(ConfigError): build_codex_delegate_request(value)
  for binding in [None, {**BINDING, "provider_id": "logical-provider"}, {"model": "x", "cwd": "/a"}]:
    with pytest.raises(ConfigError): build_codex_delegate_request(request(binding=binding))
  value = request(binding={"model": "m" * 65536, "model_provider": "界" * 256, "cwd": "/业务 中文"})
  result = build_codex_delegate_request(value)
  assert result["params"]["modelProvider"] == "界" * 256
  assert result["params"]["cwd"] == "/业务 中文"


def test_text_byte_bounds_and_forged_native_ids():
  for text in ["", " \n ", "\ud800", "界" * 21846, None]:
    with pytest.raises(ConfigError): build_codex_delegate_request(request("turn_start", thread_id="exact", text=text))
  for text in ["x" * 65536, "界" * 21845 + "x", " /skill\0 literal "]:
    assert build_codex_delegate_request(request("turn_start", thread_id="exact", text=text))["params"]["input"][0]["text"] == text
  for native_id in ["", "--last", "../thread", "/thread", "thread name", "界", "x" * 201, None, True]:
    with pytest.raises(ConfigError): build_codex_delegate_request(request("thread_resume", thread_id=native_id))
    with pytest.raises(ConfigError): build_codex_delegate_request(request("turn_interrupt", thread_id="exact", turn_id=native_id))


def test_native_type_capture_does_not_invoke_subclass_or_copy_hooks():
  hooks = []
  class DictHook(dict):
    def keys(self): hooks.append("keys"); raise AssertionError
    def __iter__(self): hooks.append("iter"); raise AssertionError
    def __deepcopy__(self, memo): hooks.append("deepcopy"); raise AssertionError
  class StringHook(str):
    def encode(self, *args, **kwargs): hooks.append("encode"); raise AssertionError
    def strip(self): hooks.append("strip"); raise AssertionError
  for value in [DictHook(request()), request(binding=DictHook(BINDING)), request(request_id=StringHook("id")),
      request(action=StringHook("thread_start")), request(binding={**BINDING, "model": StringHook("model")})]:
    with pytest.raises(ConfigError): build_codex_delegate_request(value)
  assert hooks == []


def test_wire_containers_are_independent_of_caller_and_other_requests():
  value = request("turn_start", thread_id="exact", text="literal")
  first = build_codex_delegate_request(value); second = build_codex_delegate_request(value)
  value["binding"]["model"] = "later"; value["text"] = "later"
  first["params"]["input"][0]["text_elements"].append({"later": True})
  first["params"]["sandboxPolicy"]["networkAccess"] = True
  assert second["params"]["model"] == "synthetic-model"
  assert second["params"]["input"] == [{"type": "text", "text": "literal", "text_elements": []}]
  assert second["params"]["sandboxPolicy"]["networkAccess"] is False


def test_caller_thread_cannot_change_native_ids_after_validation(monkeypatch):
  import threading
  import agentcfg.model_delegate_codex_protocol as protocol
  value = request("turn_interrupt", thread_id="thread.original", turn_id="turn.original")
  validated = threading.Event(); mutated = threading.Event()
  original = protocol._native_id
  validations = 0
  def barrier(item):
    nonlocal validations
    captured = original(item)
    validations += 1
    if validations == 2:
      validated.set()
      assert mutated.wait(5), "caller thread failed to mutate"
    return captured
  def caller():
    assert validated.wait(5), "validator barrier not reached"
    value["thread_id"] = "../forged-thread"; value["turn_id"] = "other-turn"
    mutated.set()
  monkeypatch.setattr(protocol, "_native_id", barrier)
  # 仅同步自有 validator 的测试线程，不替换宿主或上游方法、不运行子进程。
  worker = threading.Thread(target=caller); worker.start()
  try:
    result = protocol.build_codex_delegate_request(value)
  finally:
    worker.join(timeout=5)
  assert not worker.is_alive()
  assert result["params"] == {"threadId": "thread.original", "turnId": "turn.original"}
