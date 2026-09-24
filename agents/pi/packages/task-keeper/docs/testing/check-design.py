#!/usr/bin/env python3
"""Read-only design audit. --self-test mutates in-memory copies, never product code or config."""
import argparse
import collections
import copy
import csv
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PKG = HERE.parents[1]
ROOT = PKG.parents[2]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def source_rows():
    sources = {}
    for kind, file in [('scenario', 'scenario-test-matrix.csv'), ('fault', 'fault-traceability.csv')]:
        for row in csv.DictReader((PKG / 'tests/plan' / file).open()):
            identity = row.get('scenario_id', row.get('id'))
            require(identity not in sources, 'duplicate-source')
            sources[identity] = (kind, file, row)
    return sources


def validate_rows(cases, sources, recipes, profiles, matrices, checkpoint, old_keys):
    expected = {f'{identity}:{level}' for identity, (_, _, row) in sources.items() for level in row['required_layers'].split(';')}
    actual = [c['obligation'] for c in cases]
    require(len(actual) == len(set(actual)), 'duplicate-obligation')
    require(set(actual) == expected, 'missing-or-extra-obligation')
    for fields in [('case_id',), ('proposed_file', 'proposed_name')]:
        require(len({tuple(c[f] for f in fields) for c in cases}) == len(cases), 'duplicate-case-identity')
    recipe_map = {r['id']: r for r in recipes}
    require(len(recipe_map) == len(recipes), 'duplicate-campaign')
    assigned = [i for r in recipes for i in r['ids']]
    require(len(assigned) == len(set(assigned)) and set(assigned) == set(sources), 'campaign-source-mismatch')
    mandatory = ['source_title', 'source_digest', 'given_when', 'procedure', 'expected_assertions', 'assertion_contract',
                 'fixture', 'positive_control', 'negative_control', 'independent_oracles', 'required_variants',
                 'variant_design', 'artifact_contract', 'dependency', 'timeout', 'layer_limit', 'reference_ids',
                 'production_targets', 'phase_gate', 'implementation_tasks', 'test_families']
    for c in cases:
        identity, level = c['obligation'].split(':')
        kind, file, row = sources[identity]
        require(level == c['level'] and level in profiles, 'wrong-layer')
        require(c['given_when'] == row.get('when', row.get('injection')) and c['expected_assertions'] == row['expected'], 'changed-source-semantics')
        require(c['source_digest'] == hashlib.sha256(canonical(row).encode()).hexdigest(), 'source-digest-drift')
        require(c['scenario_digest'] == row.get('spec_digest', ''), 'scenario-digest-drift')
        require(c['source'] == kind and c['source_file'] == file, 'wrong-source')
        require(all(c[f].strip() for f in mandatory), 'incomplete-design-fields')
        require(c['proposed_name'].startswith(f'[{level} {identity}] {c["case_id"]} '), 'wrong-test-name')
        require(re.fullmatch(r'tests/cases-g\d{2}-[usaplev]\.test\.ts', c['proposed_file']), 'undiscoverable-test-path')
        recipe = recipe_map[c['campaign']]
        require(identity in recipe['ids'] and c['wave'] == recipe['wave'], 'wrong-campaign')
        for target in c['production_targets'].split(';'):
            require((PKG / target).is_file(), 'missing-inspection-target')
        require(c['independent_oracles'] == profiles[level]['observer'] and c['layer_limit'] == profiles[level]['forbidden'], 'wrong-layer-observer')
        assertion = json.loads(c['assertion_contract'])
        require(assertion['obligation'] == c['obligation'] and assertion['assertionId'] == c['case_id'] + '.primary', 'wrong-assertion-owner')
        require(assertion['input'] == c['given_when'] and assertion['predicate'] == c['expected_assertions'], 'wrong-assertion-predicate')
        require(assertion['observer'] == c['independent_oracles'] and assertion['artifact'].startswith('<run>/' + c['case_id'] + '/'), 'missing-observer-artifact')
        variants = ['primary', 'positive-control', 'negative-control'] + [x['id'] for x in recipe['checks']]
        applicable = [m for m in matrices if c['campaign'] in m['campaigns'] and level in m['layers']]
        for matrix in applicable:
            variants += [matrix['id'] + '.' + x['id'] for x in matrix['cases']]
        require(len(variants) == len(set(variants)), 'duplicate-variant')
        require(c['required_variants'].split(';') == variants, 'variant-coverage-gap')
        require(json.loads(c['variant_design']) == recipe['checks'], 'wrong-variant-design')
        require(c['matrix_refs'].split(';') == [m['id'] for m in applicable] if applicable else c['matrix_refs'] == '', 'wrong-matrix-ref')
        deferred = identity in {'T66', 'T68', 'T69'}
        require(c['release_scope'] == ('P4-deferred-online' if deferred else 'P0-P3'), 'changed-release-scope')
        require(c['disposition'] == ('deferred-P4' if deferred else 'needs-live-binding' if level == 'L' else 'offline-design'), 'wrong-environment-scope')
        require(c['evidence_at_checkpoint'] == ('missing' if c['obligation'] in checkpoint['fullMissing'] else 'credited-at-checkpoint-needs-regression'), 'changed-runtime-status')
        require(c['baseline_design'] == ('existing-435-design' if c['obligation'] in old_keys else 'new-detailed-design'), 'wrong-baseline-link')
        require(c['design_status'] == 'designed' and c['implementation_status'] == 'not-claimed-by-design'
                and c['execution_status'] == 'not-executed-as-designed' and not c['result_artifact'], 'fabricated-runtime-evidence')
    return expected


