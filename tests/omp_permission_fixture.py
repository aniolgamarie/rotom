"""只在临时仓库组装官方运行时与独立权限插件；不执行宿主。"""

import hashlib
import json
import re

from agentcfg.deployment import json_bytes
from agentcfg.omp_dependencies import OmpBackend
from agentcfg.omp_permission_build import permission_plugin_digest
from agentcfg.workspace import load_workspace
from test_omp_pipeline import full_workspace


def permission_workspace(tmp_path, *, profile_name="omp-validation", local_values=None, monkeypatch=None):
  original = full_workspace(tmp_path)
  repository = original.repository
  profile = repository / "profiles/omp-validation.toml"
  profile.write_text(profile.read_text().replace('plugins = ["rotom-health"]',
    'plugins = ["rotom-health", "omp-permission-control"]') + '\n'
    '[agent_options.permission_control]\ndefault_mode = "smart"\n'
    'fallback_model = "local/lfm2.5-230m"\n'
    '[agent_options.runtime.tools]\napprovalMode = "write"\n'
    '[agent_options.runtime.tools.approval]\nbash = "prompt"\npermission_bash = "allow"\n'
    'task = "prompt"\neval = "prompt"\n')
  plugin_digest = permission_plugin_digest(repository)
  catalog = repository / "agents/omp/plugins.toml"
  catalog_text = re.sub(r'(\[plugins\.omp-permission-control\][\s\S]*?entrypoints = )\[[^\n]+\]',
    r'\1["standalone.ts"]', catalog.read_text())
  catalog_text = re.sub(r'(\[plugins\.omp-permission-control\][\s\S]*?tree_digest = ")[a-f0-9]{64}(" )?',
    lambda match: match[1] + plugin_digest + (match[2] or ""), catalog_text)
  catalog.write_text(catalog_text)
  backend = OmpBackend()
  official_path = repository / "locks/omp/manifest.json"
  official = json.loads(official_path.read_bytes())
  official.pop("identity")
  if monkeypatch is not None:
    from agentcfg import omp_dependencies
    # 同步测试只消费明确的惰性哨兵，不下载或执行官方宿主。
    binary = b"SYNTHETIC OFFICIAL HOST SENTINEL: NEVER EXECUTE\n"
    digest = hashlib.sha256(binary).hexdigest()
    assets = {name: {**asset, "sha256": digest} for name, asset in omp_dependencies.ASSETS.items()}
    monkeypatch.setattr(omp_dependencies, "ASSETS", assets)
    official["assets"] = assets
    downloads = original.cache / "downloads"
    downloads.mkdir(mode=0o700, parents=True, exist_ok=True)
    (downloads / digest).write_bytes(binary)
  resources, packages, recipe = backend._resources(repository)
  official.update(resources=resources, packages=packages, recipe=recipe)
  official["identity"] = hashlib.sha256(json_bytes(official)).hexdigest()
  official_path.write_bytes(json_bytes(official))
  if local_values:
    with original.local_path.open("a") as stream:
      stream.write("\n[local_values]\n" + "\n".join(name + " = " + json.dumps(value)
        for name, value in local_values.items()) + "\n")
  workspace = load_workspace(original.local_path, profile_name, repository=repository)
  lock = backend.read_lock(repository)
  return workspace, lock, {"identity": backend.runtime_identity(workspace, lock), "pluginDigest": plugin_digest}
