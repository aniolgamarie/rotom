#!/usr/bin/env python3
"""复制单一自有TK core与精确runtime闭包；生成包不是另一份业务源码权威。"""
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys

_ROOT = Path(__file__).resolve().parents[1]
_TARGET = _ROOT / "agents/pi/packages/task-keeper-modern"
_CORE = _ROOT / "agents/pi/packages/task-keeper"
_IMPORTS = re.compile(r'''(?m)^(?:import(?!\s+type\b)|export)\s+[^;]*?from\s+["']([^"']+)["']''')
_URLS = re.compile(r'''new URL\(["']([^"']+)["'], import\.meta\.url\)''')
sys.path.insert(0, str(_ROOT / "src"))
from agentcfg.pi_task_keeper_sources import compile_sources, transformed_text

def regenerate():
  pending = [(_CORE / "src/orchestration/service-core.ts", "src/orchestration/service-core.ts"),
    (_CORE / "src/store/database.ts", "src/store/database.ts"), (_CORE / "src/config.ts", "src/config.ts"),
    (_TARGET / "core.ts", "core.ts"), (_TARGET / "index.ts", "index.ts"),
    (_CORE / "config.schema.json", "config.schema.json")]
  captured = {}; total = 0
  while pending:
    source, target = pending.pop()
    if target in captured: continue
    if len(captured) >= 256 or source.is_symlink() or not source.is_file(): raise ValueError("task-core-source-invalid:" + str(source.relative_to(_ROOT)))
    if not source.is_relative_to(_ROOT): raise ValueError("task-core-source-invalid")
    raw = source.read_bytes(); total += len(raw)
    if len(raw) > 256 * 1024 or total > 8 * 1024 * 1024: raise ValueError("task-core-source-capacity")
    text = raw.decode("utf8")
    translations = {}
    if source.suffix in (".ts", ".js", ".mjs"):
      for name in [*_IMPORTS.findall(text), *(n for n in _URLS.findall(text) if Path(n).suffix)]:
        if name.startswith("node:") or name in ("ajv", "typebox"): continue
        if name.startswith("@agentcfg/pi-runtime/"):
          module = name.removeprefix("@agentcfg/pi-runtime/")
          if not re.fullmatch(r"[a-z][a-z0-9-]+", module): raise ValueError("task-core-import-invalid")
          child = _ROOT / "agents/pi/runtime" / (module + ".ts")
          destination = "runtime/" + module + ".ts"
          translated = posixpath.relpath(destination, posixpath.dirname(target))
          translations[name] = translated if translated.startswith(".") else "./" + translated
        elif name.startswith("."):
          child = (source.parent / name).resolve()
          if child.is_relative_to(_TARGET / "src"):
            child = _CORE / child.relative_to(_TARGET)
          destination = posixpath.normpath(posixpath.join(posixpath.dirname(target), name))
          if destination.startswith("../"): raise ValueError("task-core-import-invalid")
        else: raise ValueError("task-core-import-unsupported")
        pending.append((child, destination))
    for name, translated in translations.items():
      text = text.replace('"' + name + '"', '"' + translated + '"').replace("'" + name + "'", "'" + translated + "'")
    captured[target] = (source, raw)
  compiled_input = [{"path": target.removesuffix(".ts") + ".mjs" if target.endswith(".ts") else target,
    "text": transformed_text(raw, target), "typescript": source.suffix == ".ts"}
    for target, (source, raw) in sorted(captured.items())]
  outputs, compiler = compile_sources(compiled_input)
  old = _TARGET / "core-source-manifest.json"
  if old.exists():
    # 只移除上轮本generator登记的副本；canonical与其他作者内容不碰。
    for row in json.loads(old.read_text())["files"]:
      name = row["path"]
      if name not in ("core.ts", "index.ts") and name.endswith(".ts"):
        (_TARGET / name).unlink(missing_ok=True)
  rows = []
  for target, (source, raw) in sorted(captured.items()):
    target = target.removesuffix(".ts") + ".mjs" if target.endswith(".ts") else target
    output = outputs[target]
    destination = _TARGET / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)
    rows.append({"source": source.relative_to(_ROOT).as_posix(), "path": target, "source_sha256": hashlib.sha256(raw).hexdigest(),
      "sha256": hashlib.sha256(output).hexdigest(), "size": len(output)})
  (_TARGET / "core-source-manifest.json").write_text(json.dumps({"schema_version": 2, "transform": "own-runtime-node24-transform", "compiler": compiler, "files": rows}, indent=2) + "\n")
  return rows

if __name__ == "__main__":
  rows = regenerate()
  print(json.dumps({"files": len(rows), "bytes": sum(row["size"] for row in rows)}))
