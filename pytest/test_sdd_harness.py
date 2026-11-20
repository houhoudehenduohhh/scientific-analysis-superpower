from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import pytest

from test_proposal_paths import write_proposal

SCRIPT = Path(__file__).parents[1] / 'skills/subagent-driven-development/scripts/sdd-harness.py'
spec = importlib.util.spec_from_file_location('sdd_harness', SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

HEADINGS = [
    '## 1. 审查对象',
    '## 2. Audit 发现的问题、解决办法及完成状态',
    '## 3. 有待改进或商讨的地方',
    '## 4. 未作判断的部分',
    '## 5. 已核实的下一步修复方向',
    '## 6. 任务验收索引',
]


def write_report(path, *, missing=None, forbidden=None):
    text = '\n'.join(h for h in HEADINGS if h != missing)
    if forbidden:
        text += f'\n## {forbidden}\n'
    path.write_text(text, encoding='utf-8')


@pytest.fixture
def report_layout(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    return harness.verify_report_layout


def test_runtime_audit_layout_accepts_required_sections(tmp_path, report_layout):
    report = tmp_path / 'runtime-audit.md'
    write_report(report)
    result = report_layout(report, 'runtime')
    assert result['layout'] == 'valid'
    assert result['kind'] == 'runtime'


def test_building_audit_layout_rejects_missing_section(tmp_path, report_layout):
    report = tmp_path / 'building-audit.md'
    write_report(report, missing=HEADINGS[4])
    with pytest.raises(SystemExit):
        report_layout(report, 'building')


def test_audit_layout_rejects_legacy_duplicate_sections(tmp_path, report_layout):
    report = tmp_path / 'audit.md'
    write_report(report, forbidden='Strengths')
    with pytest.raises(SystemExit):
        report_layout(report, 'runtime')


def test_state_machine_rejects_skipping_task_review():
    assert 'final_review_pending' not in harness.STATES['task_review_pending']
    assert 'dispatch_task_reviewer' in harness.NEXT['task_review_pending']


def test_manifest_phase_mapping_covers_runtime_audit():
    assert harness._phase('milestone_audit_pending') == 'runtime_audit'
    assert harness._phase('runtime_finish_pending') == 'runtime_finish'


def test_task_spec_layout_accepts_current_template(tmp_path):
    task = tmp_path / 'task-t01.md'
    task.write_text((Path(__file__).parents[1] / 'templates/task-spec.md').read_text(encoding='utf-8'), encoding='utf-8')
    assert harness.verify_task_spec_layout(task)['layout'] == 'valid'


def test_task_spec_layout_rejects_missing_approval_section(tmp_path):
    task = tmp_path / 'task-t01.md'
    task.write_text('# Task T01\n## 验收与验证\n| AC ID（完整任务 ID + -ACNN） |', encoding='utf-8')
    with pytest.raises(SystemExit):
        harness.verify_task_spec_layout(task)


def test_task_spec_layout_rejects_reordered_sections(tmp_path):
    task = tmp_path / 'task-t01.md'
    text = (Path(__file__).parents[1] / 'templates/task-spec.md').read_text(encoding='utf-8')
    text = text.replace('## 上下游影响\n', '## 上下游影响\n', 1)
    first = text.index('## 输入、脚本与输出')
    second = text.index('## 上下游影响')
    text = text[:first] + text[second:text.index('## 审批引用')] + text[first:second] + text[text.index('## 审批引用'):]
    task.write_text(text, encoding='utf-8')
    with pytest.raises(SystemExit):
        harness.verify_task_spec_layout(task)


def test_verify_task_spec_cli_enforces_layout(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text('{}', encoding='utf-8')
    task = tmp_path / 'task-t01.md'
    task.write_text((Path(__file__).parents[1] / 'templates/task-spec.md').read_text(encoding='utf-8'), encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(SCRIPT), 'verify-task-spec', str(state), '--artifact', str(task)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)['layout'] == 'valid'


def test_build_plan_layout_accepts_current_template(tmp_path):
    plan = tmp_path / 'build_plan.md'
    plan.write_text((Path(__file__).parents[1] / 'templates/build-plan.md').read_text(encoding='utf-8'), encoding='utf-8')
    assert harness.verify_build_plan_layout(plan)['layout'] == 'valid'


def test_build_plan_layout_rejects_removed_sections(tmp_path):
    plan = tmp_path / 'build_plan.md'
    text = (Path(__file__).parents[1] / 'templates/build-plan.md').read_text(encoding='utf-8')
    plan.write_text(text + '\n## Build 总体映射\n', encoding='utf-8')
    with pytest.raises(SystemExit):
        harness.verify_build_plan_layout(plan)


def test_verify_build_plan_cli_enforces_layout(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text('{}', encoding='utf-8')
    plan, _ = write_proposal(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), 'verify-build-plan', str(state), '--artifact', str(plan)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)['layout'] == 'valid'


def test_transition_evidence_requires_implementer_completion(tmp_path):
    report = tmp_path / 'implementer.md'
    report.write_text('Status: BLOCKED\nCommit: none\n', encoding='utf-8')
    records = [harness.evidence_record(report)]
    with pytest.raises(SystemExit):
        harness._require_transition_evidence({}, 'building_incomplete', 'task_review_pending', records)


def test_transition_evidence_requires_review_pass(tmp_path):
    report = tmp_path / 'review.md'
    report.write_text('Verdict: CHANGES_REQUIRED\n', encoding='utf-8')
    records = [harness.evidence_record(report)]
    with pytest.raises(SystemExit):
        harness._require_transition_evidence({}, 'task_review_pending', 'task_complete', records)


def test_transition_evidence_accepts_completed_implementer_and_review(tmp_path):
    implementer = tmp_path / 'implementer.md'
    implementer.write_text('Status: DONE\nCommit: abc123\nTDD Evidence\n', encoding='utf-8')
    reviewer = tmp_path / 'review.md'
    reviewer.write_text('Verdict: PASS\n', encoding='utf-8')
    records = [harness.evidence_record(implementer), harness.evidence_record(reviewer)]
    harness._require_transition_evidence({}, 'building_incomplete', 'task_review_pending', records)
    harness._require_transition_evidence({}, 'task_review_pending', 'task_complete', records)


@pytest.fixture
def final_review_workspace(tmp_path):
    git = ['git', '-C', str(tmp_path)]
    subprocess.run([*git, 'init', '--quiet'], check=True)
    subprocess.run([*git, '-c', 'user.email=review@example.invalid', '-c', 'user.name=Review',
                    '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'fixture'], check=True)
    head = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
    plan = tmp_path / 'build-plan.md'
    plan.write_text('# Build Plan\n', encoding='utf-8')
    state = tmp_path / 'state.json'
    final_text = f'# Overall Review\nHEAD: `{head}`\nVerdict: PASS\n'
    review = tmp_path / 'task-review.md'
    review.write_text(final_text, encoding='utf-8')
    task = tmp_path / 'T01.md'
    task.write_text('# Task T01\n', encoding='utf-8')
    return state, {
        'refs': {'build_plan': harness.evidence_record(plan)},
        'tasks': {'T01': {'status': 'task_complete', 'task_spec_path': str(task),
                          'task_spec_sha256': harness.digest(task),
                          'building_chain': {'review': [harness.evidence_record(review)]}}},
        'task_id': 'T01', 'evidence': {},
    }, review, final_text


@pytest.mark.parametrize('case', [
    'missing', 'invalid_verdict', 'duplicate_verdict', 'reused', 'copied', 'wrong_head', 'unnamed',
    'task_review_subheading', 'task_review_fenced_example', 'fenced_metadata', 'indented_metadata',
])
def test_building_audit_requires_current_independent_overall_review(final_review_workspace, case):
    state, data, task_review, final_text = final_review_workspace
    data.update(status='final_review_pending', next_allowed_actions=harness.NEXT['final_review_pending'])
    state.write_text(json.dumps(data), encoding='utf-8')
    final_review = state.with_name('overall.md')
    report = {
        'invalid_verdict': final_text.replace('PASS', 'UNKNOWN'),
        'duplicate_verdict': final_text + 'Verdict: CHANGES_REQUIRED\n',
        'copied': final_text,
        'wrong_head': final_text.split('`')[0] + '`' + '0' * 40 + '`\nVerdict: PASS\n',
        'unnamed': final_text.replace('# Overall Review', '# Task Review'),
        'task_review_subheading': '# Task Review\n\n#' + final_text,
        'task_review_fenced_example': '# Task Review\n\n```markdown\n' + final_text + '```\n',
        'fenced_metadata': final_text.replace('\n', '\n~~~markdown\n', 1) + '~~~\n',
        'indented_metadata': '# Overall Review\n\n' + ''.join('    ' + line for line in
                                                            final_text.splitlines(keepends=True)[1:]),
    }
    args = []
    if case == 'reused':
        args = ['--evidence', str(task_review)]
    elif case != 'missing':
        final_review.write_text(report[case], encoding='utf-8')
        args = ['--evidence', str(final_review)]
    before = state.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPT), 'transition', str(state), '--to',
                             'building_audit_pending', *args], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Overall Review' in result.stderr
    assert state.read_bytes() == before
    assert not state.with_name('events.jsonl').exists()


@pytest.mark.parametrize('current, action, args', [
    ('building_audit_pending', 'transition', ['--to', 'building_audit_gate']),
    ('building_audit_gate', 'gate', []),
])
def test_legacy_audit_state_with_no_overall_review_cannot_advance(final_review_workspace, current, action, args):
    state, data, _, _ = final_review_workspace
    audit = state.with_name('formal-audit.md')
    audit.write_text('# Building Audit\n', encoding='utf-8')
    if current == 'building_audit_gate':
        data['evidence']['building_audit'] = [harness.evidence_record(audit)]
    data.update(status=current, next_allowed_actions=harness.NEXT[current])
    state.write_text(json.dumps(data), encoding='utf-8')
    before = state.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPT), action, str(state), *args, '--evidence', str(audit)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Overall Review' in result.stderr
    assert state.read_bytes() == before


@pytest.mark.parametrize('title', ['# Overall Review', 'Overall Review', '# 整体初审', '## 整体审查'])
def test_building_audit_records_independent_review(final_review_workspace, title):
    state, data, _, final_text = final_review_workspace
    data.update(status='final_review_pending', next_allowed_actions=harness.NEXT['final_review_pending'])
    state.write_text(json.dumps(data), encoding='utf-8')
    report = state.with_name('overall.md')
    example = '````markdown\n```\nVerdict: CHANGES_REQUIRED\n```\n````\n'
    report.write_text('\n' + final_text.replace('# Overall Review', title, 1)
                      + '\nWhole-branch evidence.\n\n' + example, encoding='utf-8')
    subprocess.run([sys.executable, str(SCRIPT), 'transition', str(state), '--to', 'building_audit_pending',
                    '--evidence', str(report)], capture_output=True, text=True, check=True)
    after = json.loads(state.read_text(encoding='utf-8'))
    assert after['evidence']['building_audit_pending'] == [harness.evidence_record(report)]
    assert after['tasks']['T01']['status'] == 'task_complete'



@pytest.mark.parametrize('assessment', ['PASS', 'PASS_WITH_NOTES', 'CHANGES_REQUIRED', 'BLOCKED'])
def test_failed_overall_review_allows_only_negative_formal_audit(final_review_workspace, assessment):
    state, data, _, final_text = final_review_workspace
    data.update(status='final_review_pending', next_allowed_actions=harness.NEXT['final_review_pending'])
    state.write_text(json.dumps(data), encoding='utf-8')
    review = state.with_name('overall.md')
    review.write_text(final_text.replace('PASS', 'CHANGES_REQUIRED'), encoding='utf-8')

    def transition(target, report):
        return subprocess.run([sys.executable, str(SCRIPT), 'transition', str(state), '--to', target,
                               '--evidence', str(report)], capture_output=True, text=True)

    pending = transition('building_audit_pending', review)
    assert pending.returncode == 0, pending.stderr
    report = state.with_name('formal-audit.md')
    template = (Path(__file__).parents[1] / 'templates/building-audit-report.md').read_text(encoding='utf-8')
    report.write_text(template.replace('assessment: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED',
                                       f'assessment: {assessment}'), encoding='utf-8')
    before = state.read_bytes()
    result = transition('building_audit_gate', report)
    if assessment in {'CHANGES_REQUIRED', 'BLOCKED'}:
        assert result.returncode == 0, result.stderr
        assert json.loads(state.read_text(encoding='utf-8'))['status'] == 'building_audit_gate'
    else:
        assert result.returncode != 0
        assert 'Overall Review' in result.stderr
        assert state.read_bytes() == before


def test_overall_rereview_uses_the_repaired_head(final_review_workspace):
    state, data, _, final_text = final_review_workspace
    data.update(status='final_review_pending', next_allowed_actions=harness.NEXT['final_review_pending'])
    state.write_text(json.dumps(data), encoding='utf-8')
    git = ['git', '-C', str(state.parent)]
    subprocess.run([*git, '-c', 'user.email=review@example.invalid', '-c', 'user.name=Review',
                    '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'fixture repair'],
                   check=True)
    new_head = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
    initial = state.with_name('final-review-initial.md')
    initial.write_text(final_text.replace('PASS', 'CHANGES_REQUIRED') + '\nInitial review.', encoding='utf-8')
    rereview = state.with_name('final-review-rereview.md')
    rereview.write_text(f'## Overall Review\nHEAD: {new_head}\nVerdict: PASS\nFinding: ADDRESSED\n',
                        encoding='utf-8')
    command = [sys.executable, str(SCRIPT), 'transition', str(state), '--to', 'building_audit_pending', '--evidence']
    stale = subprocess.run([*command, str(initial)], capture_output=True, text=True)
    assert stale.returncode != 0
    current = subprocess.run([*command, str(rereview)], capture_output=True, text=True)
    assert current.returncode == 0, current.stderr
    assert json.loads(state.read_text(encoding='utf-8'))['evidence']['building_audit_pending'] == [
        harness.evidence_record(rereview)]
