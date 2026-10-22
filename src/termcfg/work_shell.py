"""原生新pane的shell回退；有意图时由一次性握手准入。"""

import os
from pathlib import Path
import json
import re
import sys
import time

from .errors import TermcfgError
from .work_config import ROOT, ROLES, PAYLOAD_ENV, PAYLOAD_ENV_V2, resolve_executable, read_settings, prepare_tool, operation_timeout


def parse_payload_v2(text, *, check_deadline=True):
  """仅解析有界的普通数据；授权仍需对应的受保护不可变意图。"""
  from jsonschema import Draft202012Validator
  from .work_state import LAUNCH_SCHEMA, ID_PATTERN, absolute, launch_digest
  from .work_config import literal
  def unique(pairs):
    result = {}
    for key, item in pairs:
      if key in result:
        raise ValueError()
      result[key] = item
    return result
  try:
    if not isinstance(text, str) or len(text.encode("utf-8")) > 16384:
      raise ValueError()
    value = json.loads(text, object_pairs_hook=unique,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    fields = {"version", "action", "kind", "op", "instance", "epoch", "owner", "context_kind",
      "type", "workspace_start", "cwd", "captured_home", "launch", "binding_digest", "local",
      "session", "socket_path", "endpoint_dev", "endpoint_ino", "rotom_root", "source_digest",
      "selection_digest", "intent_path", "expires_at_ns"}
    if not isinstance(value, dict) or value.get("action") not in ("workspace-initial", "tab"):
      raise ValueError()
    if value["action"] == "tab":
      fields.add("workspace_id")
    if value.keys() != fields:
      raise ValueError()
    if (type(value["version"]) is not int or value["version"] != 2
        or value["kind"] not in ("default", "extra")
        or (value["action"] == "workspace-initial" and value["kind"] != "default")
        or value["context_kind"] not in ("project", "named")):
      raise ValueError()
    for key in ("endpoint_dev", "endpoint_ino", "expires_at_ns"):
      if type(value[key]) is not int or value[key] < (1 if key == "expires_at_ns" else 0):
        raise ValueError()
    for key, item in value.items():
      if key not in ("version", "endpoint_dev", "endpoint_ino", "expires_at_ns", "launch"):
        literal(item)
    for key in ("op", "instance", "epoch", "owner", "binding_digest", "source_digest", "selection_digest"):
      length = 32 if key in ("op", "instance", "epoch") else 64
      if not re.fullmatch("[a-f0-9]{" + str(length) + "}", value[key]):
        raise ValueError()
    if not re.fullmatch(ID_PATTERN, value["type"]) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value["session"]):
      raise ValueError()
    for key in ("workspace_start", "cwd", "captured_home", "local", "socket_path", "rotom_root", "intent_path"):
      absolute(value[key])
    launch = value["launch"]
    if not Draft202012Validator(LAUNCH_SCHEMA).is_valid(launch):
      raise ValueError()
    for item in launch["argv"]:
      literal(item)
    absolute(launch["argv"][0])
    for item in launch["paths"].values():
      if item is not None:
        absolute(item)
    if (launch["paths"]["HOME"] != value["captured_home"]
        or (launch["launcher"] in ("pi", "dsh")) != (launch["runtime"] is not None)
        or value["binding_digest"] != launch_digest(value["cwd"], value["captured_home"], launch)):
      raise ValueError()
    if launch["runtime"] is not None:
      for item in launch["runtime"].values():
        literal(item)
    if check_deadline:
      now = time.monotonic_ns()
      if not now < value["expires_at_ns"] <= now + operation_timeout(launch["launcher"]) * 1_000_000_000:
        raise ValueError()
    return value
  except (ValueError, TypeError, UnicodeError, KeyError, RecursionError, TermcfgError):
    raise TermcfgError(2, "work_launch_payload_invalid", "work enter PATH") from None


