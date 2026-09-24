"""上下文与反馈只承载证据，不携带执行授权；按 UTF-8 字节作保守 token 上界。"""

from copy import deepcopy
import json
from pathlib import Path
import uuid

from .activity import digest
from .deployment import json_bytes
from .model_delegate import validate_record
from .schema import ConfigError
from .storage import Conflict, Tree


def validate_context(context):
  validate_record("context-v2", context)
  ids = [item["id"] for field in ("facts", "decisions", "hypotheses") for item in context[field]]
  if len(ids) != len(set(ids)):
    raise ConfigError("delegate-context-duplicate-id")
  return context


def trim_context(context, limit):
  validate_context(context)
  if type(limit) is not int or limit < 1:
    raise ConfigError("delegate-context-budget")
  result = deepcopy(context)
  limit = min(limit, result["budget"]["max_input_tokens"])
  result["budget"]["max_input_tokens"] = limit
  removed = {}
  # 每个UTF-8字节最多保留一个token额度，宁可少带证据也不假定所有模型都有1M窗口。
  for field in ("hypotheses", "references", "facts", "decisions"):
    while len(json_bytes(result)) > limit and result[field]:
      result[field].pop()
      removed[field] = removed.get(field, 0) + 1
      result["truncated"] = list(dict.fromkeys(context["truncated"] + [name + ":" + str(count) for name, count in removed.items()]))
  if len(json_bytes(result)) > limit:
    raise ConfigError("delegate-authoritative-context-too-large")
  return result


def import_context(root, context):
  validate_context(context)
  with Tree(Path(root), create=True) as tree:
    tree.write_immutable("contexts/" + context["artifact_id"] + ".json", json_bytes(context))
  return context["artifact_id"]


def read_context(root, artifact_id, *, cwd, candidate_digest, limit):
  if not isinstance(artifact_id, str) or not artifact_id or "/" in artifact_id or "\\" in artifact_id:
    raise ConfigError("delegate-context-id")
  with Tree(Path(root)) as tree:
    raw = tree.read("contexts/" + artifact_id + ".json", max_bytes=4 * 1024 * 1024)
  if raw is None:
    raise ConfigError("delegate-context-missing")
  context = json.loads(raw[0]); validate_context(context)
  if context["artifact_id"] != artifact_id or context["workspace"] != {"cwd": str(cwd), "candidate_digest": candidate_digest}:
    raise Conflict("DELEGATE_CONTEXT_STALE")
  return trim_context(context, limit)


def validate_feedback(feedback, context, request):
  validate_record("feedback-v2", feedback)
  validate_context(context)
  ids = [fact["id"] for fact in feedback["facts"]]
  known_ids = {fact["id"] for field in ("facts", "decisions", "hypotheses") for fact in context[field]}
  if len(ids) != len(set(ids)) or len(feedback["conflicts"]) != len(set(feedback["conflicts"])) or set(feedback["conflicts"]) - set(ids) - known_ids:
    raise ConfigError("delegate-feedback-references")
  if (feedback["run_id"] != request["run_id"] or feedback["context_artifact_id"] != context["artifact_id"]
      or feedback["turn"] != context["turn"] or feedback["candidate_digest"] != request["candidate_digest"]
      or feedback["artifact_id"] != "feedback-" + request["run_id"]):
    raise Conflict("DELEGATE_FEEDBACK_STALE")
  result = deepcopy(feedback)
  prior = {item["id"]: item for field in ("facts", "decisions", "hypotheses") for item in context[field]}
  for fact in result["facts"]:
    known = prior.get(fact["id"])
    if fact["id"] in result["conflicts"]:
      fact["status"] = "disputed"
    elif known and all(fact[key] == known[key] for key in ("text", "source")):
      fact["status"] = known["status"] if context["workspace"]["candidate_digest"] == request["candidate_digest"] else "stale"
    else:
      fact["status"] = "unverified"
  # 结构/轮次关联通过只给 provisional；模型不能把自己的新论断标成 verified。
  return result, [{"artifact_id": feedback["artifact_id"], "status": "provisional"}]


