"""验证入口的授权边界；汇总不执行宿主，执行必须指定层级。"""
import argparse
import sys
from pathlib import Path

from .pi_acceptance import read_scope, report, write_report
from .schema import ConfigError
from .storage import Conflict, Tree
from .paths import PathError, _absolute_directory
from .process import DependencyError


CASES = ("all", "migration-conflicts", "budget-permissions", "termination-recovery", "codex-receipts",
  "model-delegate-replacement", "dsh-compatibility", "taskkeeper-lifecycle", "cold-rebuild", "host-resources", "optional-services", "readseek-tools")


def parser():
  result = argparse.ArgumentParser(allow_abbrev=False)
  mode = result.add_mutually_exclusive_group(required=True)
  mode.add_argument("--tier", choices=("mock", "native", "live"))
  mode.add_argument("--report-only", action="store_true")
  mode.add_argument("--check-release", action="store_true")
  mode.add_argument("--prepare-live-project", action="store_true")
  result.add_argument("--output", type=Path, required=True)
  result.add_argument("--scope", type=Path)
  result.add_argument("--evidence-root", type=Path)
  result.add_argument("--case", choices=CASES)
  result.add_argument("--runtime", type=Path)
  result.add_argument("--home", type=Path)
  result.add_argument("--local", type=Path)
  result.add_argument("--profile")
  result.add_argument("--project", type=Path)
  result.add_argument("--native-report", type=Path)
  result.add_argument("--live-item")
  result.add_argument("--allow-host", action="store_true")
  result.add_argument("--allow-live", action="store_true")
  return result


def validate_args(args):
  if args.prepare_live_project:
    if not args.project or any((args.case, args.runtime, args.home, args.local, args.profile, args.scope, args.evidence_root,
        args.native_report, args.live_item, args.allow_host, args.allow_live)): raise ConfigError("pi-live-project-arguments")
  elif args.report_only or args.check_release:
    if not args.scope or not args.evidence_root or any((args.case, args.runtime, args.home, args.local, args.profile, args.project, args.native_report, args.live_item, args.allow_host, args.allow_live)):
      raise ConfigError("pi-verification-report-arguments")
  else:
    if not args.case or args.evidence_root: raise ConfigError("pi-verification-case-required")
    if args.tier != "live" and any((args.scope, args.native_report, args.live_item)): raise ConfigError("pi-verification-case-required")
    if args.tier == "mock" and any((args.home, args.runtime, args.local, args.profile, args.project, args.allow_host, args.allow_live)):
      raise ConfigError("pi-verification-mock-isolation")
    if args.tier == "native" and (not args.allow_host or not args.runtime or any((args.home, args.local, args.profile, args.project, args.allow_live))):
      raise ConfigError("pi-verification-native-authorization")
    if args.tier == "live" and (not args.allow_host or not args.allow_live or not args.runtime or not args.local or not args.profile or not args.project
        or not args.scope or not args.native_report or not args.live_item or args.case == "all" or args.home):
      raise ConfigError("pi-verification-live-authorization")


def main(argv=None, *, execute=None):
  try:
    args = parser().parse_args(argv); validate_args(args)
    if args.runtime is not None and (not args.runtime.is_dir() or args.runtime.is_symlink()):
      raise ConfigError("pi-verification-runtime-directory")
    with _absolute_directory(args.output.absolute().parent):
      pass
    # 拒绝覆盖发生在任何执行之前。
    if args.output.exists() or args.output.is_symlink(): raise Conflict("PI_REPORT_EXISTS")
    if args.prepare_live_project:
      from .pi_live_project import prepare_project
      value = prepare_project(args.project); code = 0
    elif args.report_only or args.check_release:
      value = report(read_scope(args.scope), args.evidence_root)
      code = 0 if args.report_only or value["release_approved"] else 1
    else:
      if execute is None:
        from .pi_validation import execute
      value = execute(args)
      from .pi_validation_report import validate_run_report
      validate_run_report(value, tier=args.tier, case=args.case)
      code = 0 if value["status"] == "passed" else 1
    write_report(args.output, value)
    return code
  except DependencyError:
    sys.stderr.write("Pi 验证所需的锁、解释器或运行包尚未就绪。\n")
    return 5
  except (ConfigError, Conflict, PathError, OSError, ValueError):
    # 不回显证据正文、参数值、私有路径或底层异常。
    sys.stderr.write("Pi 验证输入无效或无法安全保存新报告。\n")
    return 2