def _v2_intent(state, value):
  from .work import conflict
  from .work_state import digest
  expected_path = state.root / "intents" / (value["op"] + ".json")
  if str(expected_path) != value["intent_path"]:
    raise conflict("work_launch_intent_location_changed")
  intent = state.read_intent(value["op"])
  if (intent is None or any(intent[key] != value[key] for key in ("op", "owner", "epoch", "action", "type", "instance", "kind"))
      or intent["payload_digest"] != digest(value)):
    raise conflict("work_launch_intent_changed")
  binding = intent["binding"]
  item = binding["types"].get(value["type"])
  if (binding["context"]["kind"] != value["context_kind"]
      or binding["workspace_start"] != value["workspace_start"] or item is None
      or any(item[key] != value[payload_key] for key, payload_key in
        (("cwd", "cwd"), ("captured_home", "captured_home"), ("launch", "launch"), ("digest", "binding_digest")))
      or value["instance"] in item["instances"]
      or (value["action"] == "tab" and binding["workspace_id"] != value["workspace_id"])):
    raise conflict("work_launch_binding_changed")
  return binding, item


def launch_payload_v2(text, *, client=None, settings=None, execute=None):
  from .herdr import HerdrClient, Deadline
  from .work import info, tokens, report_tokens, source_digest, conflict
  from .work_config import bound_paths, prepare_launch
  from .work_state import WorkState, MODEL, LAUNCH_SOURCE
  value = parse_payload_v2(text)
  deadline = Deadline(timeout=max(0, (value["expires_at_ns"] - time.monotonic_ns()) / 1_000_000_000))
  deadline.expires_at = min(deadline.expires_at, value["expires_at_ns"] / 1_000_000_000)
  owned_client = marked = False
  pane = None
  expected = {"rw2_" + key: value[key] for key in ("owner", "epoch", "type", "instance", "kind", "op")}
  try:
    if (value["rotom_root"] != str(ROOT) or source_digest() != value["source_digest"]):
      raise conflict("work_launch_source_changed")
    if client is None:
      client = HerdrClient(value["socket_path"], deadline,
        expected_identity=(value["endpoint_dev"], value["endpoint_ino"]))
      owned_client = True
    elif client.identity != (value["endpoint_dev"], value["endpoint_ino"]):
      raise conflict("work_launch_endpoint_changed")
    client.deadline = deadline
    client.request("ping", {})
    caller_id = os.environ.get("HERDR_PANE_ID")
    if not caller_id:
      raise conflict("work_launch_caller_unknown")
    pane = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
    if value["action"] == "tab" and pane["workspace_id"] != value["workspace_id"]:
      raise conflict("work_launch_membership_changed")
    if any(key.startswith(("rw_", "rw2_")) for key in tokens(pane)):
      raise conflict("work_launch_already_consumed")
    native_ids = {key: pane[key] for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")}
    root = Path(value["intent_path"])
    if len(root.parents) < 3:
      raise conflict("work_launch_intent_location_changed")
    with WorkState(value["socket_path"], client.identity, root=root.parents[2]) as state:
      binding, item = _v2_intent(state, value)
      def scope(*, committed=False, ready=False, accepted=False):
        deadline.remaining()
        current = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
        if any(current[key] != expected_id for key, expected_id in native_ids.items()):
          raise conflict("work_launch_membership_changed")
        workspace = info(client.request("workspace.get", {"workspace_id": current["workspace_id"]}), "workspace")
        if workspace.get("worktree") is not None:
          raise conflict("work_launch_grouped_workspace")
        marker = tokens(workspace)
        required = {"rw2_owner": value["owner"], "rw2_epoch": value["epoch"],
          "rw2_model": MODEL, "rw2_pending": value["op"]}
        owned = {key: val for key, val in marker.items() if key.startswith("rw2_")}
        if accepted:
          # 接收后父端可清 pending 或开始下一操作，旧操作只保留自身 pane 提交证明。
          pending = owned.get("rw2_pending")
          stable = {key: val for key, val in owned.items() if key != "rw2_pending"}
          valid_workspace = (stable == {key: val for key, val in required.items() if key != "rw2_pending"}
            and (pending is None or re.fullmatch(r"[a-f0-9]{32}", pending)))
        else:
          valid_workspace = not (committed or value["action"] == "tab" or owned) or owned == required
        if any(key.startswith("rw_") for key in marker) or not valid_workspace:
          raise conflict("work_launch_workspace_changed")
        if ready or accepted:
          observed = tokens(current)
          if (any(observed.get(key) != val for key, val in expected.items())
              or observed.get("rw2_phase") != ("accepted" if accepted else "ready")
              or observed.get("rw2_commit") not in ((value["op"],) if accepted else (None, value["op"]))
              or any(key.startswith("rw2_") and key not in {*expected, "rw2_phase", "rw2_commit"}
                for key in observed)):
            raise conflict("work_launch_pane_changed")
        return current
      def prepared():
        deadline.remaining()
        if source_digest() != value["source_digest"]:
          raise conflict("work_launch_source_changed")
        chosen = settings or read_settings(local=value["local"], repo_root=ROOT)
        if (chosen.selection_digest != value["selection_digest"] or chosen.session != value["session"]
            or chosen.model != MODEL or chosen.repo_root != ROOT):
          raise conflict("work_launch_selection_changed")
        try:
          definition = chosen.structured["templates"][binding["template"]]["tab_types"][value["type"]]
        except (KeyError, TypeError):
          raise conflict("work_launch_type_changed") from None
        requested = prepare_launch(chosen, definition, binding["workspace_start"], fixed=item)
        if any(requested[key] != item[key] for key in ("cwd", "captured_home", "launch", "digest")):
          raise conflict("work_launch_contract_changed")
        deadline.remaining()
        return requested["launch"]["argv"]
      with bound_paths(value["launch"]["paths"]):
        prepared()
        scope()
        report_tokens(client, "pane", pane["pane_id"], {**expected, "rw2_phase": "ready"}, source=LAUNCH_SOURCE)
        marked = True
        while True:
          current = scope(ready=True)
          if tokens(current).get("rw2_commit") == value["op"]:
            break
          time.sleep(deadline.remaining(0.02))
        scope(committed=True, ready=True)
        _v2_intent(state, value)
        receipt = state.read("receipts", value["op"])
        if (receipt is None or receipt["phase"] != "commit-issued"
            or any(receipt[key] != value[key] for key in ("op", "owner", "epoch", "action", "type", "instance", "kind"))
            or any(receipt[key] != val for key, val in native_ids.items())):
          raise conflict("work_launch_commit_not_durable")
        command = prepared()
        scope(committed=True, ready=True)
        report_tokens(client, "pane", pane["pane_id"], {"rw2_phase": "accepted"}, source=LAUNCH_SOURCE)
        deadline.remaining()
        environment = dict(os.environ)
        for name in (PAYLOAD_ENV, PAYLOAD_ENV_V2):
          environment.pop(name, None)
          os.environ.pop(name, None)
        os.chdir(value["cwd"])
        scope(accepted=True)
        deadline.remaining()
        try:
          (execute or os.execvpe)(command[0], command, environment)
        except OSError:
          raise TermcfgError(5, "work_launch_exec_failed", "work enter PATH") from None
        return 0
  except (TermcfgError, OSError, KeyError, ValueError) as error:
    failure = error if isinstance(error, TermcfgError) else TermcfgError(5, "work_launch_failed", "work status")
    failure.fallback_safe = False
    if marked and client is not None and pane is not None:
      try:
        client.deadline = Deadline(2)
        current = info(client.request("pane.get", {"pane_id": pane["pane_id"]}), "pane")
        if (current["terminal_id"] == pane["terminal_id"]
            and all(tokens(current).get(key) == val for key, val in expected.items())):
          report_tokens(client, "pane", pane["pane_id"], {"rw2_phase": "failed", "rw2_commit": None}, source=LAUNCH_SOURCE)
      except (TermcfgError, OSError, KeyError, ValueError):
        pass
    raise failure from None
  finally:
    if owned_client:
      client.close()


def parse_payload(text):
  def unique(pairs):
    result = {}
    for key, value in pairs:
      if key in result:
        raise ValueError()
      result[key] = value
    return result
  try:
    if not isinstance(text, str) or len(text.encode("utf-8")) > 16384:
      raise ValueError()
    value = json.loads(text, object_pairs_hook=unique,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    required = {"version", "role", "kind", "op", "epoch", "project_digest", "checkout", "workspace_id",
      "session", "socket_path", "endpoint_dev", "endpoint_ino", "rotom_root", "source_digest",
      "selection_digest", "expires_at_ns"}
    if (not isinstance(value, dict) or not required <= value.keys() or
        value.keys() - required - {"machine", "local"} or len(value.keys() & {"machine", "local"}) != 1):
      raise ValueError()
    if type(value["version"]) is not int or value["version"] != 1 or value["role"] not in ROLES or value["kind"] not in ("primary", "extra"):
      raise ValueError()
    for key in ("op", "epoch", "project_digest", "source_digest", "selection_digest"):
      length = 32 if key in ("op", "epoch") else 64
      if not isinstance(value[key], str) or not re.fullmatch("[a-f0-9]{" + str(length) + "}", value[key]):
        raise ValueError()
    for key, item in value.items():
      if key in ("version", "endpoint_dev", "endpoint_ino", "expires_at_ns"):
        if type(item) is not int or item < (1 if key == "expires_at_ns" else 0):
          raise ValueError()
      elif not isinstance(item, str) or not item or any(ord(c) < 32 or ord(c) == 127 for c in item):
        raise ValueError()
    now = time.monotonic_ns()
    if not now < value["expires_at_ns"] <= now + operation_timeout(value["role"]) * 1_000_000_000:
      raise ValueError()
    for key in ("checkout", "rotom_root", "socket_path", "local"):
      if key in value and (not Path(value[key]).is_absolute() or ".." in Path(value[key]).parts):
        raise ValueError()
    return value
  except (ValueError, TypeError, UnicodeError):
    raise TermcfgError(2, "work_launch_payload_invalid", "work enter PATH") from None


def launch_payload(text, *, client=None, settings=None, execute=None):
  from .herdr import HerdrClient, Deadline
  from .work import info, tokens, report_tokens, source_digest, project_digest, LAUNCH_SOURCE
  value = parse_payload(text)
  remaining = (value["expires_at_ns"] - time.monotonic_ns()) / 1_000_000_000
  deadline = Deadline(timeout=max(0, min(operation_timeout(value["role"]), remaining)))
  deadline.expires_at = min(deadline.expires_at, value["expires_at_ns"] / 1_000_000_000)
  owned_client = False
  pane_id = None
  terminal_id = None
  marked = accepted = False
  try:
    root = Path(value["checkout"]).resolve(strict=True)
    if (str(root) != value["checkout"] or not root.is_dir() or root == Path("/") or
        Path(value["rotom_root"]) != ROOT or source_digest() != value["source_digest"] or
        project_digest(root) != value["project_digest"]):
      raise TermcfgError(4, "work_launch_source_changed", "work enter PATH")
    settings = settings or read_settings(machine=value.get("machine"), local=value.get("local"))
    if settings.selection_digest != value["selection_digest"] or settings.session != value["session"]:
      raise TermcfgError(4, "work_launch_selection_changed", "work enter PATH")
    command = prepare_tool(settings, value["role"], root)
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
      raise TermcfgError(4, "work_launch_caller_unknown", "work enter PATH")
    if client is None:
      client = HerdrClient(value["socket_path"], deadline,
        expected_identity=(value["endpoint_dev"], value["endpoint_ino"]))
      owned_client = True
    elif client.identity != (value["endpoint_dev"], value["endpoint_ino"]):
      raise TermcfgError(4, "work_launch_endpoint_changed", "work enter PATH")
    client.request("ping", {})
    pending = value["role"] + ":" + value["op"] + ":" + value["kind"]
    def validate():
      deadline.remaining()
      caller = info(client.request("pane.current", {"caller_pane_id": pane_id}), "pane")
      workspace = info(client.request("workspace.get", {"workspace_id": value["workspace_id"]}), "workspace")
      state = tokens(workspace)
      if (caller["workspace_id"] != value["workspace_id"] or
          (terminal_id is not None and caller["terminal_id"] != terminal_id) or
          state.get("rw_epoch") != value["epoch"] or state.get("rw_project") != value["project_digest"] or
          state.get("rw_pending") != pending or
          workspace.get("worktree", {}).get("checkout_path") != str(root)):
        raise TermcfgError(4, "work_launch_identity_changed", "work enter PATH")
      return caller
    initial = validate()
    terminal_id = initial["terminal_id"]
    if tokens(initial).get("rw_op") is not None:
      raise TermcfgError(4, "work_launch_already_consumed", "work enter PATH")
    report_tokens(client, "pane", pane_id, {"rw_project": value["project_digest"],
      "rw_epoch": value["epoch"], "rw_role": value["role"], "rw_op": value["op"],
      "rw_kind": value["kind"], "rw_phase": "ready"}, source=LAUNCH_SOURCE)
    marked = True
    while True:
      caller = validate()
      state = tokens(caller)
      if any(state.get(key) != expected for key, expected in {
          "rw_project": value["project_digest"], "rw_epoch": value["epoch"], "rw_role": value["role"],
          "rw_op": value["op"], "rw_kind": value["kind"], "rw_phase": "ready"}.items()):
        raise TermcfgError(4, "work_launch_identity_changed", "work enter PATH")
      if state.get("rw_commit") == value["op"]:
        break
      if state.get("rw_commit") is not None or state.get("rw_phase") != "ready":
        raise TermcfgError(4, "work_launch_commit_mismatch", "work enter PATH")
      time.sleep(deadline.remaining(0.02))
    validate()
    # accepted请求可能已经应用但丢响应；失败上报不明时不能回退成伪有效普通shell。
    accepted = True
    report_tokens(client, "pane", pane_id, {"rw_phase": "accepted"}, source=LAUNCH_SOURCE)
    deadline.remaining()
    environment = dict(os.environ)
    environment.pop(PAYLOAD_ENV, None)
    os.environ.pop(PAYLOAD_ENV, None)
    os.chdir(root)
    try:
      (execute or os.execvpe)(command[0], command, environment)
    except OSError:
      raise TermcfgError(5, "work_launch_exec_failed", "work enter PATH") from None
    return 0
  except (TermcfgError, OSError, KeyError, ValueError) as error:
    failure = error if isinstance(error, TermcfgError) else TermcfgError(5, "work_launch_failed", "work enter PATH")
    failure.fallback_safe = not accepted
    if marked and client is not None:
      try:
        # 单独有界的失败上报不会重启任务；无法撤销accepted时不留下伪有效shell。
        client.deadline = Deadline(timeout=2)
        report_tokens(client, "pane", pane_id, {"rw_phase": "failed", "rw_commit": None,
          "rw_error": "work_launch_failed"}, source=LAUNCH_SOURCE)
        failure.fallback_safe = True
      except TermcfgError:
        pass
    raise failure from None
  finally:
    if owned_client:
      client.close()


def fallback_shell():
  value = os.environ.get("SHELL") or "/bin/sh"
  if Path(value).resolve() == (ROOT / "rotom-work-shell").resolve():
    raise TermcfgError(2, "work_recursive_shell", "work --help")
  executable = resolve_executable(value)
  env = dict(os.environ)
  env.pop(PAYLOAD_ENV, None)
  env.pop(PAYLOAD_ENV_V2, None)
  os.execvpe(executable, [executable], env)
  return 0


def main():
  structured_payload = os.environ.pop(PAYLOAD_ENV_V2, None)
  payload = os.environ.pop(PAYLOAD_ENV, None)
  if structured_payload is not None:
    if payload is not None:
      print("work_launch_payload_versions_conflict", file=sys.stderr)
      return 2
    try:
      return launch_payload_v2(structured_payload)
    except TermcfgError as error:
      print(error.reason + ": work status", file=sys.stderr)
      return error.code
  if payload is not None:
    try:
      return launch_payload(payload)
    except TermcfgError as error:
      print(error.reason + ": work enter PATH", file=sys.stderr)
      if not getattr(error, "fallback_safe", True):
        return error.code
  try:
    return fallback_shell()
  except (TermcfgError, OSError) as error:
    print("work_launch_shell_failed", file=sys.stderr)
    return error.code if isinstance(error, TermcfgError) else 5
