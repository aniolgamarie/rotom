"""委托入口先捕获严格原生参数；坏值不得留下intent或分配执行租约。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg.activity import digest
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from test_pi_delegate import fixture


@pytest.mark.parametrize("field,value", [("feedback_required", None), ("context_artifact", 0), ("continuation_of", 0)])
def test_invalid_optional_has_no_intent_lease_or_spawn_and_key_remains_usable(tmp_path, field, value):
  controller, host, args, calls = fixture(tmp_path)
  with pytest.raises(ConfigError): controller.prepare(Principal("manager"), {**args, field: value})
  assert not list(controller.root.glob("intents/*.json"))
  assert host.store.records() == [] and calls == []
  request = controller.prepare(Principal("manager"), args)
  assert controller.prepare(Principal("manager"), args) == request
  assert len(host.store.records()) == 1 and calls == []


@pytest.mark.parametrize("field,value", [("feedback_required", None), ("context_artifact", 0), ("continuation_of", 0),
  ("allow_workspace_write", 0), ("worktree_root", False)])
def test_invalid_optional_rejects_before_manifest_context_paths_or_allocate(tmp_path, monkeypatch, field, value):
  import agentcfg.model_delegate_context as context
  controller, host, args, calls = fixture(tmp_path)
  def forbidden(*args, **kwargs): pytest.fail("invalid argument reached preparation IO")
  with monkeypatch.context() as guard:
    guard.setattr(host, "manifest", forbidden)
    guard.setattr(host.store, "allocate", forbidden)
    guard.setattr(context, "read_context", forbidden)
    guard.setattr(Path, "resolve", forbidden)
    with pytest.raises(ConfigError): controller.prepare(Principal("manager"), {**args, field: value})
  assert host.store.records() == [] and calls == []
  assert not list(controller.root.glob("intents/*.json"))


def arguments():
  return {"idempotency_key": "一次-😀", "backend": "pi", "mode": "review", "preset": "review", "task": "  bounded task 😀\n",
    "cwd": "/fictional/project", "model": {"provider_id": "provider:one", "model_id": " literal model 😀 "}, "timeout_seconds": 30}


def capture(value):
  from agentcfg.model_delegate import capture_delegate_arguments
  return capture_delegate_arguments(value)


def invalid(value):
  with pytest.raises(ConfigError) as caught: capture(value)
  assert caught.value.exit_code == 2
  assert caught.value.code in ("delegate-request", "pi-control-protocol")
  assert "SYNTHETIC_PRIVATE" not in str(caught.value) and caught.value.__cause__ is None


def test_capture_copies_native_outer_and_model_without_normalizing_values_or_defaults():
  value = arguments(); before = deepcopy(value)
  captured = capture(value)
  assert captured == before and captured is not value and captured["model"] is not value["model"]
  assert digest(captured) == digest(before)
  value["task"] = "changed"; value["model"]["model_id"] = "changed"
  assert captured == before
  captured["model"]["model_id"] = "captured-only"
  assert value["model"]["model_id"] == "changed"


@pytest.mark.parametrize("optional", [{}, {"context_artifact": None}, {"continuation_of": None}, {"worktree_root": None},
  {"feedback_required": False}, {"allow_workspace_write": False}, {"context_artifact": None, "continuation_of": None,
    "worktree_root": None, "feedback_required": False, "allow_workspace_write": False}])
def test_optional_presence_none_and_false_are_preserved_for_idempotency_digest(optional):
  value = {**arguments(), **optional}; captured = capture(value)
  assert captured == value and set(captured) == set(value) and digest(captured) == digest(value)


@pytest.mark.parametrize("field", list(arguments()))
def test_each_required_field_is_required(field):
  value = arguments(); del value[field]; invalid(value)


@pytest.mark.parametrize("field", ["approved", "role", "task_id", "permissions", "grant", "source", "nested", "SYNTHETIC_PRIVATE"])
def test_unknown_self_authority_fields_are_rejected(field):
  invalid({**arguments(), field: True})


@pytest.mark.parametrize("field", ["idempotency_key", "backend", "mode", "preset", "task", "cwd", "context_artifact", "continuation_of", "worktree_root"])
@pytest.mark.parametrize("value", [[], {}, True, 0, 1.0, b"SYNTHETIC_PRIVATE"])
def test_string_scalar_fields_never_accept_non_strings(field, value):
  invalid({**arguments(), field: value})


@pytest.mark.parametrize("field", ["feedback_required", "allow_workspace_write"])
@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}, 1.0])
def test_optional_boolean_fields_are_exact_bool(field, value):
  invalid({**arguments(), field: value})


@pytest.mark.parametrize("value", [None, True, 0, -1, 2**53, 1.0, "30", [], {}])
def test_timeout_is_exact_safe_positive_int(value):
  invalid({**arguments(), "timeout_seconds": value})


@pytest.mark.parametrize("field,value", [("backend", "other"), ("mode", "other"), ("preset", "other"),
  ("task", ""), ("task", " \t\n"), ("cwd", "relative"), ("idempotency_key", ""), ("idempotency_key", "a" * 201),
  ("context_artifact", ""), ("context_artifact", "../escape"), ("continuation_of", "a" * 201),
  ("continuation_of", "中文"), ("worktree_root", "")])
def test_enum_required_content_ids_and_bounds(field, value):
  invalid({**arguments(), field: value})


@pytest.mark.parametrize("field,value", [(field, value) for field in
  ("idempotency_key", "task", "cwd", "worktree_root", "context_artifact", "continuation_of")
  for value in ("SYNTHETIC_PRIVATE\0", "SYNTHETIC_PRIVATE\ud800") if not (field == "task" and value.endswith("\0"))])
def test_nul_and_surrogates_have_fixed_private_errors(field, value):
  invalid({**arguments(), field: value})


def test_task_original_text_including_nul_is_preserved_without_new_authority():
  value = {**arguments(), "task": "literal\0task"}
  assert capture(value) == value


@pytest.mark.parametrize("field", ["task", "cwd", "worktree_root"])
def test_text_uses_utf8_byte_limit_after_bounded_character_check(field):
  value = "/" + "é" * 32768 if field == "cwd" else "é" * 32769
  invalid({**arguments(), field: value})
  invalid({**arguments(), field: ("/" if field == "cwd" else "") + "a" * 65537})


@pytest.mark.parametrize("field", ["provider_id", "model_id"])
@pytest.mark.parametrize("value", [None, True, 0, 1.0, [], {}, "", "SYNTHETIC_PRIVATE\0", "SYNTHETIC_PRIVATE\ud800"])
def test_model_scalar_fields_are_strict_and_nonempty(field, value):
  row = arguments(); row["model"][field] = value; invalid(row)


@pytest.mark.parametrize("model", [None, [], {}, {"provider_id": "p"}, {"model_id": "m"},
  {"provider_id": "p", "model_id": "m", "approved": True}, {"provider_id": "p", "model_id": "m", 1: "extra"}])
def test_model_closed_native_shape(model):
  invalid({**arguments(), "model": model})


def test_model_id_byte_limits_and_provider_pattern():
  value = arguments(); value["model"]["model_id"] = "é" * 32769; invalid(value)
  value = arguments(); value["model"]["provider_id"] = "provider\n"; invalid(value)
  value["model"]["provider_id"] = "中文"; invalid(value)
  value["model"]["provider_id"] = "a" * 201; invalid(value)


@pytest.mark.parametrize("field", ["task", "cwd", "worktree_root", "model_id"])
def test_exact_utf8_capacity_and_unmodified_literal_model_or_paths(field):
  value = arguments()
  text = "/" + "a" * 65535 if field == "cwd" else "é" * 32768
  if field == "model_id": value["model"][field] = text
  else: value[field] = text
  assert capture(value) == value


def test_native_enums_timeout_and_ascii_id_boundaries_without_filesystem_access(monkeypatch):
  def forbidden(*args, **kwargs): pytest.fail("capture performed filesystem IO")
  with monkeypatch.context() as guard:
    for name in ("resolve", "stat", "exists", "is_dir"): guard.setattr(Path, name, forbidden)
    for backend in ("pi", "codex"):
      for mode in ("review", "investigate", "implement"):
        for preset in ("general", "context", "challenge", "plan", "research", "review", "scout"):
          value = {**arguments(), "backend": backend, "mode": mode, "preset": preset, "timeout_seconds": 2**53 - 1,
            "idempotency_key": "😀" * 200, "context_artifact": "a" * 200, "continuation_of": "A:._-9", "worktree_root": "relative/literal"}
          assert capture(value) == value


CALLBACKS = []


class HookDict(dict):
  def __iter__(self): CALLBACKS.append("iter"); raise AssertionError("custom iter")
  def items(self): CALLBACKS.append("items"); raise AssertionError("custom items")
  def __deepcopy__(self, memo): CALLBACKS.append("copy"); raise AssertionError("custom copy")


class HookString(str):
  def __str__(self): CALLBACKS.append("str"); raise AssertionError("custom str")
  def encode(self, *args, **kwargs): CALLBACKS.append("encode"); raise AssertionError("custom encode")


class HookInt(int):
  def __int__(self): CALLBACKS.append("int"); raise AssertionError("custom int")


class HookObject:
  def __bool__(self): CALLBACKS.append("bool"); raise AssertionError("custom bool")
  def __str__(self): CALLBACKS.append("str"); raise AssertionError("custom str")


@pytest.mark.parametrize("location", ["outer", "key", "task", "model", "provider", "timeout", "feedback"])
def test_custom_native_subclasses_and_objects_reject_with_zero_hooks(location):
  CALLBACKS.clear(); value = arguments()
  if location == "outer": value = HookDict(value)
  elif location == "key": value[HookString("extra")] = True
  elif location == "task": value["task"] = HookString("SYNTHETIC_PRIVATE")
  elif location == "model": value["model"] = HookDict(value["model"])
  elif location == "provider": value["model"]["provider_id"] = HookString("provider")
  elif location == "timeout": value["timeout_seconds"] = HookInt(30)
  else: value["feedback_required"] = HookObject()
  invalid(value); assert CALLBACKS == []


@pytest.mark.parametrize("value", [None, [], (), 0, True, 1.0, {i: None for i in range(14)}])
def test_outer_shape_and_key_count_are_checked_before_field_use(value):
  invalid(value)


@pytest.mark.parametrize("optional", [{}, {"context_artifact": None, "continuation_of": None, "worktree_root": None,
  "feedback_required": False, "allow_workspace_write": False}])
def test_real_prepare_keeps_argument_and_request_digest_formulas_and_duplicate_identity(tmp_path, optional):
  controller, host, args, calls = fixture(tmp_path)
  args.update(optional); original = deepcopy(args)
  request = controller.prepare(Principal("manager"), args)
  assert controller.prepare(Principal("manager"), args) == request and args == original
  key = digest({"owner": host.store.owner, "key": args["idempotency_key"]})
  with Tree(controller.root) as tree:
    intent = json.loads(tree.read("intents/" + key + ".json")[0])
  assert intent["arguments_digest"] == digest(original)
  value = controller.input(request["run_id"])
  with Tree(host.runtime_root) as tree:
    purpose = tree.read("supervisor/shared/skills/model-delegate/presets/" + args["preset"] + ".md")[0].decode("utf8")
  bound = {field: item for field, item in request.items() if field != "request_digest"}
  assert request["request_digest"] == digest({"request": bound, "task_digest": digest(args["task"]),
    "route": {field: item for field, item in value["route"].items() if field != "id"}, "context_digest": digest(value["context"]),
    "purpose_digest": digest(purpose), "retry_limit": value["retry_limit"]})
  assert len(host.store.records()) == 1 and calls == []


def test_prepare_uses_captured_outer_and_model_after_caller_mutation_during_manifest(tmp_path):
  controller, host, args, calls = fixture(tmp_path)
  original = deepcopy(args); manifest = host.manifest
  def changed():
    args["task"] = "caller replacement"
    args["model"]["model_id"] = "unbound replacement"
    return manifest()
  host.manifest = changed
  request = controller.prepare(Principal("manager"), args)
  assert request["requested_model"] == original["model"]
  assert controller.input(request["run_id"])["prompt"].endswith(original["task"])
  assert controller.prepare(Principal("manager"), original) == request
  assert len(host.store.records()) == 1 and calls == []
