"""规范动作/来源的纯数据边界与稳定幂等身份，不启动后端。"""

import hashlib

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.model_delegate_actions import capture_delegate_action, capture_delegate_origin, delegate_action_identity
from agentcfg.schema import ConfigError


ORIGIN = {"instance_id": "instance-1", "host": "pi", "source_id": "parent-session:1", "task_id": "task.1", "step_id": None}


def action(kind="submit", **fields):
  base = {"schema_version": 3, "action": kind, "request_id": "父请求:1"}
  if kind == "submit":
    base.update(backend="pi", mode="review", preset="general", task=" /skill literal\0 中文 ",
      model={"provider_id": "provider:1", "model_id": "模型 alpha"}, cwd="/fixture/project", timeout_seconds=19)
  else:
    base["run_id"] = "run:1"
    if kind != "cancel": base["text"] = " /template literal\0 "
    if kind == "continue": base["timeout_seconds"] = 23
  return {**base, **fields}


def invalid(value, code="delegate-action-invalid", capture=capture_delegate_action):
  with pytest.raises(ConfigError) as failure: capture(value)
  assert failure.value.code == code
  assert failure.value.path == ()
  assert "synthetic-secret" not in str(failure.value)


@pytest.mark.parametrize("kind", ["submit", "message", "continue", "cancel"])
def test_four_actions_preserve_literal_content_and_capture_exact_shapes(kind):
  value = action(kind); result = capture_delegate_action(value)
  expected = {**value, **({"context_artifact": None, "feedback_required": False, "allow_workspace_write": False, "worktree_root": None} if kind == "submit" else {})}
  assert result == expected
  assert result is not value
  if kind == "submit": assert result["model"] is not value["model"]


def test_omitted_and_explicit_defaults_share_canonical_action_and_identity():
  omitted = action()
  explicit = action(context_artifact=None, feedback_required=False, allow_workspace_write=False, worktree_root=None)
  assert capture_delegate_action(omitted) == capture_delegate_action(explicit)
  assert delegate_action_identity(ORIGIN, omitted) == delegate_action_identity(ORIGIN, explicit)
  reversed_order = dict(reversed(list(explicit.items())))
  assert delegate_action_identity(dict(reversed(list(ORIGIN.items()))), reversed_order) == delegate_action_identity(ORIGIN, omitted)


def test_same_origin_and_id_are_stable_while_content_or_targets_conflict():
  original = action("message")
  first = delegate_action_identity(ORIGIN, original)
  assert first == delegate_action_identity(dict(ORIGIN), dict(original))
  for changed in [action("message", text="different"), action("message", run_id="run:2"), action("cancel")]:
    identity = delegate_action_identity(ORIGIN, changed)
    assert identity["key"] == first["key"]
    assert identity["request_digest"] != first["request_digest"]
  submitted = delegate_action_identity(ORIGIN, action())
  for patch in [{"backend": "codex"}, {"cwd": "/fixture/other"}, {"model": {"provider_id": "other", "model_id": "different"}}, {"timeout_seconds": 20}]:
    changed = delegate_action_identity(ORIGIN, action(**patch))
    assert changed["key"] == submitted["key"] and changed["request_digest"] != submitted["request_digest"]
  changed_id = delegate_action_identity(ORIGIN, action("message", request_id="父请求:2"))
  assert changed_id["key"] != first["key"]


def test_identity_matches_stable_json_bytes_without_activation_or_random_dependencies(monkeypatch):
  value = action(); identity = delegate_action_identity(ORIGIN, value)
  assert identity == {
    "key": hashlib.sha256(json_bytes({"origin": capture_delegate_origin(ORIGIN), "request_id": value["request_id"]})).hexdigest(),
    "request_digest": hashlib.sha256(json_bytes(capture_delegate_action(value))).hexdigest(),
  }
  monkeypatch.setenv("ACTIVATION_ID", "random-current-owner")
  monkeypatch.setenv("OWNER_NONCE", "random-second-owner")
  assert delegate_action_identity(ORIGIN, value) == identity
  for field, changed in [("instance_id", "instance-2"), ("host", "codex"), ("source_id", "parent-session:2"), ("task_id", None), ("step_id", "step:1")]:
    changed_identity = delegate_action_identity({**ORIGIN, field: changed}, value)
    assert changed_identity["key"] != identity["key"]
    assert changed_identity["request_digest"] == identity["request_digest"]


