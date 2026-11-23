"""Exercise two independent Building gates and their shared final Runtime Audit."""

from datetime import datetime, timezone
import json
import sys
from pathlib import Path

import pytest

from test_proposal_paths import AUDIT_ROW, ENTRY, OUTPUT, replace, write_proposal
from test_runtime_harness import AUDIT_TEMPLATE, Scenario, TEMPLATES, fingerprint
from test_unit_git import git, state_path


def now():
    return datetime.now(timezone.utc).isoformat()


class BatchedScenario(Scenario):
    def __init__(self, root):
        self.root = self.unit = root
        self.state = state_path(root)
        self.plan, first = write_proposal(root)
        self.tasks = {"T01": first}
        self.tasks["T02"] = self.file(
            "specs/tasks/task-02/task-02.md",
            first.read_text(encoding="utf-8").replace("T01", "T02").replace("main.py", "next.py"),
        )
        replace(first, "approval_status: pending", "approval_status: approved")
        replace(self.plan, "decision: pending", "decision: approved")
        replace(self.plan, OUTPUT, OUTPUT + (
            "\n| O04 | First review | results/data/second.csv | Data | Runtime | T01-AC01 |"
            "\n| O05 | Later batch | results/data/third.csv | Data | Runtime | T02-AC01 |"
        ))
        replace(self.plan, ENTRY, ENTRY + "\n| T02 | scripts/build/next.py | 新增 |")
        replace(self.plan, "| Count | 无 | T01-AC01 |",
                "| Count | 无 | T01-AC01 |\n"
                "| T02 | [Task MD](tasks/task-02/task-02.md) | Count | T01 | T02-AC01 |")
        replace(self.plan, "| R01 | T01 | 无 | Count | 无 | Smoke |",
                "| R01 | T01 | 无 | Count | 无 | Smoke |\n"
                "| R02 | T01 | R01、N01 | Count | 无 | Smoke |\n"
                "| R03 | T02 | R02、N02 | Count | 无 | Smoke |")
        replace(self.plan,
                "| 节点 ID | 节点目的 | 包含的运行步骤 | 前置节点 | 阶段性成果与验收条件 | 用户授权范围 |\n"
                "|---|---|---|---|---|---|\n| N01 | Count | R01 | 无 | Outputs | All |",
                "| 节点 ID | 节点目的 | 建设批次 | 前置建设要求 | 包含的运行步骤 | Runtime 前置节点 | 阶段性成果与验收条件 |\n"
                "|---|---|---|---|---|---|---|\n"
                "| N01 | Count | B01 | 无 | R01 | 无 | Outputs |\n"
                "| N02 | Count | B01 | 无 | R02 | N01 | Outputs |\n"
                "| N03 | Count | B02 | N01、N02 已验收 | R03 | N02 | Outputs |")
        git(root, "init", "--quiet")
        self.source = self.file("input.txt", "synthetic")
        git(root, "add", "specs", "input.txt")
        git(root, "commit", "--quiet", "-m", "proposal")

    def approval(self, batch, *task_ids, approved_at=None, message_ref=None):
        return self.file(f".tmp/{batch}-approval.json", {
            "batch_id": batch, "build_plan_sha256": fingerprint(self.plan),
            "task_specs": {task: fingerprint(self.tasks[task]) for task in task_ids},
            "approved_at": approved_at or now(), "user_message_ref": message_ref or f"user-spec-{batch}",
        })

    def build(self, batch, task_id, *, denied_message_ref=None, reject_worktree_report=False, legacy_report=False):
        self.batch = batch
        self.directory = self.state.parent.relative_to(self.root) / "building" / batch
        self.runtime_dir = self.state.parent.relative_to(self.root) / "runtime" / batch
        spec = self.tasks[task_id]
        self.cli("register-task", task_id, "--action", "resume_or_redispatch_implementer", "--evidence", spec)
        base = git(self.root, "rev-parse", "HEAD").stdout.strip()
        script = self.file("scripts/build/" + ("main.py" if batch == "B01" else "next.py"),
                           "import pathlib, sys\nsource, target = map(pathlib.Path, sys.argv[1:])\n"
                           "target.write_text(source.read_text() + '!')\n")
        git(self.root, "add", script)
        git(self.root, "commit", "--quiet", "-m", f"build {batch}")
        head = git(self.root, "rev-parse", "HEAD").stdout.strip()
        for status, content in (
            ("task_review_pending", f"Task {task_id}\nStatus: DONE\nCommit: {head}\nTDD Evidence"),
            ("task_complete", f"Task {task_id}\nReviewed HEAD: {head}\nVerdict: PASS"),
            ("final_review_pending", None),
            ("building_audit_pending", f"Overall Review\nHEAD: {head}\nVerdict: PASS"),
        ):
            evidence = ["--evidence", self.file(self.directory / (status + ".md"), content)] if content else []
            self.cli("transition", "--to", status, *evidence)
        self.contract = {
            "run_id": batch, "code_root": str(self.root), "code_commit": head,
            "build_plan_sha256": fingerprint(self.plan), "task_specs": {task_id: fingerprint(spec)},
            "inputs": {"source": {"path": "input.txt", "sha256": fingerprint(self.source),
                                  "identity": "synthetic fixture", "qualification": "test fixture"}},
            "nodes": {"N01": {"needs": []}, "N02": {"needs": ["N01"]}} if batch == "B01"
            else {"N03": {"needs": ["N02"]}},
            "steps": {},
        }
        paths = ["results/data/region/status.csv", "results/data/second.csv", "results/data/third.csv"]
        for i in ([1, 2] if batch == "B01" else [3]):
            source = "{input:source}" if i == 1 else "{upstream:R" + f"{i-1:02d}:" + paths[i-2] + "}"
            self.contract["steps"][f"R{i:02d}"] = {
                "node": f"N{i:02d}", "task_id": task_id, "acs": [task_id + "-AC01"],
                "needs": [f"R{i-1:02d}"] if i > 1 else [], "inputs": ["source"] if i == 1 else [],
                "outputs": [paths[i-1]], "executable_sha256": fingerprint(Path(sys.executable)),
                "resources": {"timeout_seconds": 15},
                "command": [sys.executable, script.relative_to(self.root).as_posix(), source,
                            "{output:" + paths[i-1] + "}"],
            }
        report = (TEMPLATES / "building-audit-report.md").read_text(encoding="utf-8")
        report = report.replace("<当前审计 ID>", "building-" + batch).replace(
            "assessment: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED", "assessment: PASS")
        report = report.replace("`limitations: []`（填写用户需接受的限制，使用 JSON 字符串数组）", "`limitations: []`")
        report = report.replace("| | | | | |\n\n## 审计门禁记录", f"{AUDIT_ROW.replace('T01', task_id)}\n\n## 审计门禁记录")
        relative_report = Path(f"audits/building/{batch}.md")
        if reject_worktree_report:
            for invalid in (self.root / relative_report, self.unit / relative_report.parent / "nested" / relative_report.name):
                misplaced = self.file(invalid, report)
                before = self.state.read_bytes()
                self.cli("transition", "--to", "building_audit_gate", "--evidence", misplaced,
                         denied="formal Building Audit")
                assert self.state.read_bytes() == before
        if legacy_report:
            report_path = self.file(relative_report, report)
            state = json.loads(self.state.read_text(encoding="utf-8"))
            state.update(status="building_audit_gate", phase="building_audit",
                         next_allowed_actions=["wait_for_user_decision"])
            state["evidence"]["building_audit"] = [{"path": str(report_path), "sha256": fingerprint(report_path)}]
            self.file(self.state, state)
        else:
            report_path = self.file(self.unit / relative_report, report)
            self.cli("transition", "--to", "building_audit_gate", "--evidence", report_path)
        contract_path = self.attachment("contract", self.contract)
        gate = self.file(self.directory / "gate.json", {
            "ledger": str(self.file(self.directory / "progress.md",
                                    f"Task {task_id}: complete (commits {base}..{head}, review clean) · {fingerprint(spec)}")),
            "tasks": {task_id: {"brief": str(self.file(self.directory / "brief.md", spec.read_text(encoding="utf-8")))}},
            "audit_binding": {"report_sha256": fingerprint(report_path), "contract_sha256": fingerprint(contract_path)},
        })
        self.cli("gate", "--evidence", gate)
        self.building = {
            "audit_id": "building-" + batch, "report_sha256": fingerprint(report_path), "assessment": "PASS",
            **{key: self.contract[key] for key in ("code_commit", "build_plan_sha256", "task_specs")},
            "contract_sha256": fingerprint(contract_path), "report_presented_at": now(),
            "accepted_at": now(), "acceptance_ref": f"user-building-{batch}", "spec_approval_ref": f"user-spec-{batch}",
            "audit_user_decision": "accepted", "accepted_audit_id": "building-" + batch,
            "limitations": [], "accepted_limitations": [],
        }
        if denied_message_ref:
            stale = {**self.building, "acceptance_ref": denied_message_ref}
            self.cli("runtime-init", "--artifact", contract_path, "--evidence",
                     self.attachment("building-stale", stale), denied="already used")
        self.cli("runtime-init", "--artifact", contract_path, "--evidence", self.attachment("building", self.building))

    def attachment(self, name, data):
        return self.file(self.runtime_dir / "evidence" / (name + ".json"), data)

    def authorize_steps(self, *steps, denied=None, message_ref=None):
        evidence = self.attachment("auth-" + "-".join(steps), {
            "audit_id": self.building["audit_id"], "contract_sha256": self.building["contract_sha256"],
            "authorized_at": now(), "user_message_ref": message_ref or "user-runtime-" + "-".join(steps), "steps": list(steps),
        })
        self.cli("runtime-authorize", "--evidence", evidence, denied=denied)

    def run_and_review(self, step, actor="executor"):
        attempt = self.cli("runtime-run", step, "--actor", actor)
        ac = self.contract["steps"][step]["acs"][0]
        fields = {"step_run_hash": attempt["step_run_hash"], "verdict": "PASS", "return_stage": "none",
                  "ac_statuses": json.dumps({ac: "PASS"})}
        report = self.file(self.runtime_dir / "reviews" / (step + ".md"), "# Runtime Task Review\n" +
                           "\n".join(f"- `{key}: {value}`" for key, value in fields.items()))
        self.cli("runtime-review", step, "--evidence", self.attachment("review-" + step, {
            "step_run_hash": attempt["step_run_hash"], "reviewer": "step-reviewer", "verdict": "PASS",
            "acs": {ac: "PASS"}, "route": None, "report": str(report),
        }))
        return attempt

    def audit_scope(self, name, *, auditor="independent-auditor", denied=None, reject_worktree_report=False):
        if name != "final_chain":
            self.cli("runtime-report", name)
        scope = self.cli("runtime-scope", name)
        rows = []
        for number in (range(1, 4) if name == "final_chain" else [int(name[1:])]):
            task = "T02" if number == 3 else "T01"
            rows.append(f"| {task}、R{number:02d}、N{number:02d} | Fixture | {task}-AC01 | PASS |")
        report = AUDIT_TEMPLATE.read_text(encoding="utf-8")
        report = report.replace("| | | | |\n\n## 审计门禁记录",
                                "\n".join(rows) + "\n\n## 审计门禁记录")
        report = report.replace("audit_scope: milestone | final_chain", f"audit_scope: {scope['audit_scope']}")
        report = report.replace("runtime_audit_id: <当前审计 ID>", f"runtime_audit_id: {scope['audit_id']}")
        report = report.replace("runtime_audit_status: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED",
                                "runtime_audit_status: PASS")
        report = report.replace("return_stage: Proposal | Building | Runtime | none", "return_stage: none")
        report = report.replace("`limitations: []`（将接受范围内的限制写为 JSON 字符串数组，单独成行）", "`limitations: []`")
        relative_report = Path("audits/runtime") / (name + ".md")
        report_path = self.file(self.unit / relative_report, report)
        receipt = {
            "scope_hash": scope["scope_hash"], "auditor": auditor, "report": str(report_path),
            "report_sha256": fingerprint(report_path), "assessment": "PASS", "limitations": [], "route": None,
        }
        if reject_worktree_report:
            misplaced = self.file(relative_report, report)
            before = self.state.read_bytes()
            self.cli("runtime-audit", name, "--evidence",
                     self.attachment("misplaced-" + name, {**receipt, "report": str(misplaced)}),
                     denied="formal Runtime Audit")
            assert self.state.read_bytes() == before
        return self.cli("runtime-audit", name, "--evidence", self.attachment("audit-" + name, receipt), denied=denied)

    def accept_scope(self, name, audit, *, denied=None, message_ref=None):
        self.cli("runtime-accept", name, "--evidence", self.attachment("accept-" + name, {
            "audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"], "accepted_at": now(),
            "user_message_ref": message_ref or f"user-accept-{name}", "accepted_limitations": [],
        }), denied=denied)


