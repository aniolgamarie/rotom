"""独立v2静态测试oracle：只生成固定583行差量，不调用TS、生产解析器或shell。"""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("frozen_shell_oracle", BASE / "omp-shell-test-oracle.py")
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)
tokens = v1.tokens
CONTROL, SHELLS, INTERPRETERS, REDIRECTS = v1.CONTROL, v1.SHELLS, v1.INTERPRETERS, v1.REDIRECTS
sed_has_execution = v1.sed_has_execution
CORPUS_SHA256 = "d6e5dc5d68c685d44949a0487f7ff71bd60b28daad228c20ec8070d39a710699"
GATE_OVERLAY_SHA256 = "6eb218c0466bdec66386564f9021b7f26ab819c5c70ef9bba86f46c454395ded"
REASONS = {
  "HOME": "普通参数的裸~或~/路径仅记录HOME位置和原文，不解析机器HOME；命令头及重定向目标仍人工处理。",
  "query": "只有内建command的-v/-V且非空静态名称是只读查询；执行wrapper、路径同名程序和动态名称仍人工处理。",
  "HOME+query": "普通HOME参数与只读command查询在简单命令组合中分别保留完整argv、连接符、glob和重定向顺序。",
}


def word(raw):
  # 引用和转义使用冻结v1的shlex工具；只独立增加前导HOME的静态标记。
  quote = None
  meaningful = False
  home = False
  protected = []
  i = 0
  while i < len(raw):
    c = raw[i]
    if c == "\\" and quote != "'":
      protected.append(raw[i:i+2])
      if raw[i+1:i+2] != "\n":
        meaningful = True
      i += 2
      continue
    if quote:
      if c == quote:
        quote = None
      protected.append(c)
    elif c in "'\"":
      quote = c
      meaningful = True
      protected.append(c)
    elif c == "~":
      # named-user/~+/~-及词中~保持边界，~/之后的~只是路径后缀字符。
      if home and raw.startswith("~/"):
        protected.append("\\~")
      elif meaningful or raw[i+1:i+2] not in {"", "/"}:
        raise ValueError("HOME outside ordinary static prefix")
      else:
        home = True
        meaningful = True
        protected.append("\\~")
    else:
      meaningful = True
      protected.append(c)
    i += 1
  value, glob = v1.word("".join(protected))
  return (raw if home else value), glob, home


def expected_parse(text):
  unsupported = {"status": "unsupported", "reason": "unsupported-syntax"}
  if not text or re.search(r"[\r\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
    return unsupported
  try:
    ts = [t for t in tokens(text) if t[0] != "comment" and not (t[0] == "word" and not t[1].replace("\\\n", ""))]
    commands = []
    argv = []
    globs = []
    homes = []
    redirects = []
    connector = "start"
    need_word = False

    def flush():
      head = argv[0].rsplit("/", 1)[-1] if argv else ""
      # 内建查询只读；路径同名命令、执行wrapper、动态名称仍不认可。
      first_name = 3 if len(argv) > 2 and argv[2] == "--" else 2
      query = (len(argv) > first_name and argv[0] == "command" and argv[1] in {"-v", "-V"}
        and not globs and not homes
        and all(name and (first_name == 3 or not name.startswith("-")) for name in argv[first_name:]))
      if not argv or (head in CONTROL and not query) or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]) or 0 in globs or 0 in homes:
        raise ValueError("unsupported command boundary")
      if (head in SHELLS and any(re.match(r"-[A-Za-z]*c", a) or a == "--command" or a.startswith("--command=") for a in argv[1:])) or (head in INTERPRETERS and any(a.startswith(("-c", "-e")) or a in {"--eval", "--command"} or re.match(r"--(?:eval|command)=", a) for a in argv[1:])):
        raise ValueError("embedded program")
      if head == "find" and any(a in {"-exec", "-execdir", "-ok", "-okdir"} for a in argv):
        raise ValueError("find command execution")
      if head in {"awk", "gawk", "mawk", "nawk"} and any(re.search(r"system\s*\(|\||@", a) or re.match(r"-(?:f|l|E)", a) or a in {"--file", "--load", "--exec"} or re.match(r"--(?:file|load|exec)=", a) for a in argv[1:]):
        raise ValueError("awk command execution")
      if head == "sed" and sed_has_execution(argv[1:]):
        raise ValueError("sed command execution")
      item = {"connector": connector, "argv": list(argv)}
      if globs:
        item["globs"] = list(globs)
      if homes:
        item["homeExpansions"] = list(homes)
      if redirects:
        item["redirections"] = list(redirects)
      commands.append(item)
      argv.clear()
      globs.clear()
      homes.clear()
      redirects.clear()

    i = 0
    while i < len(ts):
      kind, raw, start, end = ts[i]
      fd = None
      if kind == "word" and re.fullmatch(r"\d+", raw) and i+1 < len(ts) and end == ts[i+1][2] and ts[i+1][1] in REDIRECTS:
        fd = int(raw)
        i += 1
        kind, raw, start, end = ts[i]
      if kind == "operator" and raw in REDIRECTS:
        if i+1 >= len(ts) or ts[i+1][0] != "word":
          raise ValueError("missing redirect target")
        target, glob, home = word(ts[i+1][1])
        if not target or glob or home or (raw in {">&", "<&"} and not re.fullmatch(r"\d+|-", target)):
          raise ValueError("dynamic redirect")
        source = fd if fd is not None else (0 if raw.startswith("<") else 1)
        if source > 9 or (raw in {">&", "<&"} and target != "-" and int(target) > 9):
          raise ValueError("unsupported descriptor")
        redirects.append({"fd": source, "operator": raw, "target": target})
        i += 2
        continue
      if kind == "operator":
        if raw not in {";", "\n", "&&", "||", "|"}:
          raise ValueError("unsupported operator")
        if not argv:
          if raw == "\n" and not redirects:
            i += 1
            continue
          raise ValueError("empty command")
        flush()
        connector = ";" if raw == "\n" else raw
        need_word = raw in {"&&", "||", "|"}
      else:
        value, glob, home = word(raw)
        if glob:
          globs.append(len(argv))
        if home:
          homes.append(len(argv))
        argv.append(value)
        need_word = False
      i += 1
    if argv:
      flush()
    elif redirects or need_word:
      raise ValueError("incomplete command")
    return {"status": "complete", "commands": commands} if commands else unsupported
  except (ValueError, IndexError):
    return unsupported


