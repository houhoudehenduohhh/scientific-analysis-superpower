"""Exercise the versioned layout through the public SDD CLI."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_proposal_paths import AUDIT_HEADER, AUDIT_ROW, proposal
from test_runtime_harness import HARNESS, Scenario, TEMPLATES, fingerprint


def clock():
    return datetime.now(timezone.utc).isoformat()


def render(template, fields):
    content = (TEMPLATES / template).read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if not any(line.startswith(f"- `{key}:") for key in fields)]
    return "\n".join([*lines, "", *(f"- `{key}: {value}`" for key, value in fields.items())])


@pytest.mark.parametrize("defect", ["commented", "detached", "after-fence", "after-prose", "comment-separator", "raw-html"])
def test_runtime_index_requires_a_visible_contiguous_table(monkeypatch, defect):
    monkeypatch.syspath_prepend(str(HARNESS.parent))
    from runtime_harness import RUNTIME_AUDIT_INDEX, verify_runtime_index

    header = f"## 6. 任务验收索引\n\n{RUNTIME_AUDIT_INDEX}\n|---|---|---|---|\n"
    row = "| T01／R01／N01 | 输出 1 | T01-AC01 通过 | 通过 |\n"
    defects = {
        "commented": f"<!--\n{header}{row}-->\n",
        "detached": header + "\nA detached row\n\n" + row,
        "after-fence": header + "```text\nnot part of the table\n```\n" + row,
        "after-prose": header.replace("\n\n", "\n\n说明文字。\n", 1) + row,
        "comment-separator": header.replace("|---", "|-<!-- hidden -->--", 1) + row,
        "raw-html": f"<pre>\n{header}{row}</pre>\n",
    }
    steps = {"R01": {"task_id": "T01", "acs": ["T01-AC01"]}}
    verify_runtime_index("```html\n<!--\n```\n\n    <!--\n\n" + header + row, ["N01"], steps)
    with pytest.raises(SystemExit, match="human-readable acceptance index"):
        verify_runtime_index(defects[defect], ["N01"], steps)


def test_publication_rolls_back_when_second_output_cannot_be_linked(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS.parent))
    from runtime_harness import Runtime, fingerprint as binding

    workspace = tmp_path / ".tmp/sdd/build_plan"
    candidates = workspace / "runtime/golden/attempts/R01/r01"
    candidates.mkdir(parents=True)
    outputs = {}
    for name in ("first", "second"):
        path = candidates / f"{name}.csv"
        path.write_text(name, encoding="utf-8")
        outputs[f"results/data/{name}.csv"] = binding(path)
    state_path = workspace / "state.json"
    state = {"runtime": {"audits": {"N01": {"audit_id": "audit"}}}}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    runtime = Runtime({}, lambda event: pytest.fail(f"Unexpected save {event}"), None, state_path=state_path)
    runtime.root = tmp_path
    runtime.run_id = "golden"
    runtime.runtime_root = workspace / "runtime/golden"
    runtime.data = {"published": {}}
    scope = {"node_id": "N01", "steps": {"R01": [{"facts": {
        "step_run_hash": "attempt", "step_id": "R01", "outputs": outputs,
    }}]}}
    audit = state["runtime"]["audits"]["N01"]
    real_link = os.link

    def fail_second(source, target):
        if target.name == "second.csv":
            raise OSError("synthetic link failure")
        return real_link(source, target)

    monkeypatch.setattr(os, "link", fail_second)
    with pytest.raises(OSError, match="synthetic link failure"):
        runtime.publish(audit, scope, {"audit_id": "audit"})
    assert audit == {"audit_id": "audit"}
    assert runtime.data["published"] == {}
    assert not list((tmp_path / "results").rglob("*.csv"))
    assert not list((runtime.runtime_root / "evidence").glob("*.json"))
    assert all(binding(Path(output["path"])) == output for output in outputs.values())


@pytest.mark.parametrize("reopen", [False, True])
def test_structured_proposal_to_runtime_finish(proposal, tmp_path, reopen):
    plan, task = proposal
    project = Scenario.__new__(Scenario)
    project.root = tmp_path
    project.state = tmp_path / ".tmp/sdd/build_plan/state.json"
    workspace = project.state.parent
    runtime = workspace / "runtime/golden"

    def put(name, data):
        return project.file(str(name), data)

    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    def manifest():
        return json.loads((workspace / "runtime/manifest.json").read_text(encoding="utf-8"))

    project.cli("verify-build-plan", "--artifact", plan)
    project.cli("verify-task-spec", "--artifact", task, "--build-plan", plan)
    put(plan, plan.read_text(encoding="utf-8").replace("decision: pending", "decision: approved"))
    put(task, task.read_text(encoding="utf-8").replace("approval_status: pending", "approval_status: approved"))
    approval = put(workspace / "spec-approval.json", {
        "build_plan_sha256": fingerprint(plan), "task_specs": {"T01": fingerprint(task)},
        "approved_at": "2020-01-01T00:00:00+00:00", "user_message_ref": "spec-approval",
    })
    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("add", "specs")
    git("-c", "commit.gpgsign=false", "commit", "-m", "approved specs")
    base = git("rev-parse", "HEAD")
    project.cli("init", "--build-plan", plan, "--evidence", approval)
    project.cli("register-task", "T01", "--action", "resume_or_redispatch_implementer", "--evidence", task)
    script = put("scripts/build/main.py", "from pathlib import Path\nimport sys\n"
                 "for name in sys.argv[1:]: Path(name).write_bytes(b'1\\n')\n")
    git("add", str(script))
    git("-c", "commit.gpgsign=false", "commit", "-m", "implement counting fixture")
    head = git("rev-parse", "HEAD")
    for state, content in [
        ("task_review_pending", f"Task T01\nStatus: DONE\nCommit: {head}\nTDD Evidence"),
        ("task_complete", f"Task T01\nReviewed HEAD: {head}\nVerdict: PASS"),
        ("final_review_pending", None),
        ("building_audit_pending", f"Overall Review\nHEAD: {head}\nVerdict: PASS"),
    ]:
        args = ["--evidence", put(workspace / f"building/{state}.md", content)] if content else []
        project.cli("transition", "--to", state, *args)

    building_identity = {"code_commit": head, "build_plan_sha256": fingerprint(plan),
                         "task_specs": {"T01": fingerprint(task)}}
    outputs = ["results/data/region/status.csv", "results/plot/count.png", "results/smoke_test/example/report.md"]
    contract = put(runtime / "evidence/contract.json", {
        **building_identity, "run_id": "golden", "code_root": str(tmp_path), "inputs": {},
        "nodes": {"N01": {"needs": []}}, "steps": {"R01": {
            "node": "N01", "task_id": "T01", "acs": ["T01-AC01"], "needs": [], "inputs": [], "outputs": outputs,
            "command": [sys.executable, "scripts/build/main.py", *["{output:" + output + "}" for output in outputs]],
            "executable_sha256": fingerprint(Path(sys.executable)), "resources": {"timeout_seconds": 15},
        }},
    })
    building_fields = {"audit_id": "B001", "assessment": "PASS", "limitations": "[]"}
    building_template = render("building-audit-report.md", building_fields)
    old_index_start = building_template.index("## 6. 任务验收索引")
    old_index_end = building_template.index("## 审计门禁记录", old_index_start)
    index = "## 6. 任务验收索引\n\n" + AUDIT_HEADER + "\n|---|---|---|---|---|\n" + AUDIT_ROW + "\n\n"
    report = put("audits/building/building.md", building_template[:old_index_start] + index + building_template[old_index_end:])
    project.cli("transition", "--to", "building_audit_gate", "--evidence", report)
    gate = put(workspace / "building/gate.json", {
        "ledger": str(put(workspace / "building/progress.md",
                          f"Task T01: complete (commits {base}..{head}, review clean) · {fingerprint(task)}")),
        "tasks": {"T01": {"brief": str(put(workspace / "building/brief.md", task.read_text(encoding="utf-8")))}},
    })
    gate_data = json.loads(gate.read_text(encoding="utf-8"))
    audit_binding = {"report_sha256": fingerprint(report), "contract_sha256": fingerprint(contract)}
    put(gate, gate_data | {"audit_binding": audit_binding | {"report_sha256": "0" * 64}})
    project.cli("gate", "--artifact", tmp_path, "--evidence", gate, denied="report fingerprint mismatch")
    put(gate, gate_data | {"audit_binding": audit_binding})
    project.cli("gate", "--artifact", tmp_path, "--evidence", gate)
    building_manifest = json.loads((workspace / "building/manifest.json").read_text(encoding="utf-8"))
    assert building_manifest["audit_binding"] == audit_binding
    building_receipt = put(runtime / "evidence/building.json", {
        **building_identity, "contract_sha256": fingerprint(contract), "audit_id": "B001", "assessment": "PASS",
        "report_sha256": fingerprint(report), "report_presented_at": "2024-01-01T00:00:00+00:00",
        "accepted_at": "2024-01-01T00:00:01+00:00", "acceptance_ref": "building-acceptance",
        "spec_approval_ref": "spec-approval", "audit_user_decision": "accepted", "accepted_audit_id": "B001",
        "limitations": [], "accepted_limitations": [],
    })
    current_building_receipt = building_receipt.read_text(encoding="utf-8")
    put(building_receipt, json.loads(current_building_receipt) | {"spec_approval_ref": "stale-spec-approval"})
    project.cli("runtime-init", "--artifact", contract, "--evidence", building_receipt, denied="current Spec approval")
    put(building_receipt, current_building_receipt)
    project.cli("runtime-init", "--artifact", contract, "--evidence", building_receipt)
    assert manifest()["schema_version"] == 2
    assert manifest()["building_audit"]["binding"]["contract_sha256"] == fingerprint(contract)
    project.cli("runtime-run", "R01", "--actor", "executor", denied="not authorized")
    project.cli("runtime-authorize", "--evidence", put(runtime / "evidence/authorization.json", {
        "audit_id": "B001", "contract_sha256": fingerprint(contract), "authorized_at": clock(),
        "user_message_ref": "runtime-authorization", "steps": ["R01"],
    }))

    def run_and_review(verdict="PASS", route=None, extra=()):
        facts = project.cli("runtime-run", "R01", "--actor", "executor", *extra)
        assert Path(facts["report"]["path"]).parent == runtime / "reports"
        assert all(Path(binding["path"]).is_relative_to(runtime / "attempts/R01") for binding in facts["outputs"].values())
        statuses = {"T01-AC01": verdict}
        fields = {"step_run_hash": facts["step_run_hash"], "verdict": verdict, "return_stage": route or "none",
                  "ac_statuses": json.dumps(statuses)}
        number = facts["attempt"]
        review = put(runtime / f"reviews/step-{number}.md",
                     "# Runtime Task Review\n" + "\n".join(f"- `{field}: {value}`" for field, value in fields.items()))
        project.cli("runtime-review", "R01", "--evidence", put(runtime / f"evidence/review-{number}.json", {
            "step_run_hash": facts["step_run_hash"], "reviewer": "step-reviewer", "verdict": verdict,
            "acs": statuses, "route": route, "report": str(review),
        }))
        return facts

    failed = run_and_review("CHANGES_REQUIRED", "Runtime")
    retry = put(runtime / "evidence/retry.json", {"step_run_hash": failed["step_run_hash"],
                "reason": "Synthetic retry", "changes": ["state"]})
    facts = run_and_review(extra=("--evidence", retry))
    assert not (tmp_path / "results").exists()

    def audit(scope, sequence):
        if scope == "N01":
            summary = project.cli("runtime-report", scope)
            assert Path(summary["path"]).parent == runtime / "reports"
        binding = project.cli("runtime-scope", scope)
        fields = {"audit_scope": binding["audit_scope"], "runtime_audit_id": binding["audit_id"],
                  "runtime_audit_status": "PASS", "return_stage": "none",
                  "limitations": "[]"}
        content = render("runtime-audit-report.md", fields)
        content = content.replace("| | | | |\n\n## 审计门禁记录", "| T01／R01／N01 | 计数为 1 | T01-AC01 通过，覆盖合成数据 | 通过 |\n\n## 审计门禁记录")
        report = put(f"audits/runtime/{sequence}-{scope}.md", content)
        assert fingerprint(contract) not in building_template
        assert binding["scope_hash"] not in content
        evidence = put(runtime / f"evidence/audit-{sequence}.json", {
            "scope_hash": binding["scope_hash"], "auditor": "formal-auditor", "report": str(report),
            "assessment": "PASS", "limitations": [], "route": None, "report_sha256": fingerprint(report),
        })
        if sequence == 1:
            for altered in (
                content.replace("| 当前状态 |", "| 事实记录与审查链接 | 当前状态 |"),
                content.replace("| T01／R01／N01 | 计数为 1 | T01-AC01 通过，覆盖合成数据 | 通过 |", "| | | | |"),
                content.replace("T01-AC01 通过", "所列条件通过"),
                content.replace("T01／R01／N01", "T01／R01"),
            ):
                put(report, altered)
                put(evidence, json.loads(evidence.read_text(encoding="utf-8")) | {"report_sha256": fingerprint(report)})
                project.cli("runtime-audit", scope, "--evidence", evidence, denied="human-readable acceptance index")
                assert scope not in manifest()["audits"]
            put(report, content + "\n额外内容\n")
            put(evidence, json.loads(evidence.read_text(encoding="utf-8")) | {"report_sha256": fingerprint(report)})
            put(report, content)
            project.cli("runtime-audit", scope, "--evidence", evidence, denied="report fingerprint mismatch")
            put(evidence, json.loads(evidence.read_text(encoding="utf-8")) | {"report_sha256": fingerprint(report)})
        project.cli("runtime-audit", scope, "--evidence", evidence)
        return binding

    def accept(scope, binding, sequence, denied=None, **overrides):
        evidence = put(runtime / f"evidence/accept-{sequence}.json", {
            "audit_id": binding["audit_id"], "scope_hash": binding["scope_hash"], "accepted_at": clock(),
            "user_message_ref": f"user-accept-{sequence}", "accepted_limitations": [], **overrides,
        })
        return project.cli("runtime-accept", scope, "--evidence", evidence, denied=denied)

    node = audit("N01", 1)
    node_report = tmp_path / "audits/runtime/1-N01.md"
    original = node_report.read_bytes()
    node_report.write_bytes(original + b"\nchanged after registration\n")
    accept("N01", node, 1, denied="fingerprint changed")
    assert "acceptance" not in manifest()["audits"]["N01"]
    node_report.write_bytes(original)
    finish = put("reports/runtime-finish.md", "# 已验收结果\n\n## 阶段性结果\n\n计数为 1。\n\n## 结果局限\n\n合成数据。\n")
    project.cli("runtime-finish", "--artifact", finish, denied="Runtime Audit gate")
    accept("N01", node, 1, denied="acceptance scope mismatch", scope_hash="bad-hash")
    conflict = put("results/smoke_test/golden/unrelated.md", "unrelated")
    accept("N01", node, 1, denied="already exists")
    assert conflict.read_text(encoding="utf-8") == "unrelated"
    assert not (tmp_path / "results/data/golden/region/status.csv").exists()
    assert "acceptance" not in manifest()["audits"]["N01"]
    conflict.unlink()
    accept("N01", node, 1)
    published = tmp_path / "results/data/golden/region/status.csv"
    candidate = Path(facts["outputs"][outputs[0]]["path"])
    assert published.read_bytes() == b"1\n" and os.path.samefile(published, candidate)

    sequence = 2
    if reopen:
        published.unlink()
        assert candidate.read_bytes() == b"1\n"
        project.cli("runtime-scope", "final_chain", denied="fingerprint changed")
        project.cli("runtime-return", "N01", "--evidence", put(runtime / "evidence/return.json", {
            "audit_id": node["audit_id"], "scope_hash": node["scope_hash"], "route": "Runtime", "reason": "Lost result",
            "steps": ["R01"], "changes": ["state"], "rerun_authorized": True,
            "user_message_ref": "recover-artifact", "decided_at": clock(),
            "artifact_loss": [{"step_id": "R01", "step_run_hash": facts["step_run_hash"], "output": outputs[0]}],
        }))
        facts = run_and_review()
        foreign = put("results/plot/golden-r02/foreign.png", "unrelated Runtime result")
        node = audit("N01", sequence)
        accept("N01", node, sequence)
        sequence += 1
        assert (tmp_path / "results/data/golden-r03/region/status.csv").read_bytes() == b"1\n"
        assert foreign.read_text(encoding="utf-8") == "unrelated Runtime result"
        assert not (tmp_path / "results/data/golden-r02").exists()
        assert (tmp_path / "results/plot/golden/count.png").read_bytes() == b"1\n"

    final = audit("final_chain", sequence)
    assert final["audit_id"] != node["audit_id"]
    assert final["scope_hash"] != node["scope_hash"]
    assert len(list((tmp_path / "audits/runtime").glob("*.md"))) == sequence
    project.cli("runtime-finish", "--artifact", finish, denied="Runtime Audit gate")
    accept("final_chain", final, sequence, denied="its own user decision", user_message_ref="user-accept-1")
    accept("final_chain", final, sequence)
    invalid = put("reports/invalid-finish.md", finish.read_text(encoding="utf-8") + "\n## 技术清单\n额外章节。\n")
    project.cli("runtime-finish", "--artifact", invalid, denied="exactly the sections")
    result_path = Path(final["outputs"]["R01"][outputs[0]]["path"])
    result_path.unlink()
    result_path.write_bytes(b"tampered")
    project.cli("runtime-finish", "--artifact", finish, denied="fingerprint changed")
    result_path.write_bytes(b"1\n")
    completed = project.cli("runtime-finish", "--artifact", finish)
    assert completed["chain_hash"] == final["scope_hash"]
    assert completed["result_manifest"] == final["outputs"] == manifest()["finish_results"]["result_manifest"]
    for logical, delivery in completed["result_manifest"]["R01"].items():
        _, category, name = logical.split("/", 2)
        version = "golden-r03" if reopen else "golden"
        assert Path(delivery["path"]) == tmp_path / "results" / category / version / name
        assert fingerprint(Path(delivery["path"])) == delivery["sha256"]
    assert sorted(item.suffix for item in (tmp_path / "audits/runtime").iterdir()) == [".md"] * sequence
