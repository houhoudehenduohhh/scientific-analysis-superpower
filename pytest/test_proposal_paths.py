from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "skills/subagent-driven-development/scripts"
HARNESS = SCRIPTS / "sdd-harness.py"
ENTRY = "| T01 | scripts/build/main.py | 新增 |"
OUTPUT = "| O01 | Data | results/data/region/status.csv | Data | Runtime | T01-AC01 |"
AUDIT_HEADER = "| 任务 ID | 任务目的 | AC ID | 成功条件 | 完成情况与验证范围 |"
AUDIT_ROW = "| T01 | Produce counts | T01-AC01 | Outputs a count | PASS. Known input counted. |"


def write_proposal(tmp_path):
    tasks = tmp_path / "specs/tasks/task-01"
    tasks.mkdir(parents=True)
    task = tasks / "task-01.md"
    task.write_text("""# Task T01 · Count
- 任务 ID：T01
- 父任务 ID（无则填无）：无
- 变更类型（原始／新增／替换）：原始
- 任务目的：Produce counts
- 任务边界与明确排除项：Counts only
## 输入、脚本与输出
- 主入口路径：`scripts/build/main.py`
## 验收与验证
| AC ID（完整任务 ID + -ACNN） | 验收目标 | 可观察的成功条件 | 验证方式 | 验证阶段 | 当前状态 |
|---|---|---|---|---|---|
| T01-AC01 | Count | Outputs a count | fixture | Building | 未验证 |
## 上下游影响
## 审批引用
- approval_status: pending
""", encoding="utf-8")
    plan = tmp_path / "specs/build_plan.md"
    plan.write_text(f"""# Build Plan（构建计划）
## 目标与边界
- 功能单元 Git 根目录：`{tmp_path}`
## 源数据、算法与输出
### 拟得到的输出
| 输出 ID | 输出名称 | 逻辑路径 | 内容与用途 | 生成阶段 | 验收依据 |
|---|---|---|---|---|---|
{OUTPUT}
| O02 | Plot | results/plot/count.png | Plot | Runtime | T01-AC01 |
| O03 | Smoke | results/smoke_test/example/report.md | Smoke | Building | T01-AC01 |
## 项目目录结构
- path_schema: 1
| 任务 ID | 主入口路径 | 变更（新增／既有／迁移） |
|---|---|---|
{ENTRY}
## 任务清单
| 任务 ID | Task MD | 目的与边界 | 前置任务／产物 | 相关 AC |
|---|---|---|---|---|
| T01 | [Task MD](tasks/task-01/task-01.md) | Count | 无 | T01-AC01 |
## Runtime 执行图
| 运行步骤 ID | 对应任务 | 前置步骤或节点 | 输入与输出 | 可并行步骤／互斥条件 | 完成检查 |
|---|---|---|---|---|---|
| R01 | T01 | 无 | Count | 无 | Smoke |
## 阶段性验收节点
| 节点 ID | 节点目的 | 包含的运行步骤 | 前置节点 | 阶段性成果与验收条件 | 用户授权范围 |
|---|---|---|---|---|---|
| N01 | Count | R01 | 无 | Outputs | All |
## 批准
- decision: pending
""", encoding="utf-8")
    return plan, task


@pytest.fixture
def proposal(tmp_path):
    return write_proposal(tmp_path)


