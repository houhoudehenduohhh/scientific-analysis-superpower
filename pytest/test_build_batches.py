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
        self.node_based = False
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
            ("node_id" if self.node_based else "batch_id"): batch, "build_plan_sha256": fingerprint(self.plan),
            "task_specs": {task: fingerprint(self.tasks[task]) for task in task_ids},
            "approved_at": approved_at or now(), "user_message_ref": message_ref or f"user-spec-{batch}",
        })

    def build(self, batch, task_id, *, denied_message_ref=None, audit_suffix="",
              reject_worktree_report=False, legacy_report=False, spec_approval_ref=None):
        self.batch = batch
        first = batch in {"B01", "N01"}
        step_nodes = ("N01", "N01", "N02") if self.node_based else ("N01", "N02", "N03")
        node_order = list(dict.fromkeys(step_nodes))
        nodes = {node: {"needs": [node_order[index - 1]] if index else []}
                 for index, node in enumerate(node_order)}
        self.directory = self.state.parent.relative_to(self.root) / "building" / (batch + audit_suffix)
        self.runtime_dir = self.state.parent.relative_to(self.root) / "runtime" / (batch + audit_suffix)
        spec = self.tasks[task_id]
        self.cli("register-task", task_id, "--action", "resume_or_redispatch_implementer", "--evidence", spec)
        base = git(self.root, "rev-parse", "HEAD").stdout.strip()
        script = self.file("scripts/build/" + ("main.py" if first else "next.py"),
                           "import pathlib, sys\nsource, target = map(pathlib.Path, sys.argv[1:])\n"
                           "target.write_text(source.read_text() + '!')\n" + f"# cycle: {audit_suffix}\n")
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
            "run_id": batch + audit_suffix, "code_root": str(self.root), "code_commit": head,
            "build_plan_sha256": fingerprint(self.plan), "task_specs": {task_id: fingerprint(spec)},
            "inputs": {"source": {"path": "input.txt", "sha256": fingerprint(self.source),
                                  "identity": "synthetic fixture", "qualification": "test fixture"}},
            "nodes": {node: nodes[node] for node in (set(step_nodes[:2]) if first else {step_nodes[2]})},
            "steps": {},
        }
        paths = ["results/data/region/status.csv", "results/data/second.csv", "results/data/third.csv"]
        for i in ([1, 2] if first else [3]):
            source = "{input:source}" if i == 1 else "{upstream:R" + f"{i-1:02d}:" + paths[i-2] + "}"
            self.contract["steps"][f"R{i:02d}"] = {
                "node": step_nodes[i - 1], "task_id": task_id, "acs": [task_id + "-AC01"],
                "needs": [f"R{i-1:02d}"] if i > 1 else [], "inputs": ["source"] if i == 1 else [],
                "outputs": [paths[i-1]], "executable_sha256": fingerprint(Path(sys.executable)),
                "resources": {"timeout_seconds": 15},
                "command": [sys.executable, script.relative_to(self.root).as_posix(), source,
                            "{output:" + paths[i-1] + "}"],
            }
        report = (TEMPLATES / "building-audit-report.md").read_text(encoding="utf-8")
        report = report.replace("<当前审计 ID>", "building-" + batch + audit_suffix).replace(
            "assessment: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED", "assessment: PASS")
        report = report.replace("`limitations: []`（填写用户需接受的限制，使用 JSON 字符串数组）", "`limitations: []`")
        report = report.replace("| | | | | |\n\n## 审计门禁记录", f"{AUDIT_ROW.replace('T01', task_id)}\n\n## 审计门禁记录")
        relative_report = Path(f"audits/building/{batch}{audit_suffix}.md")
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
            "audit_id": "building-" + batch + audit_suffix, "report_sha256": fingerprint(report_path), "assessment": "PASS",
            **{key: self.contract[key] for key in ("code_commit", "build_plan_sha256", "task_specs")},
            "contract_sha256": fingerprint(contract_path), "report_presented_at": now(),
             "accepted_at": now(), "acceptance_ref": f"user-building-{batch}{audit_suffix}",
            "spec_approval_ref": spec_approval_ref or f"user-spec-{batch}",
            "audit_user_decision": "accepted", "accepted_audit_id": "building-" + batch + audit_suffix,
            "limitations": [], "accepted_limitations": [],
        }
        if denied_message_ref:
            stale = {**self.building, "acceptance_ref": denied_message_ref}
            self.cli("runtime-init", "--artifact", contract_path, "--evidence",
                     self.attachment("building-stale", stale), denied="already used")
        self.cli("runtime-init", "--artifact", contract_path,
                 "--evidence", self.attachment("building", self.building))

    def attachment(self, name, data):
        return self.file(self.runtime_dir / "evidence" / (name + ".json"), data)

    def authorize_steps(self, *steps, denied=None, message_ref=None):
        evidence = self.attachment("auth-" + "-".join(steps), {
            "audit_id": self.building["audit_id"], "contract_sha256": self.building["contract_sha256"],
            "authorized_at": now(), "user_message_ref": message_ref or "user-runtime-" + "-".join(steps), "steps": list(steps),
        })
        self.cli("runtime-authorize", "--evidence", evidence, denied=denied)

    def run_and_review(self, step, actor="executor", *, route=None):
        attempt = self.cli("runtime-run", step, "--actor", actor)
        ac = self.contract["steps"][step]["acs"][0]
        verdict = "CHANGES_REQUIRED" if route else "PASS"
        ac_statuses = {ac: verdict}
        fields = {"step_run_hash": attempt["step_run_hash"], "verdict": verdict, "return_stage": route or "none",
                  "ac_statuses": json.dumps(ac_statuses)}
        report = self.file(self.runtime_dir / "reviews" / (step + ".md"), "# Runtime Task Review\n" +
                           "\n".join(f"- `{key}: {value}`" for key, value in fields.items()))
        self.cli("runtime-review", step, "--evidence", self.attachment("review-" + step, {
            "step_run_hash": attempt["step_run_hash"], "reviewer": "step-reviewer", "verdict": verdict,
            "acs": ac_statuses, "route": route, "report": str(report),
        }))
        return attempt

    def audit_scope(self, name, *, auditor="independent-auditor", denied=None, reject_worktree_report=False):
        if name != "final_chain":
            self.cli("runtime-report", name)
        scope = self.cli("runtime-scope", name)
        rows = []
        step_nodes = ("N01", "N01", "N02") if self.node_based else ("N01", "N02", "N03")
        for number, node in enumerate(step_nodes, 1):
            if name not in {node, "final_chain"}:
                continue
            task = "T02" if number == 3 else "T01"
            rows.append(f"| {task}、R{number:02d}、{node} | Fixture | {task}-AC01 | PASS |")
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