def test_write_structure_and_backend_capture_do_not_authorize_execution():
  for backend in ["pi", "codex"]:
    captured = capture_delegate_action(action(backend=backend, mode="implement", allow_workspace_write=True, worktree_root="/fixture/worktree"))
    assert captured["backend"] == backend and captured["allow_workspace_write"] is True
    assert not {"approved", "grant", "lease_id", "capability", "writer", "owner"} & captured.keys()
  for patch in [{"mode": "implement"}, {"mode": "implement", "allow_workspace_write": True}, {"mode": "implement", "worktree_root": "/fixture/worktree"},
      {"allow_workspace_write": True}, {"worktree_root": "/fixture/worktree"}, {"mode": "investigate", "allow_workspace_write": True}]: invalid(action(**patch))


def test_closed_actions_reject_missing_inapplicable_and_claimed_authority_fields():
  for kind in ["submit", "message", "continue", "cancel"]:
    value = action(kind)
    for field in value:
      incomplete = dict(value); del incomplete[field]; invalid(incomplete)
    for field in ["role", "approved", "budget", "activation_id", "owner_nonce", "native_id", "unknown-synthetic-secret"]:
      invalid({**value, field: "synthetic-secret"})
  for kind, patch in [("message", {"task": "text"}), ("continue", {"backend": "pi"}), ("cancel", {"text": "text"}),
      ("cancel", {"timeout_seconds": 1}), ("submit", {"run_id": "run:1"}), ("message", {"feedback_required": False})]: invalid(action(kind, **patch))
  invalid({"schema_version": 3, "action": "status", "request_id": "id"}, "delegate-action-unsupported")
  for version in [2, 4, True, 3.0, None]: invalid(action(schema_version=version))
  invalid(action(action=None))


def test_origin_is_closed_native_stable_data_with_nullable_labels():
  assert capture_delegate_origin(ORIGIN) == ORIGIN
  assert capture_delegate_origin(ORIGIN) is not ORIGIN
  for host in ["pi", "codex", "cli"]:
    result = capture_delegate_origin({**ORIGIN, "host": host, "task_id": None, "step_id": None})
    assert result["host"] == host and result["task_id"] is None and result["step_id"] is None
  for field in ORIGIN:
    value = dict(ORIGIN); del value[field]; invalid(value, "delegate-origin-invalid", capture_delegate_origin)
  for field in ["activation", "owner", "role", "approved", "nativeID"]:
    invalid({**ORIGIN, field: "synthetic-secret"}, "delegate-origin-invalid", capture_delegate_origin)
  for patch in [{"host": "other"}, {"instance_id": None}, {"source_id": "native/cache"}, {"task_id": ""}, {"step_id": True}]:
    invalid({**ORIGIN, **patch}, "delegate-origin-invalid", capture_delegate_origin)


def test_string_unicode_byte_bounds_and_timeout_types():
  for request_id in ["😀" * 200, "界" * 200, " literal \n id "]:
    assert capture_delegate_action(action(request_id=request_id))["request_id"] == request_id
  for text in ["x" * 65536, "界" * 21845 + "x", "literal\0text"]:
    assert capture_delegate_action(action(task=text))["task"] == text
    assert capture_delegate_action(action("message", text=text))["text"] == text
  for request_id in ["", "x" * 201, "\ud800", "x\0", None, True]: invalid(action(request_id=request_id))
  for text in ["", " \n\t ", "界" * 21846, "\udfff", None, 3]:
    invalid(action(task=text)); invalid(action("continue", text=text))
  for timeout in [1, 2**53 - 1]: assert capture_delegate_action(action(timeout_seconds=timeout))["timeout_seconds"] == timeout
  for timeout in [0, -1, 2**53, True, 1.0, None]:
    invalid(action(timeout_seconds=timeout)); invalid(action("continue", timeout_seconds=timeout))


def test_model_paths_ascii_id_and_optional_boundaries():
  for model_id in ["", " ", "synthetic-secret\n", "model\u200b", "\ud800", "界" * 21846, None]:
    invalid(action(model={"provider_id": "provider", "model_id": model_id}))
  assert capture_delegate_action(action(model={"provider_id": "p" * 200, "model_id": "m" * 65536}))["model"]["model_id"] == "m" * 65536
  for native_id in ["", "-leading", ".leading", "界", "name/path", "x" * 201, None, True]:
    invalid(action(model={"provider_id": native_id, "model_id": "model"})); invalid(action("cancel", run_id=native_id))
    if native_id is not None: invalid(action(context_artifact=native_id))
  for path in ["/", "//root", "/a//b", "/a/../b", "/a/./b", "/a/", "relative", "/a\0", "/\udfff", None]:
    invalid(action(cwd=path)); invalid(action(mode="implement", allow_workspace_write=True, worktree_root=path))
  assert capture_delegate_action(action(cwd="/业务 中文"))["cwd"] == "/业务 中文"
  for field in ["feedback_required", "allow_workspace_write"]:
    for value in [None, 0, 1, "true"]: invalid(action(**{field: value}))
  for model in [None, {"provider_id": "p"}, {"provider_id": "p", "model_id": "m", "apiKey": "synthetic-secret"}]: invalid(action(model=model))
  for field in ["backend", "mode", "preset"]: invalid(action(**{field: "unsupported"}))