def test_two_batches_use_separate_gates_and_finalize_all_accepted_results(tmp_path):
    case = BatchedScenario(tmp_path)
    premature = case.approval("B02", "T02")
    case.cli("init", "--build-plan", case.plan, "--evidence", premature, denied="eligible batch_id B01")
    case.cli("init", "--build-plan", case.plan, "--evidence", case.approval("B01", "T01", "T02"),
             denied="exactly the eligible Task")
    case.cli("init", "--build-plan", case.plan, "--evidence", case.approval("B01", "T01"))
    case.cli("register-task", "T02", "--action", "resume_or_redispatch_implementer", "--evidence",
             case.tasks["T02"], denied="differs from fresh Spec approval")
    case.build("B01", "T01", denied_message_ref="user-spec-B01")
    case.authorize_steps("R03", denied="unknown step")
    case.cli("runtime-scope", "final_chain", denied="requires all Building batches")
    case.cli("runtime-next-batch", denied="accept every current batch milestone")
    case.authorize_steps("R01", "R02", message_ref="user-spec-B01", denied="already used")
    case.authorize_steps("R01", message_ref="user-building-B01")
    case.authorize_steps("R02")
    case.run_and_review("R01", actor="first-batch-executor")
    first_audit = case.audit_scope("N01")
    case.accept_scope("N01", first_audit, message_ref="user-building-B01", denied="already used")
    case.accept_scope("N01", first_audit)
    case.cli("runtime-next-batch", denied="accept every current batch milestone")
    case.run_and_review("R02")
    case.accept_scope("N02", case.audit_scope("N02"))
    assert case.cli("runtime-next-batch")["next_batch"] == "B02"
    replace(case.tasks["T02"], "approval_status: pending", "approval_status: approved")
    stale = case.approval("B02", "T02", approved_at="2020-01-01T00:00:00+00:00")
    case.cli("proposal-rebind", "--build-plan", case.plan, "--evidence", stale, denied="fresh Spec approval")
    reused = case.approval("B02", "T02", message_ref="user-runtime-R02")
    case.cli("proposal-rebind", "--build-plan", case.plan, "--evidence", reused, denied="fresh Spec approval")
    replace(case.plan, "| N01 | Count |", "| N01 | Changed |")
    case.cli("proposal-rebind", "--build-plan", case.plan, "--evidence", case.approval("B02", "T02"),
             denied="completed Building batch plan rows changed")
    replace(case.plan, "| N01 | Changed |", "| N01 | Count |")
    case.cli("proposal-rebind", "--build-plan", case.plan, "--evidence", case.approval("B02", "T02"))
    git(tmp_path, "add", "specs")
    git(tmp_path, "commit", "--quiet", "-m", "approve later task")
    case.build("B02", "T02", denied_message_ref="user-spec-B01")
    case.cli("runtime-run", "R03", "--actor", "executor", denied="not authorized")
    case.authorize_steps("R03", message_ref="user-building-B01", denied="already used by an earlier batch")
    case.authorize_steps("R03")
    result = case.run_and_review("R03")
    assert Path(result["outputs"]["results/data/third.csv"]["path"]).read_text(encoding="utf-8") == "synthetic!!!"
    audit = case.audit_scope("N03")
    stale_return = case.attachment("return-N03-stale", {
        "route": "Building", "reason": "synthetic review decision", "decided_at": now(),
        "user_message_ref": "user-spec-B01", "audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"],
    })
    case.cli("runtime-return", "N03", "--evidence", stale_return, denied="already used by an earlier batch")
    current_return = case.attachment("return-N03-current", {
        **json.loads(stale_return.read_text(encoding="utf-8")), "user_message_ref": "user-runtime-R03",
    })
    case.cli("runtime-return", "N03", "--evidence", current_return, denied="already used")
    case.accept_scope("N03", audit, message_ref="user-building-B01", denied="already used by an earlier batch")
    case.accept_scope("N03", audit)
    case.audit_scope("final_chain", auditor="first-batch-executor", denied="independent of all executors")
    scope = case.cli("runtime-scope", "final_chain")
    assert [item["node_id"] for item in scope["nodes"]] == ["N01", "N02", "N03"]
    previous_output = Path(scope["outputs"]["R01"]["results/data/region/status.csv"]["path"])
    contents = previous_output.read_bytes()
    previous_output.write_bytes(b"tampered")
    state_before = case.state.read_bytes()
    case.cli("runtime-scope", "final_chain", denied="fingerprint changed")
    assert case.state.read_bytes() == state_before
    previous_output.write_bytes(contents)
    case.accept_scope("final_chain", case.audit_scope("final_chain"))
    finish = case.file("reports/finish.md", "# Synthetic\n\n## 阶段性结果\n\nFixture\n\n## 结果局限\n\nSynthetic")
    delivery = case.cli("runtime-finish", "--artifact", finish)
    assert set(delivery["result_manifest"]) == {"R01", "R02", "R03"}