NODE_HEADER = ("| 节点 ID | 节点目的 | 前置建设要求 | 包含的 Task | "
               "包含的运行步骤 | 阶段性成果与验收条件 |")


def convert_to_node_plan(case):
    case.node_based = True
    plan = case.plan.read_text(encoding="utf-8")
    start = plan.index("| 节点 ID |")
    end = plan.index("## 批准", start)
    plan = plan[:start] + NODE_HEADER + (
        "\n|---|---|---|---|---|---|\n"
        "| N01 | Count | 无 | T01 | R01、R02 | Outputs |\n"
        "| N02 | Count | N01 已验收 | T02 | R03 | Outputs |\n\n"
    ) + plan[end:]
    case.file(case.plan, plan.replace("| R02 | T01 | R01、N01 |", "| R02 | T01 | R01 |")
              .replace("| R03 | T02 | R02、N02 |", "| R03 | T02 | R02 |"))


def test_node_plan_uses_one_prerequisite_column_and_explicit_task_scope(tmp_path):
    case = BatchedScenario(tmp_path)
    convert_to_node_plan(case)
    case.cli("verify-build-plan", "--artifact", case.plan)
    replace(case.plan, "| N02 | Count | N01 已验收 |", "| N02 | Count | 无 |")
    case.cli("verify-build-plan", "--artifact", case.plan, denied="undeclared prerequisite node N01")
    replace(case.plan, "| N02 | Count | 无 | T02 |", "| N02 | Count | N01 已验收 | T01、T02 |")
    case.cli("verify-build-plan", "--artifact", case.plan, denied="duplicate Task T01")


