"""从显式纯 Pi 基线与容忍参数生成数值工件；不采样、不验收、不授予执行权限。"""
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
import re

from .activity import digest
from .schema import ConfigError


PLATFORMS = ("linux-x86_64", "linux-arm64", "darwin-x86_64", "darwin-arm64")
IDENTITIES = ("platform_identity", "runtime_identity", "method_identity", "checker_identity", "input_identity")
ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _fail():
  raise ConfigError("pi-budget-input")


def _fields(value, fields):
  if not isinstance(value, dict) or set(value) != set(fields): _fail()


def _integer(value, minimum):
  if type(value) is not int or value < minimum: _fail()


def _number(value):
  if not isinstance(value, str) or not DECIMAL.fullmatch(value): _fail()
  return Decimal(value)


def _canonical(value):
  text = format(value, "f")
  return text.rstrip("0").rstrip(".") if "." in text else text


def _unit(value):
  if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z%][A-Za-z0-9%_./-]{0,31}", value): _fail()


def _samples(samples):
  if not isinstance(samples, list): _fail()
  counts = {"total": len(samples), "valid": 0, "failed": 0, "timeout": 0, "missing": 0}
  values = []
  for sample in samples:
    if not isinstance(sample, dict): _fail()
    status = sample.get("status")
    if status == "observed":
      _fields(sample, ("status", "value")); values.append(_number(sample["value"]))
      counts["valid"] += 1
    elif status in ("failed", "timeout", "missing"):
      _fields(sample, ("status",)); counts[status] += 1
    else: _fail()
  return values, counts


def freeze_budget(baseline, tolerances, *, revision):
  """闭合非秘密投影；调用者须在候选测量前审阅参数，摘要不能证明授权或采样真实性。"""
  _integer(revision, 1)
  _fields(baseline, ("schema_version", "profile", "platform", *IDENTITIES, "metrics"))
  _fields(tolerances, ("schema_version", "revision", "method_identity", "authorized_limits", "metrics"))
  for document in (baseline, tolerances):
    if type(document["schema_version"]) is not int or document["schema_version"] != 1: _fail()
  _integer(tolerances["revision"], 1)
  if baseline["profile"] != "pure-pi" or baseline["platform"] not in PLATFORMS: _fail()
  for name in IDENTITIES:
    if not isinstance(baseline[name], str) or not re.fullmatch("[0-9a-f]{64}", baseline[name]): _fail()
  if tolerances["method_identity"] != baseline["method_identity"]: _fail()
  limits = tolerances["authorized_limits"]
  _fields(limits, ("max_model_calls", "max_cost", "currency"))
  _integer(limits["max_model_calls"], 0); cost = _number(limits["max_cost"])
  if not isinstance(limits["currency"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", limits["currency"]): _fail()
  metrics, rules = baseline["metrics"], tolerances["metrics"]
  if not isinstance(metrics, dict) or not metrics or not isinstance(rules, dict) or set(metrics) != set(rules): _fail()
  output = {}
  for name, measured in metrics.items():
    if not isinstance(name, str) or not ID.fullmatch(name): _fail()
    _fields(measured, ("unit", "samples", "warmup_samples")); _unit(measured["unit"])
    rule = rules[name]
    _fields(rule, ("unit", "direction", "statistic", "min_valid_samples", "max_failed_samples", "absolute_delta", "relative_delta", "authorized_limit"))
    _unit(rule["unit"])
    if rule["unit"] != measured["unit"] or rule["direction"] not in ("upper", "lower") or rule["statistic"] not in ("median", "max", "p95"): _fail()
    _integer(rule["min_valid_samples"], 1); _integer(rule["max_failed_samples"], 0)
    absolute, relative, authorized = (_number(rule[key]) for key in ("absolute_delta", "relative_delta", "authorized_limit"))
    if rule["direction"] == "lower" and relative > 1: _fail()
    values, formal = _samples(measured["samples"])
    _, warmup = _samples(measured["warmup_samples"])
    if not formal["total"] or formal["valid"] < rule["min_valid_samples"] or sum(formal[key] for key in ("failed", "timeout", "missing")) > rule["max_failed_samples"]: _fail()
    if rule["statistic"] == "p95" and len(values) < 20: _fail()
    values.sort()
    # 根据输入有效位数扩大局部精度，不使用默认 28 位舍入阈值。
    numbers = (*values, absolute, relative, authorized)
    precision = (max(0, *(value.adjusted() for value in numbers)) - min(0, *(value.as_tuple().exponent for value in numbers)) + 1) * 4 + 32
    with localcontext() as context:
      context.prec = precision; context.Emax = MAX_EMAX; context.Emin = MIN_EMIN
      if rule["statistic"] == "max": statistic = values[-1]
      elif rule["statistic"] == "p95": statistic = values[(95 * len(values) + 99) // 100 - 1]
      else:
        middle = len(values) // 2
        statistic = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
      if rule["direction"] == "upper":
        bounds = [statistic + absolute, authorized]
        if statistic != 0: bounds.append(statistic * (1 + relative))
        threshold = min(bounds)
      else:
        bounds = [max(Decimal(0), statistic - absolute), authorized]
        if statistic != 0: bounds.append(statistic * (1 - relative))
        threshold = max(bounds)
    output[name] = {"unit": rule["unit"], "direction": rule["direction"], "statistic": rule["statistic"],
      "baseline_stat": _canonical(statistic), "threshold": _canonical(threshold), "authorized_limit": _canonical(authorized), "formal": formal, "warmup": warmup}
  return {"schema_version": 1, "revision": revision, "profile": baseline["profile"], "platform": baseline["platform"],
    **{name: baseline[name] for name in IDENTITIES}, "baseline_digest": digest(baseline), "tolerances_digest": digest(tolerances),
    "tolerances_revision": tolerances["revision"], "authorized_limits": {"max_model_calls": limits["max_model_calls"], "max_cost": _canonical(cost), "currency": limits["currency"]},
    "metrics": output}
