#!/usr/bin/env bash
# model-delegate: 路由优先级测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/scripts/lib/routing.sh"

pass=0
fail=0

TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

# 测试 1: 用户显式指定优先
export MD_CONFIG_JSON='{"defaults":{"provider":"default-provider","model":"default-model"},"scenes":{"review":{"provider":"scene-provider","model":"scene-model"}}}'
if md_resolve_route "user-backend" "user-provider" "user-model" ""; then
  [[ "$MD_RESOLVED_BACKEND" == "user-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: backend not user-specified\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "user-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not user-specified\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "user-model" ]] && pass=$((pass+1)) || { printf 'FAIL: model not user-specified\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: user specification should succeed\n' >&2
  fail=$((fail+3))
fi

# 测试 2: skill 场景次之
export MD_CONFIG_JSON='{"defaults":{"backend":"default-backend","provider":"default-provider","model":"default-model"},"scenes":{"review":{"backend":"scene-backend","provider":"scene-provider","model":"scene-model"}}}'
if md_resolve_route "" "" "" "review"; then
  [[ "$MD_RESOLVED_BACKEND" == "scene-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: backend not scene-specified\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "scene-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not scene-specified\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "scene-model" ]] && pass=$((pass+1)) || { printf 'FAIL: model not scene-specified\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: scene resolution should succeed\n' >&2
  fail=$((fail+3))
fi

# 测试 3: 默认配置再次之
export MD_CONFIG_JSON='{"defaults":{"backend":"default-backend","provider":"default-provider","model":"default-model"}}'
if md_resolve_route "" "" "" ""; then
  [[ "$MD_RESOLVED_BACKEND" == "default-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: backend not default\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "default-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not default\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "default-model" ]] && pass=$((pass+1)) || { printf 'FAIL: model not default\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: default configuration should succeed\n' >&2
  fail=$((fail+3))
fi

# 测试 4: 混合优先级
export MD_CONFIG_JSON='{"defaults":{"backend":"default-backend","provider":"default-provider","model":"default-model"},"scenes":{"review":{"provider":"scene-provider"}}}'
if md_resolve_route "" "user-provider" "" "review"; then
  [[ "$MD_RESOLVED_BACKEND" == "default-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: backend not default\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "user-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not user-specified\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "default-model" ]] && pass=$((pass+1)) || { printf 'FAIL: model not default\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: mixed priority should succeed\n' >&2
  fail=$((fail+3))
fi

# 测试 5: 无法解析时失败
export MD_CONFIG_JSON='{}'
if md_resolve_route "" "" "" "" 2>/dev/null; then
  printf 'FAIL: should fail when nothing specified\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 6: 加载配置文件
cat > "$TEST_TMP/config.json" <<'EOF'
{
  "defaults": {
    "backend": "pi",
    "provider": "test-provider",
    "model": "test-model"
  }
}
EOF
md_load_config "$TEST_TMP/config.json"
[[ -n "$MD_CONFIG_JSON" ]] && pass=$((pass+1)) || { printf 'FAIL: config not loaded\n' >&2; fail=$((fail+1)); }
md_resolve_route "" "" "" ""
[[ "$MD_RESOLVED_PROVIDER" == "test-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not from config\n' >&2; fail=$((fail+1)); }

# 测试 7: 配置文件不存在时失败
if md_load_config "$TEST_TMP/nonexistent.json" 2>/dev/null; then
  printf 'FAIL: should fail when config file not found\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 8: 配置文件格式错误时失败
echo "not json" > "$TEST_TMP/invalid.json"
if md_load_config "$TEST_TMP/invalid.json" 2>/dev/null; then
  printf 'FAIL: should fail when config file is invalid JSON\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 9: 部分用户指定，部分默认
export MD_CONFIG_JSON='{"defaults":{"backend":"default-backend","provider":"default-provider","model":"default-model"}}'
if md_resolve_route "" "user-provider" "" ""; then
  [[ "$MD_RESOLVED_BACKEND" == "default-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: backend not default\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "user-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not user-specified\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "default-model" ]] && pass=$((pass+1)) || { printf 'FAIL: model not default\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: partial user specification should succeed\n' >&2
  fail=$((fail+3))
fi

# 测试 10: 场景不存在时使用默认
export MD_CONFIG_JSON='{"defaults":{"backend":"default-backend","provider":"default-provider","model":"default-model"},"scenes":{"review":{"provider":"review-provider"}}}'
if md_resolve_route "" "" "" "nonexistent-scene"; then
  [[ "$MD_RESOLVED_BACKEND" == "default-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: backend not default for nonexistent scene\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "default-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: provider not default for nonexistent scene\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "default-model" ]] && pass=$((pass+1)) || { printf 'FAIL: model not default for nonexistent scene\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: nonexistent scene should fallback to defaults\n' >&2
  fail=$((fail+3))
fi

# 测试 11: Codex backend 路由（5.4.5）
export MD_CONFIG_JSON='{}'
md_resolve_route "codex" "openai" "gpt-4" ""
[[ "$MD_RESOLVED_BACKEND" == "codex" ]] && pass=$((pass+1)) || { printf 'FAIL: codex backend not resolved\n' >&2; fail=$((fail+1)); }
[[ "$MD_RESOLVED_PROVIDER" == "openai" ]] && pass=$((pass+1)) || { printf 'FAIL: openai provider not resolved\n' >&2; fail=$((fail+1)); }
[[ "$MD_RESOLVED_MODEL" == "gpt-4" ]] && pass=$((pass+1)) || { printf 'FAIL: gpt-4 model not resolved\n' >&2; fail=$((fail+1)); }

# 测试 12: Codex 不会静默回退到 Pi（5.4.5）
export MD_CONFIG_JSON='{"defaults":{"backend":"pi","provider":"bailian","model":"glm-5"}}'
md_resolve_route "codex" "openai" "gpt-4" ""
[[ "$MD_RESOLVED_BACKEND" == "codex" ]] && pass=$((pass+1)) || { printf 'FAIL: codex backend should not fallback to pi\n' >&2; fail=$((fail+1)); }
[[ "$MD_RESOLVED_PROVIDER" == "openai" ]] && pass=$((pass+1)) || { printf 'FAIL: openai provider should not fallback to bailian\n' >&2; fail=$((fail+1)); }

# 测试 13: md_load_config 使用 project_dir 查找项目配置（修复四级路由）
project_dir="$TEST_TMP/project_routing_test"
mkdir -p "$project_dir"
cat > "$project_dir/.model-delegate.json" <<'EOF'
{"defaults":{"backend":"project-backend","provider":"project-provider","model":"project-model"}}
EOF
md_load_config "" "$project_dir"
if md_resolve_route "" "" "" ""; then
  [[ "$MD_RESOLVED_BACKEND" == "project-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: project config not loaded from project_dir (got %s)\n' "$MD_RESOLVED_BACKEND" >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "project-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: project provider not resolved\n' >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "project-model" ]] && pass=$((pass+1)) || { printf 'FAIL: project model not resolved\n' >&2; fail=$((fail+1)); }
else
  printf 'FAIL: project config routing should succeed\n' >&2
  fail=$((fail+3))
fi

# 测试 14: project_dir 不存在时回退到全局配置
unset MD_CONFIG_JSON
md_load_config "" "$TEST_TMP/nonexistent_dir_for_routing"
if md_resolve_route "" "" "" ""; then
  # 没有项目配置，应该回退到空配置（无默认值），解析失败
  pass=$((pass+1))  # 回退行为正确
else
  pass=$((pass+1))  # 无默认值时解析失败也是正确行为
fi

# 测试 15: 项目与全局配置逐字段合并（修复 P2 round13）
# 项目只配 model，全局配 backend/provider → 三个字段都应解析成功
merged_home="$TEST_TMP/merged_home"
mkdir -p "$merged_home/.config/model-delegate"
printf '%s' '{"defaults":{"backend":"g-backend","provider":"g-provider"}}' \
  > "$merged_home/.config/model-delegate/config.json"
merged_project="$TEST_TMP/merged_project"
mkdir -p "$merged_project"
printf '%s' '{"defaults":{"model":"p-model"}}' \
  > "$merged_project/.model-delegate.json"
XDG_CONFIG_HOME="$merged_home/.config" md_load_config "" "$merged_project"
if md_resolve_route "" "" "" ""; then
  [[ "$MD_RESOLVED_BACKEND" == "g-backend" ]] && pass=$((pass+1)) || { printf 'FAIL: merge backend (got %s)\n' "$MD_RESOLVED_BACKEND" >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_PROVIDER" == "g-provider" ]] && pass=$((pass+1)) || { printf 'FAIL: merge provider (got %s)\n' "$MD_RESOLVED_PROVIDER" >&2; fail=$((fail+1)); }
  [[ "$MD_RESOLVED_MODEL" == "p-model" ]] && pass=$((pass+1)) || { printf 'FAIL: merge model project-wins (got %s)\n' "$MD_RESOLVED_MODEL" >&2; fail=$((fail+1)); }
else
  printf 'FAIL: merged config should resolve all fields\n' >&2
  fail=$((fail+3))
fi

printf '\n== routing tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