def test_accepted_node_survives_downstream_return_and_final_audit(tmp_path):
    case = BatchedScenario(tmp_path)
    convert_to_node_plan(case)
    git(tmp_path, "add", "specs")
    git(tmp_path, "commit", "--quiet", "-m", "use node scope")
    case.cli("init", "--build-plan", case.plan, "--evidence", case.approval("N02", "T02"),
             denied="eligible node_id N01")
    case.cli("init", "--build-plan", case.plan, "--evidence", case.approval("N01", "T01", "T02"),
             denied="exactly the eligible Task")
    case.cli("init", "--build-plan", case.plan, "--evidence", case.approval("N01", "T01"))
    analysis_manifest = case.state.parent / "analysis-state.json"
    assert json.loads(analysis_manifest.read_text(encoding="utf-8"))["node_id"] == "N01"
    case.build("N01", "T01")
    case.cli("runtime-next-batch", denied="uses runtime-next-node")
    case.cli("runtime-next-node", denied="accept the current Runtime node")
    case.authorize_steps("R01", "R02")
    case.run_and_review("R01")
    case.run_and_review("R02")
    upstream_audit = case.audit_scope("N01")
    case.accept_scope("N01", upstream_audit)
    case.cli("allowed", "advance_next_node")
    assert case.cli("runtime-next-node")["next_node"] == "N02"
    handoff = json.loads(analysis_manifest.read_text(encoding="utf-8"))
    assert handoff["next_node"] == "N02" and "node_id" not in handoff
    replace(case.tasks["T02"], "approval_status: pending", "approval_status: approved")
    case.cli("proposal-rebind", "--build-plan", case.plan, "--evidence", case.approval("N02", "T02"))
    rebound = json.loads(analysis_manifest.read_text(encoding="utf-8"))
    assert rebound["node_id"] == "N02" and "next_node" not in rebound
    git(tmp_path, "add", "specs")
    git(tmp_path, "commit", "--quiet", "-m", "approve downstream node")
    case.build("N02", "T02")
    case.authorize_steps("R03")
    attempt = case.run_and_review("R03", route="Proposal")
    case.cli("runtime-return", "R03", "--evidence", case.attachment("return", {
        "step_run_hash": attempt["step_run_hash"], "route": "Proposal", "reason": "revise downstream",
        "user_message_ref": "user-reopens-N02", "decided_at": now(),
    }))
    replace(case.plan, "| T02 | scripts/build/next.py | 新增 |", "| T02 | scripts/build/next.py | 既有 |")
    approval = case.approval("N02", "T02", message_ref="user-revised-N02")
    case.cli("proposal-rebind", "--build-plan", case.plan, "--evidence", approval)
    git(tmp_path, "add", "specs")
    git(tmp_path, "commit", "--quiet", "-m", "revise downstream setup")
    case.build("N02", "T02", audit_suffix="-r02", spec_approval_ref="user-revised-N02")
    case.authorize_steps("R03", message_ref="user-reruns-R03")
    result = case.run_and_review("R03")
    assert Path(result["outputs"]["results/data/third.csv"]["path"]).read_text(encoding="utf-8") == "synthetic!!!"
    case.accept_scope("N02", case.audit_scope("N02"))
    scope = case.cli("runtime-scope", "final_chain")
    assert [node["node_id"] for node in scope["nodes"]] == ["N01", "N02"]
    assert scope["nodes"][0]["audit_id"] == upstream_audit["audit_id"]
    original = Path(scope["outputs"]["R02"]["results/data/second.csv"]["path"])
    saved = original.read_bytes()
    original.write_bytes(b"changed")
    case.cli("runtime-scope", "final_chain", denied="fingerprint changed")
    original.write_bytes(saved)
    case.accept_scope("final_chain", case.audit_scope("final_chain"))
    delivery = case.cli("runtime-finish", "--artifact",
                        case.file("reports/finish.md", "# Synthetic\n\n## 阶段性结果\n\nFixture\n\n## 结果局限\n\nSynthetic"))
    assert set(delivery["result_manifest"]) == {"R01", "R02", "R03"}