def test_no_foreign_mapping_scalar_or_copy_hooks_are_executed():
  calls = []
  class DictHook(dict):
    def keys(self): calls.append("keys"); raise AssertionError
    def __iter__(self): calls.append("iter"); raise AssertionError
    def __deepcopy__(self, memo): calls.append("deepcopy"); raise AssertionError
  class StrHook(str):
    def encode(self, *args, **kwargs): calls.append("encode"); raise AssertionError
    def strip(self): calls.append("strip"); raise AssertionError
    def __str__(self): calls.append("str"); raise AssertionError
  class IntHook(int):
    def __int__(self): calls.append("int"); raise AssertionError
  for value in [DictHook(action()), action(model=DictHook(action()["model"])), action(task=StrHook("task")), action(request_id=StrHook("id")),
      action(action=StrHook("submit")), action(schema_version=IntHook(3)), action(timeout_seconds=IntHook(19))]: invalid(value)
  for value in [DictHook(ORIGIN), {**ORIGIN, "host": StrHook("pi")}, {**ORIGIN, "source_id": StrHook("source")}]:
    invalid(value, "delegate-origin-invalid", capture_delegate_origin)
  value = action(); value[StrHook("foreign")] = "synthetic-secret"; invalid(value)
  invalid({**ORIGIN, StrHook("foreign"): "synthetic-secret"}, "delegate-origin-invalid", capture_delegate_origin)
  assert calls == []


def test_caller_mutation_cannot_change_captured_data_or_prior_identity():
  value = action(); origin = dict(ORIGIN)
  captured = capture_delegate_action(value); captured_origin = capture_delegate_origin(origin)
  first = delegate_action_identity(origin, value)
  value["model"]["model_id"] = "later"; value["task"] = "later"; origin["source_id"] = "later"
  assert captured["model"]["model_id"] == "模型 alpha" and captured["task"] != "later"
  assert captured_origin["source_id"] == "parent-session:1"
  assert delegate_action_identity(captured_origin, captured) == first
  captured["model"]["provider_id"] = "edited"
  assert value["model"]["provider_id"] == "provider:1"


def test_identity_validates_both_boundaries_and_pure_functions_do_not_access_files(monkeypatch):
  with pytest.raises(ConfigError) as failure: delegate_action_identity({**ORIGIN, "approved": True}, action())
  assert failure.value.code == "delegate-origin-invalid"
  with pytest.raises(ConfigError) as failure: delegate_action_identity(ORIGIN, action(approved=True))
  assert failure.value.code == "delegate-action-invalid"
  def forbidden(*args, **kwargs): raise AssertionError("filesystem access forbidden")
  with monkeypatch.context() as patch:
    patch.setattr("builtins.open", forbidden)
    patch.setattr("os.stat", forbidden)
    patch.setattr("pathlib.Path.resolve", forbidden)
    assert delegate_action_identity(ORIGIN, action())["key"]


def test_private_native_snapshots_survive_caller_thread_mutation_during_validation(monkeypatch):
  import threading
  import agentcfg.model_delegate_actions as actions
  value = action(task="original task")
  validated = threading.Event(); changed = threading.Event()
  original = actions._text
  def barrier(item, *args, **kwargs):
    captured = original(item, *args, **kwargs)
    if item == "original task":
      validated.set(); assert changed.wait(5)
    return captured
  def caller():
    assert validated.wait(5)
    value["task"] = "later"; value["cwd"] = "/../forged"
    value["model"]["provider_id"] = "../forged"; value["model"]["model_id"] = "later"
    changed.set()
  monkeypatch.setattr(actions, "_text", barrier)
  # 仅替换自有 validator 建立测试屏障，不改宿主或上游。
  worker = threading.Thread(target=caller); worker.start()
  try: captured = capture_delegate_action(value)
  finally: worker.join(timeout=5)
  assert not worker.is_alive()
  assert captured["task"] == "original task" and captured["cwd"] == "/fixture/project"
  assert captured["model"] == {"provider_id": "provider:1", "model_id": "模型 alpha"}