def validate_matrices(matrices):
    by_id = {m['id']: m for m in matrices}
    require(len(by_id) == len(matrices) == 5, 'matrix-identity')
    races = {'R01': ['input', 'stop', 'binding-change'], 'R02': ['input', 'stop', 'account-change', 'bucket-change'],
             'R03': ['input', 'pause', 'stop', 'shutdown'], 'R04': ['input', 'stop', 'config-change'],
             'R05': ['input', 'stop', 'ownerEpoch-change'], 'R06': ['stop', 'reload', 'owner-loss'],
             'R07': ['input', 'stop', 'fork', 'switch'], 'R08': ['input', 'stop', 'switch'],
             'R09': ['pause', 'stop', 'dispose'], 'R10': ['stop', 'source-change', 'acceptance-change']}
    expected = {
        'await-orders': {f'{r}.{e}.{o}' for r, events in races.items() for e in events for o in ['revoke-first', 'await-first']},
        'crash-cuts': {f'{a}.C{n}' for a in ['start', 'continue', 'verify'] for n in range(6)},
        'request-paths': {f'{p}.{w}' for p in ['primary', 'native-retry', 'summary', 'compaction', 'child', 'parent-helper', 'canary']
                          for w in ['allowed', 'denied', 'cancel-before-gate', 'cancel-after-reserve', 'cancel-after-recheck', 'cancel-after-receiver']},
        'stream-terminals': {'complete', 'error', 'truncated', 'timeout'},
        'lifecycle-preservation': {f'{a}.{s}' for a in ['upgrade', 'disable', 'restart', 'rollback'] for s in ['not-sent', 'terminal-confirmed', 'unknown']},
    }
    for identity, matrix in by_id.items():
        keys = [c['id'] for c in matrix['cases']]
        require(len(keys) == len(set(keys)) and set(keys) == expected[identity], 'matrix-cross-product-gap')
        require(all(c['input'] and c['expected'] for c in matrix['cases']), 'matrix-case-empty')