def memory_context(memory, *, task, cwd, candidate_digest, limit):
  if (not isinstance(memory, dict) or set(memory) - {"entries", "revision"} or "entries" not in memory
      or not isinstance(memory["entries"], list) or type(memory.get("revision", "1")) not in (str, int)):
    raise ConfigError("delegate-memory-format")
  groups = {"facts": [], "decisions": [], "hypotheses": []}
  identifiers = set()
  for index, entry in enumerate(memory["entries"]):
    if (not isinstance(entry, dict) or set(entry) - {"id", "text", "claim", "kind", "source", "status", "evidence"}
        or ("text" in entry) == ("claim" in entry)):
      raise ConfigError("delegate-memory-format")
    claim = entry.get("text", entry.get("claim"))
    if not isinstance(claim, str) or not claim:
      raise ConfigError("delegate-memory-format")
    kind = entry.get("kind", "fact")
    if kind not in {"fact", "decision", "hypothesis", "disputed", "finding", "lesson"}:
      raise ConfigError("delegate-memory-kind")
    identity = entry.get("id", "memory-" + str(index))
    if identity in identifiers:
      raise ConfigError("delegate-context-duplicate-id")
    identifiers.add(identity)
    status = entry.get("status", "unverified")
    if status in {"confirmed", "active"}: status = "provisional"
    if kind == "disputed": status = "disputed"
    evidence = entry.get("evidence", [])
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
      raise ConfigError("delegate-memory-evidence")
    source = entry.get("source", "; ".join(evidence) or "explicit-user-memory")
    item = {"id": identity, "text": claim, "source": source, "status": status}
    groups["decisions" if kind == "decision" else "hypotheses" if kind == "hypothesis" else "facts"].append(item)
  context = {"schema_version": 2, "artifact_id": "context-" + uuid.uuid4().hex, "task": task, "scope": [], "constraints": [],
    "workspace": {"cwd": str(cwd), "candidate_digest": candidate_digest}, **groups,
    "references": ["memory-revision:" + str(memory.get("revision", "1"))], "turn": 0, "budget": {"max_input_tokens": limit}, "truncated": []}
  validate_record("context-v2", context)
  return context


def feedback_from_result(final, context, request, candidate_digest):
  try:
    payload = json.loads(final)
  except (ValueError, UnicodeError):
    raise ConfigError("delegate-feedback-format") from None
  if not isinstance(payload, dict) or set(payload) != {"facts", "conflicts", "summary"}:
    raise ConfigError("delegate-feedback-format")
  feedback = {"schema_version": 2, "artifact_id": "feedback-" + request["run_id"], "run_id": request["run_id"],
    "context_artifact_id": context["artifact_id"], "turn": context["turn"], "candidate_digest": candidate_digest, **payload}
  return validate_feedback(feedback, context, {**request, "candidate_digest": candidate_digest})


def verify_saved_feedback(root, request, receipt, final):
  """再次获取结果时重算反馈，不能只信任收据中的 provisional 标记。"""
  if not request["feedback_required"]:
    return
  from .model_delegate import DelegationRuns
  with Tree(Path(root)) as tree:
    source = tree.read("inputs/" + DelegationRuns(Path(root) / "runs")._key(request["run_id"]))
    saved = tree.read("reports/" + request["run_id"] + "/feedback.json", max_bytes=16 * 1024 * 1024)
  try:
    if source is None or saved is None:
      raise ValueError()
    value = json.loads(source[0])
    if (value["request"] != request or value["definition_digest"] != digest({key: item for key, item in value.items() if key != "definition_digest"})):
      raise ValueError()
    expected, dispositions = feedback_from_result(final, value["context"], request, receipt["candidate_digest"])
    if json.loads(saved[0]) != expected or receipt["feedback_dispositions"] != dispositions:
      raise ValueError()
  except (ValueError, TypeError, KeyError, ConfigError):
    raise Conflict("DELEGATE_FEEDBACK_STALE") from None