def canonical(value):
  return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def build_overlay():
  fixture_dir = BASE.parent / "tests/fixtures/omp/command-scenarios"
  source = (fixture_dir / "corpus.json.gz").read_bytes()
  if hashlib.sha256(source).hexdigest() != CORPUS_SHA256:
    raise ValueError("frozen corpus fingerprint changed")
  corpus = json.loads(gzip.decompress(source))
  frozen = json.loads((fixture_dir / "grammar-upgrade-20261009.json").read_text())
  if (hashlib.sha256(canonical(frozen)).hexdigest() != GATE_OVERLAY_SHA256 or
      frozen["sourceCorpusSha256"] != CORPUS_SHA256 or len(frozen["entries"]) != 583):
    raise ValueError("unexpected frozen gate overlay")
  rows = {row["id"]: row for row in corpus["records"]}
  entries = []
  for ref in frozen["entries"]:
    row = rows[ref["id"]]
    if hashlib.sha256(canonical(row)).hexdigest() != ref["sourceRowSha256"]:
      raise ValueError("original row fingerprint changed")
    result = expected_parse(row["command"])
    if row["expected"]["status"] != "unsupported" or result["status"] != "complete":
      raise ValueError("independent oracle does not endorse frozen delta: " + ref["id"])
    entries.append({"id": ref["id"], "sourceRowSha256": ref["sourceRowSha256"],
      "category": ref["category"], "reason": REASONS[ref["category"]], "fullParse": result})
  if len({entry["id"] for entry in entries}) != 583:
    raise ValueError("duplicate frozen delta")
  return {"schemaVersion": 1, "oracleVersion": 2, "purpose": "fixed independent full-parse delta; syntax eligibility is never approval",
    "sourceCorpusSha256": CORPUS_SHA256,
    "sourceCorpusCanonicalSha256": hashlib.sha256(canonical(corpus)).hexdigest(),
    "sourceGateOverlaySha256": hashlib.sha256(canonical(frozen)).hexdigest(),
    "sourceOracleSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "sourceRowDigestMethod": "sha256 canonical recursively sorted original parsed row JSON",
    "counts": {"HOME": 501, "query": 74, "HOME+query": 8}, "entries": entries}


if __name__ == "__main__":
  output = BASE.parent / "tests/fixtures/omp/command-scenarios/grammar-parse-upgrade-20261009.json"
  output.write_text(json.dumps(build_overlay(), ensure_ascii=False, indent=2) + "\n")
  print("Generated 583 fixed independent full-parse entries: " + str(output))