def verify_specs(sources):
    actual = {}
    requirements = 0
    files = list((PKG / 'tests/plan/specs').glob('*/spec.md'))
    for file in files:
        text = file.read_text()
        for block in re.split(r'^### Requirement: ', text, flags=re.M)[1:]:
            requirements += 1
            requirement = block.split('\n', 1)[0]
            scenarios = re.split(r'^#### Scenario: ', block, flags=re.M)[1:]
            require(scenarios, 'requirement-without-scenario')
            for scenario in scenarios:
                name = scenario.split('\n', 1)[0]
                when = re.search(r'^- \*\*WHEN\*\* (.+)$', scenario, re.M).group(1)
                then = re.search(r'^- \*\*THEN\*\* (.+)$', scenario, re.M).group(1)
                key = ('specs/' + file.parent.name + '/spec.md', requirement, name)
                require(key not in actual, 'duplicate-spec-scenario')
                actual[key] = hashlib.sha256('\n'.join([requirement, name, when, then]).encode()).hexdigest()
    for identity, (kind, _, row) in sources.items():
        if kind == 'scenario':
            require(actual.pop((row['spec_path'], row['requirement'], row['scenario']), None) == row['spec_digest'], 'spec-scenario-drift')
    require(not actual and len(files) == 8 and requirements == 56, 'spec-count-drift')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cases = list(csv.DictReader((HERE / 'coverage-cases.csv').open()))
    recipes = json.loads((HERE / 'case-recipes.json').read_text())
    profiles = json.loads((HERE / 'layer-profiles.json').read_text())
    matrices = json.loads((HERE / 'expanded-matrices.json').read_text())
    checkpoint = json.loads((HERE / 'current-checkpoint.json').read_text())
    baseline = json.loads((HERE / 'baseline.json').read_text())
    manifest = json.loads((HERE / 'design-baseline-v2.json').read_text())
    sources = source_rows()
    old_keys = set(baseline['missingObligations'])
    checks = []
    for file, expected_hash in manifest['immutableInputs'].items():
        require(sha(PKG / file) == expected_hash, 'immutable-input-changed: ' + file)
    checks.append('frozen baseline, old designs, current checkpoint and source matrix hashes unchanged')
    # Runtime artifacts are untracked and optional in a fresh checkout; absence is explicit.
    verified_reports = []
    for item in [baseline, {'reportPath': checkpoint['reportPath'], 'reportSha256': checkpoint['reportSha256']}]:
        file = PKG / item['reportPath']
        if file.exists():
            require(sha(file) == item['reportSha256'], 'historical-report-changed')
            verified_reports.append(item['reportPath'])
    checks.append('available historical runtime reports unchanged')
    verify_specs(sources)
    checks.append('all 8 specs / 56 requirements / 126 scenarios match actual WHEN/THEN digests')
    validate_matrices(matrices)
    checks.append('independent cross-product check: 66 await, 18 crash, 42 request, 4 stream, 12 lifecycle')
    expected = validate_rows(cases, sources, recipes, profiles, matrices, checkpoint, old_keys)
    checks += ['all 228 IDs and all 713 source-required layers mapped exactly once',
               'all 707 P0-P3 and six P4 obligations retained; T75 offline not deferred',
               'all case IDs and proposed file/name identities unique and discoverable',
               'all case source semantics / digest / primary assertion / observer artifacts correspond',
               'all cases have layer-appropriate steps, positive and negative controls, variants and dependencies',
               'all required recipe checks and applicable expanded matrix cells retained',
               'all design rows remain unexecuted; no invented result artifact']
    release = {c['obligation'] for c in cases if c['release_scope'] == 'P0-P3'}
    require(len(release) == 707 and set(checkpoint['releaseMissing']) <= release, 'release-set-mismatch')
    require({c['obligation'] for c in cases if c['level'] == 'L'} == {'VAL-005:L', 'VAL-007:L'}, 'live-set-mismatch')
    for file, rows in [('current-gap-cases.csv', [r for r in cases if r['obligation'] in checkpoint['releaseMissing']]),
                       ('newly-uncredited-cases.csv', [r for r in cases if r['obligation'] in checkpoint['releaseMissing'] and r['newly_uncredited'] == 'yes'])]:
        require(list(csv.DictReader((HERE / file).open())) == rows, 'derived-view-drift: ' + file)
    require(len(set(checkpoint['releaseMissing']) & old_keys) == 398, 'baseline-gap-count')
    require(len(set(checkpoint['releaseMissing']) - old_keys) == 220, 'new-gap-count')
    checks.append('current 618-gap view = 398 existing designs + 220 newly uncredited designs')
    # A renderer comparison prevents manually editing a generated CSV but not its authored recipe.
    spec = importlib.util.spec_from_file_location('design_builder', HERE / 'build-design.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    require(builder.render()[0] == cases, 'renderer-drift')
    checks.append('rendered case catalog equals reviewed source recipes and layer profiles')
    openspec = ROOT / 'openspec/changes/add-pi-task-keeper'
    if openspec.exists():
        for file in ['scenario-test-matrix.csv', 'fault-traceability.csv']:
            require((openspec / file).read_bytes() == (PKG / 'tests/plan' / file).read_bytes(), 'openspec-package-matrix-drift')
        for file in (openspec / 'specs').glob('*/spec.md'):
            require(file.read_bytes() == (PKG / 'tests/plan/specs' / file.parent.name / 'spec.md').read_bytes(), 'openspec-package-spec-drift')
        for line in (openspec / 'references/v6/SHA256SUMS').read_text().splitlines():
            h, file = line.split()
            require(sha(openspec / 'references/v6' / file) == h, 'v6-source-changed')
        checks.append('OpenSpec/package sources and all nine v6 bundle checksums unchanged')
    negatives = []
    if args.self_test:
        def reject(name, mutate, error):
            bad = copy.deepcopy(cases)
            mutate(bad)
            try:
                validate_rows(bad, sources, recipes, profiles, matrices, checkpoint, old_keys)
            except ValueError as exc:
                require(str(exc) == error, 'unexpected-negative-rejection: ' + name + ': ' + str(exc))
                negatives.append({'name': name, 'expectedRejection': error, 'result': 'rejected'})
            else:
                raise ValueError('negative-control-accepted: ' + name)
        reject('delete obligation', lambda x: x.pop(), 'missing-or-extra-obligation')
        reject('duplicate obligation', lambda x: x.append(copy.deepcopy(x[0])), 'duplicate-obligation')
        reject('unknown obligation', lambda x: x[0].update(obligation='CFG-999:U'), 'missing-or-extra-obligation')
        reject('change validation layer', lambda x: x[0].update(level='E'), 'wrong-layer')
        reject('alter expected behavior', lambda x: x[0].update(expected_assertions='always pass'), 'changed-source-semantics')
        reject('omit negative control', lambda x: x[0].update(negative_control=''), 'incomplete-design-fields')
        reject('borrow another level observer', lambda x: x[0].update(independent_oracles=profiles['P']['observer']), 'wrong-layer-observer')
        reject('drop required variant', lambda x: x[0].update(required_variants='primary'), 'variant-coverage-gap')
        reject('claim runtime pass', lambda x: x[0].update(execution_status='passed'), 'fabricated-runtime-evidence')
        reject('invent result artifact', lambda x: x[0].update(result_artifact='imaginary/passed.json'), 'fabricated-runtime-evidence')
        reject('same test identity twice', lambda x: x[1].update(proposed_file=x[0]['proposed_file'], proposed_name=x[0]['proposed_name']), 'duplicate-case-identity')
        reject('wrong primary assertion ID', lambda x: x[0].update(assertion_contract=x[0]['assertion_contract'].replace(x[0]['case_id'] + '.primary', 'other.primary')), 'wrong-assertion-owner')
        t75 = next(i for i, r in enumerate(cases) if r['obligation'] == 'T75:U')
        reject('silently defer T75 offline', lambda x: x[t75].update(release_scope='P4-deferred-online'), 'changed-release-scope')
        broken = copy.deepcopy(matrices)
        broken[0]['cases'].pop()
        try:
            validate_matrices(broken)
        except ValueError as exc:
            require(str(exc) == 'matrix-cross-product-gap', 'unexpected-matrix-rejection')
            negatives.append({'name': 'drop reverse await order', 'expectedRejection': str(exc), 'result': 'rejected'})
        else:
            raise ValueError('negative-control-accepted: matrix')
        checks.append('14 in-memory negative controls rejected; no product/config writes')
    audit = {'kind': 'test-design-static-review-v2', 'baselineRun': checkpoint['runId'],
             'designCoverage': {'sourceIds': len(sources), 'allObligations': len(expected), 'p0p3Obligations': len(release),
                                'p0p3Designed': len(release), 'currentMissingDesigned': len(checkpoint['releaseMissing']),
                                'newlyUncreditedDesigned': 220, 'unmapped': 0, 'duplicates': 0,
                                'campaigns': len(recipes), 'domainChecks': sum(len(r['checks']) for r in recipes)},
             'byLevel': dict(sorted(collections.Counter(c['level'] for c in cases if c['release_scope'] == 'P0-P3').items())),
             'checks': checks, 'negativeControls': negatives, 'verifiedRuntimeReports': verified_reports,
             'runtimeEvidenceAdded': 0, 'runtimeReleaseMissingUnchanged': len(checkpoint['releaseMissing']),
             'runtimeReleaseReadyUnchanged': checkpoint['releaseReady'], 'implementationTasksUnchanged': checkpoint['implementationTasks'],
             'designFiles': {f: sha(HERE / f) for f in ['case-recipes.json', 'layer-profiles.json', 'expanded-matrices.json', 'coverage-cases.csv', 'current-gap-cases.csv', 'newly-uncredited-cases.csv', 'case-design.md', 'build-design.py', 'check-design.py']},
             'limitations': ['100% is the declared obligation-to-design mapping, not executed/code coverage or exhaustive input-space proof.',
                             'Assertions and every planned variant must be implemented and executed against the correct layer before credit.',
                             'An unsupported success requirement remains pending; rejection cannot replace the required success case.']}
    if args.output:
        args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({**audit['designCoverage'], 'checks': len(checks), 'negativeControls': len(negatives), 'runtimeEvidenceAdded': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
