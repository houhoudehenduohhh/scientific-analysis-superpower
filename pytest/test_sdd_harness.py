from pathlib import Path
import importlib.util
import json
import pytest

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


def test_runtime_audit_layout_accepts_required_sections(tmp_path):
    report = tmp_path / 'runtime-audit.md'
    write_report(report)
    result = harness.verify_report_layout(report, 'runtime')
    assert result['layout'] == 'valid'
    assert result['kind'] == 'runtime'


def test_building_audit_layout_rejects_missing_section(tmp_path):
    report = tmp_path / 'building-audit.md'
    write_report(report, missing=HEADINGS[4])
    with pytest.raises(SystemExit):
        harness.verify_report_layout(report, 'building')


def test_audit_layout_rejects_legacy_duplicate_sections(tmp_path):
    report = tmp_path / 'audit.md'
    write_report(report, forbidden='Strengths')
    with pytest.raises(SystemExit):
        harness.verify_report_layout(report, 'runtime')


def test_state_machine_rejects_skipping_task_review():
    assert 'final_review_pending' not in harness.STATES['task_review_pending']
    assert 'dispatch_task_reviewer' in harness.NEXT['task_review_pending']


def test_manifest_phase_mapping_covers_runtime_audit():
    assert harness._phase('milestone_audit_pending') == 'runtime_audit'
    assert harness._phase('runtime_finish_pending') == 'runtime_finish'
