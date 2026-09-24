#!/usr/bin/env python3
"""Render test DESIGN only. Does not execute Pi/tests, synchronize config, or mint runtime evidence."""
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[1]
ROOT = PKG.parents[2]
DEFERRED = {'T66', 'T68', 'T69'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def row_digest(row):
    return hashlib.sha256(canonical(row).encode()).hexdigest()


def read_sources():
    rows = {}
    for kind, file in [('scenario', 'scenario-test-matrix.csv'), ('fault', 'fault-traceability.csv')]:
        for row in csv.DictReader((PKG / 'tests/plan' / file).open()):
            identity = row.get('scenario_id', row.get('id'))
            if identity in rows:
                raise ValueError('Duplicate source ID: ' + identity)
            rows[identity] = (kind, file, row)
    return rows


def render():
    recipes = json.loads((HERE / 'case-recipes.json').read_text())
    profiles = json.loads((HERE / 'layer-profiles.json').read_text())
    matrices = json.loads((HERE / 'expanded-matrices.json').read_text())
    checkpoint = json.loads((HERE / 'current-checkpoint.json').read_text())
    baseline = json.loads((HERE / 'baseline.json').read_text())
    baseline_rows = {r['obligation']: r for r in csv.DictReader((HERE / 'gap-obligations.csv').open())}
    by_id = {}
    for recipe in recipes:
        for identity in recipe['ids']:
            if identity in by_id:
                raise ValueError('Duplicate recipe ID: ' + identity)
            by_id[identity] = recipe
    sources = read_sources()
    if set(sources) != set(by_id):
        raise ValueError('Recipe/source ID mismatch')
    cases = []
    full_missing = set(checkpoint['fullMissing'])
    for identity, (kind, file, source) in sources.items():
        recipe = by_id[identity]
        for layer in source['required_layers'].split(';'):
            key = f'{identity}:{layer}'
            case_id = f'TC-{identity}-{layer}'
            profile = profiles[layer]
            origin = baseline_rows.get(key)
            applicable_matrices = [m for m in matrices if recipe['id'] in m['campaigns'] and layer in m['layers']]
            variants = ['primary', 'positive-control', 'negative-control'] + [c['id'] for c in recipe['checks']]
            for matrix in applicable_matrices:
                variants += [matrix['id'] + '.' + c['id'] for c in matrix['cases']]
            trigger = source.get('when', source.get('injection'))
            assertion = {'assertionId': case_id + '.primary', 'obligation': key,
                         'input': trigger, 'predicate': source['expected'],
                         'observer': profile['observer'], 'artifact': '<run>/' + case_id + '/assertions.json'}
            cases.append(dict(
                obligation=key, case_id=case_id, source=kind, source_file=file,
                source_title=source.get('scenario', source.get('injection')),
                source_digest=row_digest(source), scenario_digest=source.get('spec_digest', ''),
                level=layer, release_scope='P4-deferred-online' if identity in DEFERRED else 'P0-P3',
                campaign=recipe['id'], wave=recipe['wave'],
                phase_gate=source.get('phase_gates', source.get('release_gate')),
                implementation_tasks=source.get('implementation_tasks', source.get('task_groups')),
                test_families=source['test_families'], reference_ids=recipe['refs'],
                production_targets=';'.join(recipe['targets']),
                proposed_file=f"tests/cases-{recipe['id'].lower()}-{layer.lower()}.test.ts",
                proposed_name=f'[{layer} {identity}] {case_id} ' + source.get('scenario', source.get('injection')),
                baseline_case=origin['case_id'] if origin else '',
                baseline_design='existing-435-design' if origin else 'new-detailed-design',
                evidence_at_checkpoint='missing' if key in full_missing else 'credited-at-checkpoint-needs-regression',
                newly_uncredited='yes' if key in checkpoint['newlyUncreditedComparedWithBaseline'] else 'no',
                existing_candidate_files=origin['existing_candidate_files'] if origin else '',
                fixture=recipe['fixtures'], given_when=trigger,
                procedure=' '.join(f'{i + 1}. {step}' for i, step in enumerate(profile['steps']))
                          + ' 领域场景：' + recipe['steps'].replace('/ orch', '/orch')
                          + ' 层级适配优先：U/S只对上述场景的规则输入或事件轨迹做断言；真实I/O另在A/P/E执行。',
                expected_assertions=source['expected'], assertion_contract=canonical(assertion),
                independent_oracles=profile['observer'], positive_control=recipe['positive_control'],
                negative_control=recipe['negative'], required_variants=';'.join(variants),
                variant_design=canonical(recipe['checks']), matrix_refs=';'.join(m['id'] for m in applicable_matrices),
                artifact_contract=';'.join('<run>/' + case_id + '/' + f for f in profile['artifacts']),
                layer_limit=profile['forbidden'], timeout=profile['timeout'],
                dependency=recipe['blocker'],
                disposition='deferred-P4' if identity in DEFERRED else 'needs-live-binding' if layer == 'L' else 'offline-design',
                design_status='designed', implementation_status='not-claimed-by-design',
                execution_status='not-executed-as-designed', result_artifact='',
            ))
    return cases, recipes, profiles, matrices, checkpoint, baseline


def csv_text(rows):
    import io
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def write_outputs():
    cases, recipes, profiles, matrices, checkpoint, baseline = render()
    release_missing = set(checkpoint['releaseMissing'])
    selected = [r for r in cases if r['obligation'] in release_missing]
    additional = [r for r in selected if r['newly_uncredited'] == 'yes']
    (HERE / 'coverage-cases.csv').write_text(csv_text(cases))
    (HERE / 'current-gap-cases.csv').write_text(csv_text(selected))
    (HERE / 'newly-uncredited-cases.csv').write_text(csv_text(additional))
    md = ['# 完整测试 case 设计（v2）', '',
          '本文件与 CSV 由 `build-design.py` 从手工审阅的领域配方、层级规则和组合矩阵生成。生成登记不生成运行证据。', '',
          f'覆盖全部 {len(cases)} 项义务：707 项 P0–P3、6 项 P4 延期；其中当前 P0–P3 缺口 {len(selected)} 项、新暴露缺口 {len(additional)} 项。', '',
          '逐义务的原 WHEN/THEN、source digest、case ID、文件/名称、断言、步骤与必测变体均在 [coverage-cases.csv](coverage-cases.csv)。'
          '只看当前缺口用 [current-gap-cases.csv](current-gap-cases.csv)，只看新增 220 项用 [newly-uncredited-cases.csv](newly-uncredited-cases.csv)。', '',
          '适用规则：原场景主断言必须单独成立；同一批次的检查不能自动给其他场景计分。正例、负向对照与本层级适用的全部变体均需执行。'
          '共享组合矩阵按稳定 ID 展开，不使用 pairwise 省略高风险交叉。原规范要求的成功行为若缺实现，保持待办，不能用拒绝测试代替。', '',
          '## 分层执行与边界', '']
    for layer, profile in profiles.items():
        md += [f'### {layer} — {profile["title"]}', '']
        md += [f'{i + 1}. {step}' for i, step in enumerate(profile['steps'])]
        md += ['', '**独立观测：** ' + profile['observer'], '', '**不能替代：** ' + profile['forbidden'], '', '**时限：** ' + profile['timeout'], '']
    md += ['## 高风险组合的完整展开', '']
    for matrix in matrices:
        md += [f'### {matrix["id"]} — {len(matrix["cases"])} 个组合', '',
               f'批次：{", ".join(matrix["campaigns"])}；层级：{", ".join(matrix["layers"])}。{matrix["scope_note"]}', '',
               '| 组合 ID | 输入／切点 | 预期 |', '|---|---|---|']
        md += [f'| {c["id"]} | {c["input"]} | {c["expected"]} |' for c in matrix['cases']]
        md += ['']
    md += ['## 领域测试配方', '']
    for recipe in recipes:
        members = [r for r in cases if r['campaign'] == recipe['id']]
        md += [f'### {recipe["id"]} — {recipe["title"]}', '',
               f'义务数：{len(members)}；当前 P0–P3 缺口：{sum(r["obligation"] in release_missing for r in members)}。', '',
               '**ID：** ' + ', '.join(recipe['ids']), '', '**参考：** ' + recipe['refs'], '',
               '**生产接口检查位置：** ' + '; '.join('`' + x + '`' for x in recipe['targets']), '',
               '**夹具：** ' + recipe['fixtures'], '', '**领域步骤（按上面的层级规则执行）：** ' + recipe['steps'], '',
               '**成功对照：** ' + recipe['positive_control'], '', '**负向对照：** ' + recipe['negative'], '',
               '**实现依赖：** ' + recipe['blocker'], '', '| 检查 ID | 输入变化 | 独立预期 |', '|---|---|---|']
        md += [f'| {c["id"]} | {c["input"]} | {c["expected"]} |' for c in recipe['checks']]
        md += ['', '**精确义务索引：** ' + ', '.join(r['obligation'] for r in members), '']
    (HERE / 'case-design.md').write_text('\n'.join(md) + '\n')
    print(json.dumps({'all': len(cases), 'release': sum(r['release_scope'] == 'P0-P3' for r in cases),
                      'current_gaps': len(selected), 'newly_uncredited': len(additional),
                      'recipes': len(recipes), 'checks': sum(len(c['checks']) for c in recipes)}))


if __name__ == '__main__':
    write_outputs()
