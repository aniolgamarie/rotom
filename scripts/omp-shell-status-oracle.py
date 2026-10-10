"""独立退出码语法oracle：引用/转义扫描后复用冻结v2；不调用生产TS或shell。"""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("home_query_oracle", BASE / "omp-shell-review-oracle.py")
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)
MARKER = "ROTOM_STATUS_ORACLE_VALUE"
UNSUPPORTED = {"status": "unsupported", "reason": "unsupported-syntax"}


def expected_status_parse(text):
  # marker只用于独立oracle的词位映射，碰撞输入拒绝，绝不改写执行命令。
  if MARKER in text:
    return UNSUPPORTED
  protected = []
  quote = None
  i = 0
  while i < len(text):
    c = text[i]
    if c == "\\" and quote != "'":
      protected.append(text[i:i+2])
      i += 2
      continue
    if c == "#" and quote is None and (i == 0 or text[i-1] in " \t\n;|&"):
      end = text.find("\n", i)
      end = len(text) if end == -1 else end
      protected.append(text[i:end])
      i = end
      continue
    if c == quote:
      quote = None
    elif quote is None and c in "'\"":
      quote = c
    if c == "$" and text[i:i+2] == "$?" and quote != "'":
      protected.append(MARKER)
      i += 2
    else:
      protected.append(c)
      i += 1
  result = v2.expected_parse("".join(protected))
  if result["status"] != "complete":
    return result
  for command in result["commands"]:
    if any(MARKER in redirect["target"] for redirect in command.get("redirections", [])):
      return UNSUPPORTED
    positions = [i for i, arg in enumerate(command["argv"]) if MARKER in arg]
    if positions:
      if 0 in positions or command["argv"][0].rsplit("/", 1)[-1] not in {"echo", "printf"}:
        return UNSUPPORTED
      command["statusExpansions"] = positions
      command["argv"] = [arg.replace(MARKER, "$?") for arg in command["argv"]]
  return result


def build_overlay():
  fixture = BASE.parent / "tests/fixtures/omp/command-scenarios"
  raw = (fixture / "corpus.json.gz").read_bytes()
  if hashlib.sha256(raw).hexdigest() != v2.CORPUS_SHA256:
    raise ValueError("frozen corpus fingerprint changed")
  data = json.loads(gzip.decompress(raw))
  entries = []
  for row in data["records"]:
    before = v2.expected_parse(row["command"])
    after = expected_status_parse(row["command"])
    if before != after:
      if before["status"] != "unsupported" or after["status"] != "complete" or row["expectedGate"] != "human":
        raise ValueError("unexpected status delta")
      entries.append({"id": row["id"], "sourceRowSha256": hashlib.sha256(v2.canonical(row)).hexdigest(),
        "oldGate": "human", "expectedGate": "review", "fullParse": after})
  return {"schemaVersion": 1, "purpose": "fixed numeric status output eligibility; never approval",
    "sourceCorpusSha256": v2.CORPUS_SHA256,
    "sourceOracleSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "count": len(entries), "entries": entries}


if __name__ == "__main__":
  output = BASE.parent / "tests/fixtures/omp/command-scenarios/grammar-status-upgrade-20261010.json"
  output.write_text(json.dumps(build_overlay(), ensure_ascii=False, indent=2) + "\n")
  print("Generated fixed status entries: " + str(len(build_overlay()["entries"])))