def verify(plan, task=None):
    command = ["verify-build-plan", str(plan.parent / "state.json"), "--artifact", str(plan)]
    if task is not None:
        command = ["verify-task-spec", str(plan.parent / "state.json"), "--artifact", str(task),
                   "--build-plan", str(plan)]
    return subprocess.run([sys.executable, str(HARNESS), *command],
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def replace(path, old, new):
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_canonical_proposal_paths_are_accepted(proposal):
    plan, task = proposal
    assert verify(plan).returncode == 0
    assert verify(plan, task).returncode == 0


@pytest.mark.parametrize("path", ["main.py", "scripts/build/../main.py", "scripts/build/NUL.py",
                                  "scripts/build//main.py", "scripts/build/main.py:payload"])
def test_canonical_plan_rejects_unsafe_entry(proposal, path):
    plan, _ = proposal
    replace(plan, "scripts/build/main.py", path)
    result = verify(plan)
    assert result.returncode and "main entry path" in result.stderr


def test_canonical_plan_rejects_task_path_mismatch(proposal):
    plan, task = proposal
    replace(task, "scripts/build/main.py", "scripts/build/other.py")
    for result in (verify(plan), verify(plan, task)):
        assert result.returncode and "main entry declaration differs" in result.stderr


@pytest.mark.parametrize("path", ["results/logs/run.csv", "results/data/../run.csv",
                                  "results/data/Region/STATUS.CSV", "results/data/region",
                                  "results/data/NUL.csv"])
def test_canonical_plan_rejects_invalid_or_duplicate_result(proposal, path):
    plan, _ = proposal
    replace(plan, OUTPUT, OUTPUT + f"\n| O04 | Other | {path} | Data | Runtime | T01-AC01 |")
    result = verify(plan)
    assert result.returncode and "logical result path" in result.stderr


def test_canonical_plan_rejects_cycle_and_accepts_multiple_nodes(proposal):
    plan, _ = proposal
    replace(plan, "| R01 | T01 | 无 | Count | 无 | Smoke |",
            "| R01 | T01 | 无 | Count | 无 | Smoke |\n| R02 | T01 | R01 | Count | 无 | Smoke |")
    replace(plan, "| N01 | Count | R01 | 无 | Outputs | All |",
            "| N01 | Count | R01 | 无 | Outputs | All |\n| N02 | Count | R02 | N01 | Outputs | All |")
    assert verify(plan).returncode == 0
    replace(plan, "| R01 | T01 | 无 | Count", "| R01 | T01 | R02 | Count")
    result = verify(plan)
    assert result.returncode and "cycle" in result.stderr


def test_building_scope_and_acceptance_index(proposal, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from sdd_layout import verify_acceptance_index, verify_building_paths

    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    plan, _ = proposal
    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "old.py").write_text("print(1)\n", encoding="utf-8")
    git("add", "old.py", "specs")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    entry = tmp_path / "scripts/build/main.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("print(2)\n", encoding="utf-8")
    git("add", "scripts")
    git("commit", "-m", "approved entry")
    verify_building_paths(tmp_path, plan, [base], git("rev-parse", "HEAD"))
    (tmp_path / "new.py").write_text("print(3)\n", encoding="utf-8")
    git("add", "new.py")
    git("commit", "-m", "unapproved entry")
    with pytest.raises(ValueError, match="scripts/build"):
        verify_building_paths(tmp_path, plan, [base], git("rev-parse", "HEAD"))

    audit = f"## 6. 任务验收索引\n\n{AUDIT_HEADER}\n|---|---|---|---|---|\n{AUDIT_ROW}\n"
    verify_acceptance_index(audit, plan)
    for invisible in (
        f"## 6. 任务验收索引\n<!--\n{AUDIT_HEADER}\n|---|---|---|---|---|\n{AUDIT_ROW}\n-->\n",
        audit.replace("\n\n", "\n\n说明文字。\n", 1),
        audit.replace("|---", "|-<!-- hidden -->--", 1),
        f"<pre>\n{audit}</pre>\n",
    ):
        with pytest.raises(ValueError, match="acceptance index|Markdown section"):
            verify_acceptance_index(invisible, plan)
    for bad in (AUDIT_ROW.replace("T01-AC01", "T01-AC02"),
                AUDIT_ROW.replace("PASS. Known input counted.", ""),
                AUDIT_ROW.replace("Outputs a count", "Different success criterion"),
                AUDIT_ROW + "\n" + AUDIT_ROW,
                ""):
        with pytest.raises(ValueError, match="acceptance index"):
            verify_acceptance_index(audit.replace(AUDIT_ROW, bad), plan)



def test_marker_cannot_be_removed_to_bypass_new_proposal(proposal, tmp_path):
    plan, task = proposal
    replace(plan, "- path_schema: 1\n", "")
    result = verify(plan)
    assert result.returncode and "path_schema" in result.stderr

    replace(plan, "decision: pending", "decision: approved")
    replace(task, "approval_status: pending", "approval_status: approved")
    receipt = tmp_path / "approval.json"
    receipt.write_text(json.dumps({
        "build_plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "task_specs": {"T01": hashlib.sha256(task.read_bytes()).hexdigest()},
        "user_message_ref": "test approval",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")
    state = tmp_path / ".tmp/sdd/build_plan/state.json"
    result = subprocess.run([sys.executable, str(HARNESS), "init", str(state), "--build-plan", str(plan),
                             "--evidence", str(receipt)], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode and "path_schema" in result.stderr
    assert not state.exists()
    assert not (tmp_path / ".git").exists()


def test_proposal_cannot_claim_a_missing_entry_is_existing(proposal):
    plan, task = proposal
    replace(plan, ENTRY, "| T01 | missing.py | 既有 |")
    replace(task, "scripts/build/main.py", "missing.py")
    result = verify(plan)
    assert result.returncode and "existing main entry" in result.stderr


def test_forged_refs_do_not_prove_legacy_build_plan(proposal):
    plan, _ = proposal
    replace(plan, "- path_schema: 1\n", "")
    (plan.parent / "state.json").write_text(json.dumps({
        "refs": {"build_plan": {"path": str(plan.resolve()),
                                "sha256": hashlib.sha256(plan.read_bytes()).hexdigest()}},
    }), encoding="utf-8")
    result = verify(plan)
    assert result.returncode and "initialized" in result.stderr


def test_forged_tasks_do_not_prove_legacy_task_md(proposal):
    plan, task = proposal
    replace(task, "- 主入口路径：`scripts/build/main.py`\n", "")
    (plan.parent / "state.json").write_text(json.dumps({
        "tasks": {"T01": {"task_spec_path": str(task.resolve()),
                          "task_spec_sha256": hashlib.sha256(task.read_bytes()).hexdigest()}},
    }), encoding="utf-8")
    result = subprocess.run([sys.executable, str(HARNESS), "verify-task-spec",
                             str(plan.parent / "state.json"), "--artifact", str(task)],
                            capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode and "main entry path" in result.stderr


def test_building_preserves_a_legacy_entry_outside_build(proposal, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from sdd_layout import verify_building_paths

    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    plan, task = proposal
    replace(plan, ENTRY, "| T01 | old.py | 既有 |")
    replace(task, "scripts/build/main.py", "old.py")
    old = tmp_path / "old.py"
    old.write_text("print(1)\n", encoding="utf-8")
    assert verify(plan).returncode == 0
    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("add", "old.py", "specs")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    verify_building_paths(tmp_path, plan, [base], base)
    old.write_text("print(2)\n", encoding="utf-8")
    git("add", "old.py")
    git("commit", "-m", "modified legacy script")
    with pytest.raises(ValueError, match="unchanged.*scripts/build"):
        verify_building_paths(tmp_path, plan, [base], git("rev-parse", "HEAD"))


def test_batch_plan_uses_the_existing_node_table(proposal, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from sdd_layout import BATCH_NODES_HEADER, NODES_HEADER, batch_plan

    plan, _ = proposal
    content = plan.read_text(encoding="utf-8")
    assert batch_plan(content) is None

    content = content.replace(
        "| T01 | [Task MD](tasks/task-01/task-01.md) | Count | 无 | T01-AC01 |",
        "| T01 | [Task MD](tasks/task-01/task-01.md) | Count | 无 | T01-AC01 |\n"
        "| T02 | [Task MD](tasks/task-02/task-02.md) | Confirm | T01 | T02-AC01 |",
    ).replace(
        "| R01 | T01 | 无 | Count | 无 | Smoke |",
        "| R01 | T01 | 无 | Count | 无 | Smoke |\n"
        "| R02 | T01 | R01、N01 | Count | 无 | Smoke |\n"
        "| R03 | T02 | R02、N02 | Confirm | 无 | Smoke |",
    ).replace(
        NODES_HEADER + "\n|---|---|---|---|---|---|\n| N01 | Count | R01 | 无 | Outputs | All |",
        BATCH_NODES_HEADER + "\n|---|---|---|---|---|---|---|\n"
        "| N01 | Count | B01 | 无 | R01 | 无 | Outputs |\n"
        "| N02 | Pilot | B01 | 无 | R02 | N01 | Outputs |\n"
        "| N03 | Confirm | B02 | N02 已验收。核定正式条件 | R03 | N02 | Outputs |",
    )
    scopes = batch_plan(content)["batches"]
    assert scopes["B01"] == {"tasks": {"T01"}, "nodes": {"N01", "N02"},
                             "steps": {"R01", "R02"}, "needs": set()}
    assert scopes["B02"] == {"tasks": {"T02"}, "nodes": {"N03"},
                             "steps": {"R03"}, "needs": {"N02"}}
    with pytest.raises(ValueError, match="eligible batch"):
        batch_plan(content.replace("N02 已验收", "N03 已验收"))
    with pytest.raises(ValueError, match="must share a Building batch"):
        batch_plan(content.replace("| R03 | T02 |", "| R03 | T01 |"))
