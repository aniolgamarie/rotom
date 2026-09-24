"""worker 启动前的封闭描述符与所选 provider 投影；不读取账号文件。"""

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from .activity import digest
from .pi_catalog import validate
from .pi_supervisor import closed
from .schema import ConfigError
from .secrets import CredentialError
from .storage import Conflict


def validate_descriptor(descriptor, lease, owner, runtime_identity, *, allow_revoked=False):
  validate("managed-descriptor", descriptor)
  if (any(descriptor[key] != owner[key] for key in ("instance_id", "manager_activation_id", "owner_nonce"))
      or any(descriptor[key] != lease[key] for key in ("allocation_id", "attempt_id", "task_id", "policy_digest", "workspace_write_lease_ids"))
      or (descriptor["grant_generation"] > lease["grant_generation"] if allow_revoked else descriptor["grant_generation"] != lease["grant_generation"])
      or descriptor["runtime_digest"] != runtime_identity or descriptor["snapshot_digest"] != lease["candidate_digest"]):
    raise Conflict("WORKER_BINDING_MISMATCH")


def selected_api_models(models, provider_id, model_id, inherited_environment, *, supported_apis=("openai-completions",)):
  """多个执行路径复用精确模型和环境凭据投影，绝不复制其他 provider。"""
  provider = models.get("providers", {}).get(provider_id)
  if not isinstance(provider, dict):
    raise ConfigError("pi-managed-api-key-provider-required")
  closed(provider, ("api", "baseUrl", "apiKey", "models"))
  if provider["api"] not in supported_apis or not isinstance(provider["apiKey"], str) or not re.fullmatch(r"\$AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16}", provider["apiKey"]):
    raise ConfigError("pi-managed-provider-unsupported")
  if not isinstance(provider["models"], list) or any(not isinstance(model, dict) for model in provider["models"]):
    raise ConfigError("pi-managed-models-invalid")
  selected = [model for model in provider["models"] if model.get("id") == model_id]
  if len(selected) != 1:
    raise ConfigError("pi-managed-model-ambiguous")
  closed(selected[0], ("id", "input"), ("contextWindow", "maxTokens", "reasoning", "thinkingLevelMap"))
  variable = provider["apiKey"][1:]
  secret = inherited_environment.get(variable)
  if not secret:
    raise CredentialError()
  result = deepcopy(provider)
  result["models"] = deepcopy(selected)
  return {"providers": {provider_id: result}}, {variable: secret}


def scoped_models(models, descriptor, manifest, inherited_environment):
  """受管路径另外校验声明角色，不能用普通委托绕过 managed 身份。"""
  roles = manifest["role_bindings"]
  role = roles.get(descriptor["role_id"])
  if not role or role["managed"] is not True or role["tools"] != descriptor["allowed_tools"] or role["model"] != {"provider": descriptor["provider_id"], "model": descriptor["model_id"]}:
    raise Conflict("WORKER_ROLE_MISMATCH")
  return selected_api_models(models, descriptor["provider_id"], descriptor["model_id"], inherited_environment)


def validate_context(context, descriptor, manifest, instance_root, read_role):
  closed(context, ("schema_version", "manager_run_id", "lease_id", "prompt", "role", "model", "route", "root_bindings", "artifacts", "result_schema", "database", "minimum_remaining"))
  if type(context["minimum_remaining"]) is not int or context["minimum_remaining"] < 0:
    raise ConfigError("pi-request-reserve")
  closed(context["role"], ("id", "digest", "definition", "system_prompt", "tools"))
  closed(context["model"], ("provider_id", "model_id", "model_digest", "api"))
  closed(context["route"], ("id", "type", "base_url", "proxy_url"))
  closed(context["database"], ("root", "filename", "owner"))
  closed(context["database"]["owner"], ("scopeId", "token", "epoch"))
  if not manifest["options"].get("task_keeper", {}).get("enabled"):
    raise Conflict("MANAGED_WORKFLOWS_DISABLED")
  expected_database = Path(instance_root) / "pi-home/task-keeper"
  if (context["schema_version"] != 1 or context["lease_id"] != descriptor["allocation_id"]
      or context["role"]["id"] != descriptor["role_id"] or context["role"]["digest"] != descriptor["role_digest"]
      or context["role"]["tools"] != descriptor["allowed_tools"]
      or context["model"] != {"provider_id": descriptor["provider_id"], "model_id": descriptor["model_id"], "model_digest": descriptor["model_digest"], "api": "openai-completions"}
      or context["database"]["root"] != str(expected_database) or context["database"]["filename"] != "runtime.db"
      or digest(context["result_schema"]) != descriptor["result_schema_digest"]):
    raise Conflict("WORKER_BINDING_MISMATCH")
  definition = read_role(descriptor["role_id"])
  if (not isinstance(context["role"]["definition"], str) or definition != context["role"]["definition"].encode()
      or hashlib.sha256(definition).hexdigest() != descriptor["role_digest"]):
    raise Conflict("WORKER_ROLE_MISMATCH")
  route = manifest["options"].get("network", {}).get("routes", {}).get(descriptor["route_id"])
  logical_provider = descriptor["provider_id"].removeprefix("agentcfg-")
  if (not route or logical_provider not in route["provider_ids"] or context["route"]["id"] != descriptor["route_id"]
      or context["route"]["type"] != route["mode"] or context["route"]["proxy_url"] != route.get("proxy_url")):
    raise Conflict("WORKER_ROUTE_MISMATCH")
  return route
