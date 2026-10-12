"""纯审批分类聚合；不匹配规则、不授权、不降低root或人工审批门。"""
from .schema import ConfigError


_MODES = ("human", "reviewer", "deterministic-policy")


def aggregate_approval(modes):
  """匹配器须自行将缺省规则传作human，显式空值不能混作缺省。"""
  if (type(modes) is not list or not 0 < len(modes) <= 4096
      or any(type(mode) is not str or mode not in _MODES for mode in modes)):
    raise ConfigError("pi-policy-approval-classification") from None
  return next(mode for mode in _MODES if mode in modes)