def test_current_build_does_not_change_another_batch_main_entry(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'skills/subagent-driven-development/scripts'
    monkeypatch.syspath_prepend(str(scripts))
    from sdd_layout import verify_building_paths

    scenario = BatchedScenario(tmp_path)
    baseline = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    main = scenario.file("scripts/build/main.py", "print('first')\n")
    git(tmp_path, "add", main)
    git(tmp_path, "commit", "--quiet", "-m", "first batch")
    first = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    verify_building_paths(tmp_path, scenario.plan, baseline, first, task_ids={"T01"})

    other = scenario.file("scripts/build/next.py", "print('later')\n")
    git(tmp_path, "add", other)
    git(tmp_path, "commit", "--quiet", "-m", "out of scope")
    out_of_scope = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(ValueError, match="main entry changed outside the current Building batch"):
        verify_building_paths(tmp_path, scenario.plan, baseline, out_of_scope, task_ids={"T01"})


def linked_case(tmp_path):
    case = BatchedScenario(tmp_path)
    linked = tmp_path / ".tmp/worktrees/linked"
    linked.parent.mkdir(parents=True)
    git(tmp_path, "worktree", "add", "--detach", str(linked))
    approval = case.approval("B01", "T01")
    case.file(approval, {**json.loads(approval.read_text(encoding="utf-8")), "worktree_path": str(linked)})
    case.root, case.state = linked, state_path(linked)
    case.cli("init", "--build-plan", case.plan, "--evidence", approval)
    return case


def test_linked_worktree_registers_formal_audits_only_at_functional_unit_root(tmp_path):
    case = linked_case(tmp_path)
    case.build("B01", "T01", reject_worktree_report=True)
    case.authorize_steps("R01")
    case.run_and_review("R01")
    audit = case.audit_scope("N01", reject_worktree_report=True)
    case.accept_scope("N01", audit)
    state = json.loads(case.state.read_text(encoding="utf-8"))
    assert Path(state["evidence"]["building_audit"][0]["path"]) == tmp_path / "audits/building/B01.md"
    assert Path(state["runtime"]["audits"]["N01"]["report"]["path"]) == tmp_path / "audits/runtime/N01.md"
    assert Path(state["runtime"]["audits"]["N01"]["summary"]["path"]).is_relative_to(case.state.parent)


def test_linked_worktree_keeps_registered_legacy_report_paths(tmp_path):
    case = linked_case(tmp_path)
    case.build("B01", "T01", legacy_report=True)
    building = case.root / "audits/building/B01.md"
    state = json.loads(case.state.read_text(encoding="utf-8"))
    assert Path(state["runtime"]["building_audit"]["report"]["path"]) == building
    assert state["runtime"]["building_audit"]["report"]["sha256"] == fingerprint(building)

    case.authorize_steps("R01")
    case.run_and_review("R01")
    audit = case.audit_scope("N01")
    # Reconstruct the already registered report and matching receipt from the old layout.
    formal = Path(audit["report"]["path"])
    legacy = case.root / "audits/runtime/N01.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    formal.rename(legacy)
    state = json.loads(case.state.read_text(encoding="utf-8"))
    old_audit = state["runtime"]["audits"]["N01"]
    old_audit["report"]["path"] = str(legacy)
    receipt = Path(old_audit["receipt"]["path"])
    old_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    case.file(receipt, {**old_receipt, "report": str(legacy)})
    old_audit["receipt"].update(sha256=fingerprint(receipt), bytes=receipt.stat().st_size)
    case.file(case.state, state)
    case.accept_scope("N01", audit)
    accepted = json.loads(case.state.read_text(encoding="utf-8"))["runtime"]["audits"]["N01"]
    assert accepted["report"] == old_audit["report"]
    assert accepted["report"]["sha256"] == fingerprint(legacy)
