"""现代生成包的自有core来源核；不能用生成副本独立演进业务源码。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess


def compile_sources(rows):
  """仅固定Node24公开类型转换；不加载SDK、资源或原业务模块。"""
  node = Path(shutil.which("node") or "").resolve(strict=True)
  with node.open("rb") as stream: tool_digest = hashlib.file_digest(stream, "sha256").hexdigest()
  script = '''import {stripTypeScriptTypes} from "node:module";import fs from "node:fs";
const rows=JSON.parse(fs.readFileSync(0,"utf8"));
if(process.version!=="v24.14.0")throw Error("fixed-node-version");
process.stdout.write(JSON.stringify({version:process.version,files:rows.map(row=>({path:row.path,
 text:row.typescript?stripTypeScriptTypes(row.text,{mode:"transform",sourceMap:false}):row.text}))}));'''
  payload = json.dumps(rows).encode()
  if len(payload) > 16 * 1024 * 1024: raise ValueError()
  result = subprocess.run([str(node), "--input-type=module", "-e", script], input=payload,
    capture_output=True, timeout=30, check=True, env={})
  if len(result.stdout) > 16 * 1024 * 1024 or len(result.stderr) > 65536: raise ValueError()
  reply = json.loads(result.stdout)
  if set(reply) != {"version", "files"} or reply["version"] != "v24.14.0" or len(reply["files"]) != len(rows): raise ValueError()
  outputs = {}
  for expected, item in zip(rows, reply["files"]):
    if type(item) is not dict or set(item) != {"path", "text"} or item["path"] != expected["path"] or type(item["text"]) is not str: raise ValueError()
    outputs[item["path"]] = item["text"].encode()
  return outputs, {"name": "node", "version": "v24.14.0", "sha256": tool_digest,
    "api": "node:module.stripTypeScriptTypes", "mode": "transform"}


def transformed_text(raw, target):
  text = raw.decode("utf8")
  def translate(match):
    module = match.group(2)
    relative = posixpath.relpath("runtime/" + module + ".mjs", posixpath.dirname(target))
    return match.group(1) + (relative if relative.startswith(".") else "./" + relative) + match.group(3)
  text = re.sub(r'''(["'])@agentcfg/pi-runtime/([a-z][a-z0-9-]+)(["'])''', translate, text)
  return re.sub(r'''(["'])(\.{1,2}/[^"']+)\.ts\1''', lambda m: m[1] + m[2] + ".mjs" + m[1], text)

from .schema import ConfigError
from .storage import Tree


def verify_generated(repository, source_path):
  failed = False
  try:
    if source_path != "agents/pi/packages/task-keeper-modern": raise ValueError()
    with Tree(Path(repository), private=False) as tree:
      raw = tree.read(source_path + "/core-source-manifest.json", max_bytes=1024 * 1024)
      document = json.loads(raw[0])
      if (type(document) is not dict or set(document) != {"schema_version", "transform", "compiler", "files"}
          or document["schema_version"] != 2 or document["transform"] != "own-runtime-node24-transform"): raise ValueError()
      rows = document["files"]
      if type(rows) is not list or not 1 <= len(rows) <= 256: raise ValueError()
      names = set(); total = 0; inputs = []; captured = []
      for row in rows:
        if type(row) is not dict or set(row) != {"source", "path", "source_sha256", "sha256", "size"}: raise ValueError()
        source, target = row["source"], row["path"]
        if (type(source) is not str or type(target) is not str or target in names or ".." in PurePosixPath(target).parts
            or PurePosixPath(target).is_absolute() or str(PurePosixPath(target)) != target
            or not (source.startswith(("agents/pi/packages/task-keeper/", "agents/pi/runtime/"))
              or source in (source_path + "/index.ts", source_path + "/core.ts"))): raise ValueError()
        names.add(target)
        if type(row["size"]) is not int or not 0 <= row["size"] <= 256 * 1024: raise ValueError()
        total += row["size"]
        if total > 8 * 1024 * 1024: raise ValueError()
        original = tree.read(source, max_bytes=256 * 1024)
        produced = tree.read(source_path + "/" + target, max_bytes=256 * 1024)
        if original is None or produced is None: raise ValueError()
        if hashlib.sha256(original[0]).hexdigest() != row["source_sha256"]: raise ValueError()
        inputs.append({"path": target, "text": transformed_text(original[0], target), "typescript": source.endswith(".ts")})
        captured.append((row, produced[0]))
      outputs, compiler = compile_sources(inputs)
      if compiler != document["compiler"]: raise ValueError()
      for row, produced in captured:
        output = outputs[row["path"]]
        if output != produced or len(output) != row["size"] or hashlib.sha256(output).hexdigest() != row["sha256"]: raise ValueError()
  except Exception: failed = True
  if failed: raise ConfigError("pi-task-keeper-generated-source") from None
