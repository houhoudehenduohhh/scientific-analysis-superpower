"""Runtime CLI regression tests using only temporary synthetic projects."""

import hashlib
import json
import os
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


HARNESS = Path(__file__).parents[1] / "skills/subagent-driven-development/scripts/sdd-harness.py"
AUDIT_TEMPLATE = HARNESS.parents[3] / "templates/runtime-audit-report.md"
TEMPLATES = AUDIT_TEMPLATE.parent


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runtime_smoke_output_uses_the_third_delivery_category(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS.parent))
    from runtime_harness import output_name

    assert output_name("results/smoke_test/example/report.md").parts == (
        "results", "smoke_test", "example", "report.md",
    )


def new_building_acceptance():
    accepted = datetime.now(timezone.utc)
    return {"report_presented_at": (accepted - timedelta(milliseconds=1)).isoformat(),
            "accepted_at": accepted.isoformat(), "acceptance_ref": "rebuild-accept"}


class Scenario:
    def __init__(self, root, *, independent=False, building_repair=False, overall_verdict="PASS"):
        self.root = root
        self.state = root / ".tmp/sdd/build_plan/state.json"
        self.building_audit_id = "B001"
        git = ["git", "-C", str(root)]
        subprocess.run([*git, "init", "--quiet"], check=True)
        task = self.file("specs/tasks/T01.md", """# Task T01 · Synthetic fixture
- 任务 ID：T01
- 父任务 ID（无则填无）：无
- 变更类型（原始／新增／替换）：原始
- 任务目的：Produce outputs
- 任务边界与明确排除项：Synthetic fixture only
## 输入、脚本与输出
## 验收与验证
| AC ID（完整任务 ID + -ACNN） | 验收目标 | 可观察的成功条件 | 验证方式 | 验证阶段 | 当前状态 |
|---|---|---|---|---|---|
| T01-AC01 | Synthetic | Produce an output | fixture | Runtime | 未验证 |
## 上下游影响
## 审批引用
- approval_status: approved
""")
        third_needs = "无" if independent else "S2、N01"
        second_node_needs = "无" if independent else "N01"
        plan = self.file("specs/build_plan.md", f"""# Build Plan（构建计划）
## 目标与边界
- 功能单元 Git 根目录：`{root.resolve()}`
## 源数据、算法与输出
## 项目目录结构
## 任务清单
| 任务 ID | Task MD | 目的与边界 | 前置任务／产物 | 相关 AC |
|---|---|---|---|---|
| T01 | [Task MD](tasks/T01.md) | Synthetic | 无 | T01-AC01 |
## Runtime 执行图
| 运行步骤 ID | 对应任务 | 前置步骤或节点 | 输入与输出 | 可并行步骤／互斥条件 | 完成检查 |
|---|---|---|---|---|---|
| S1 | T01 | 无 | source → s1 | 无 | output fixture |
| S2 | T01 | S1 | s1 → s2 | 无 | output fixture |
| S3 | T01 | {third_needs} | count → s3 | 无 | output fixture |
## 阶段性验收节点
| 节点 ID | 节点目的 | 包含的运行步骤 | 前置节点 | 阶段性成果与验收条件 | 用户授权范围 |
|---|---|---|---|---|---|
| N01 | fixture 1 | S1、S2 | 无 | output fixture | S1、S2 |
| N02 | fixture 2 | S3 | {second_node_needs} | output fixture | S3 |
## 批准
- decision: approved
""")
        script = self.file("job.py", "import os, pathlib, sys\n"
                           "source, target, config = map(pathlib.Path, sys.argv[1:])\n"
                           "if os.environ.get('SDD_TEST_UNAPPROVED_ENV'): sys.exit(5)\n"
                           "if os.environ.get('CHECK_NO_USER_SITE') and not sys.flags.no_user_site: sys.exit(6)\n"
                           "if config.read_text() == 'reject': sys.exit(4)\n"
                           "if config.read_text() == 'r06' and 'r06' not in target.parts: sys.exit(4)\n"
                           "if target.is_dir(): target /= 's1.txt'\n"
                           "target.write_text(source.read_text() + '!')\n")
        self.source = self.file("input.txt", "sample")
        self.config = self.file("config.txt", "copy")
        commit = [*git, "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
                  "-c", "commit.gpgsign=false", "commit", "--quiet", "-m"]
        subprocess.run([*git, "add", str(task), str(plan)], check=True)
        subprocess.run([*commit, "specs"], check=True)
        base = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        subprocess.run([*git, "add", str(script)], check=True)
        subprocess.run([*commit, "fixture"], check=True)
        initial_head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()

        approval = {
            "build_plan_sha256": fingerprint(plan), "task_specs": {"T01": fingerprint(task)},
            "approved_at": "2020-01-01T00:00:00+00:00", "user_message_ref": "user-spec-approval",
        }
        self.approval = self.file(".tmp/spec-approval.json", approval)
        # Historical approvals used the old layout before path_schema existed.
        unit_git = runpy.run_path(str(HARNESS.with_name("sdd_unit_git.py")))
        unit_git["initialize_workspace"](self.state)
        self.file(self.state, {
            "phase": "building", "status": "building_incomplete", "task_id": None, "fix_round": 0,
            "tasks": {}, "evidence": {}, "spec_approval": approval,
            "refs": {"build_plan": {"path": str(plan), "sha256": fingerprint(plan)},
                     "spec_approval": {"path": str(self.approval), "sha256": fingerprint(self.approval)}},
            "git": unit_git["prepare"](root, root),
            "next_allowed_actions": ["resume_or_redispatch_implementer"],
        })
        self.cli("verify-build-plan", "--artifact", plan)
        self.cli("register-task", "T01", "--action", "resume_or_redispatch_implementer", "--evidence", task)
        self.cli("verify-task-spec", "--artifact", task)
        implementation = self.file(".tmp/sdd/build_plan/task_review_pending.md",
                                   f"Task T01\nStatus: DONE\nCommit: {initial_head}\nTDD Evidence")
        self.cli("transition", "--to", "task_review_pending", "--evidence", implementation)
        ledger_repair = ""
        if building_repair:
            initial_review = self.file(".tmp/sdd/build_plan/first-review.md",
                                       f"Task T01\nReviewed HEAD: {initial_head}\nVerdict: CHANGES_REQUIRED")
            self.cli("transition", "--to", "fix_round_pending", "--evidence", initial_review)
            script.write_text(script.read_text(encoding="utf-8") + "# Synthetic refinement\n", encoding="utf-8")
            subprocess.run([*git, "add", str(script)], check=True)
            subprocess.run([*commit, "repair fixture"], check=True)
            repaired_head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
            fix = self.file(".tmp/sdd/build_plan/fix-round-1.md",
                            f"Task T01 fix round 1\nCommit: {repaired_head}\nTDD Evidence")
            self.cli("transition", "--to", "re_review_pending", "--evidence", fix)
            ledger_repair = f"Task T01: fix round 1/5 — fixture refinement; commits {initial_head}..{repaired_head}\n"
        head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        for state, evidence in [
            ("task_complete", f"Task T01\nReviewed HEAD: {head}\nVerdict: PASS"),
            ("final_review_pending", None),
            ("building_audit_pending", f"Overall Review\nHEAD: {head}\nVerdict: {overall_verdict}"),
        ]:
            args = ["--evidence", self.file(f".tmp/sdd/build_plan/{state}.md", evidence)] if evidence else []
            self.cli("transition", "--to", state, *args)
        self.building_report = None
        self.human_report = self.file("audits/building/report/task-01-human-report.md", "# T01 · Synthetic fixture")
        self.gate = self.file(".tmp/sdd/build_plan/building-gate.json", {
            "ledger": str(self.file(".tmp/sdd/build_plan/progress.md",
                ledger_repair + f"Task T01: complete (commits {base}..{head}, review clean) · {fingerprint(task)}\n")),
            "tasks": {"T01": {
                "brief": str(self.file(".tmp/sdd/build_plan/task-01-brief.md", task.read_text(encoding="utf-8"))),
                "human_report": str(self.human_report),
            }},
        })
        self.contract = {
            "run_id": "synthetic",
            "code_root": str(root),
            "code_commit": head,
            "build_plan_sha256": fingerprint(plan),
            "task_specs": {"T01": fingerprint(task)},
            "inputs": {"source": {"path": "input.txt", "sha256": fingerprint(self.source),
                                  "identity": "synthetic fixture", "qualification": "test fixture"}},
            "nodes": {"N01": {"needs": []}, "N02": {"needs": [] if independent else ["N01"]}},
            "steps": {},
        }
        for number, node, needs, source_arg in [
            (1, "N01", [], "{input:source}"),
            (2, "N01", ["S1"], "{upstream:S1:results/data/s1.txt}"),
            (3, "N02", [], "{input:source}") if independent else (3, "N02", ["S2"], "{upstream:S2:results/data/s2.txt}"),
        ]:
            output = f"results/data/s{number}.txt"
            self.contract["steps"][f"S{number}"] = {
                "node": node, "task_id": "T01", "acs": ["T01-AC01"],
                "needs": needs, "inputs": ["source"] if not needs else [],
                "outputs": [output], "config": {"path": "config.txt", "sha256": fingerprint(self.config)},
                "command": [sys.executable, "job.py", source_arg, "{output:" + output + "}", "{config}"],
                "executable_sha256": fingerprint(Path(sys.executable)),
                "resources": {"timeout_seconds": 15},
            }

    def file(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def cli(self, command, *args, denied=None):
        result = subprocess.run([sys.executable, str(HARNESS), str(self.state), command, *map(str, args)],
                                capture_output=True, encoding="utf-8",
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if denied is not None:
            assert result.returncode != 0
            assert denied in result.stderr, result.stderr
            return result
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if command.startswith("runtime-") else result

    def initialize(self, denied=None, *, register_gate=True, contract_path=None, receipt_path=None,
                   building_assessment="PASS", hash_free_building=False, legacy_building_fields=None,
                   nested_legacy_building_fields=False, **overrides):
        version = "" if self.building_audit_id == "B001" else "-" + self.building_audit_id
        contract = self.file(contract_path or f".tmp/contract{version}.json", self.contract)
        if self.building_report is None:
            fields = {
                "code_commit": self.contract["code_commit"], "build_plan_sha256": self.contract["build_plan_sha256"],
                "task_specs": json.dumps(self.contract["task_specs"]), "contract_sha256": fingerprint(contract),
                "limitations": "[]",
            }
            if hash_free_building:
                del fields["contract_sha256"]
            fields.update(legacy_building_fields or {})
            template = (TEMPLATES / "building-audit-report.md").read_text(encoding="utf-8")
            template = "\n".join(line for line in template.splitlines()
                                 if not any(line.startswith("- `" + key + ":") for key in fields))
            field_prefix = "    - " if nested_legacy_building_fields else "- "
            fields_heading = "\n- Legacy audit metadata\n" if nested_legacy_building_fields else "\n"
            self.building_report = self.file(f"audits/building/{self.building_audit_id}_building.md",
                template
                .replace("audit_id: <当前审计 ID>", f"audit_id: {self.building_audit_id}")
                .replace("assessment: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED", f"assessment: {building_assessment}")
                .replace("| 任务 ID | 任务目的 | AC ID | 成功条件 | 完成情况与验证范围 |",
                         "| 任务 ID | 任务目的 | AC 及完成边界 | 完成情况与未验证范围 | 人工任务报告 |")
                .replace("| | | | | |\n\n## 审计门禁记录",
                         f"| T01 | fixture | T01-AC01 | complete | [报告](report/{self.human_report.name}) |\n\n## 审计门禁记录")
                + fields_heading + "\n".join(f"{field_prefix}`{key}: {value}`" for key, value in fields.items()))
            self.cli("transition", "--to", "building_audit_gate", "--evidence", self.building_report)
            if register_gate:
                self.cli("gate", "--artifact", self.root, "--evidence", self.gate)
        self.building = {
            "audit_id": self.building_audit_id, "report_sha256": fingerprint(self.building_report), "assessment": "PASS",
            **{key: self.contract[key] for key in ("code_commit", "build_plan_sha256", "task_specs")},
            "contract_sha256": fingerprint(contract),
            "report_presented_at": "2024-01-01T00:00:00+00:00",
            "accepted_at": "2024-01-01T00:01:00+00:00", "acceptance_ref": "user-building-accept",
            "spec_approval_ref": "user-spec-approval",
            "audit_user_decision": "accepted", "accepted_audit_id": self.building_audit_id,
            "limitations": [], "accepted_limitations": [], **overrides,
        }
        evidence = self.file(receipt_path or f".tmp/building-binding{version}.json", self.building)
        return self.cli("runtime-init", "--artifact", contract, "--evidence", evidence, denied=denied)

    def authorize(self, steps, denied=None, **overrides):
        version = "" if self.building_audit_id == "B001" else self.building_audit_id + "-"
        evidence = self.file(".tmp/auth-" + version + "-".join(steps) + ".json", {
            "audit_id": self.building_audit_id, "contract_sha256": self.building["contract_sha256"],
            "authorized_at": "2024-01-01T00:02:00+00:00", "user_message_ref": "user-runtime-" + "-".join(steps),
            "steps": steps, **overrides,
        })
        return self.cli("runtime-authorize", "--evidence", evidence, denied=denied)

    def return_step_receipt(self, route):
        self.contract["steps"]["S1"]["environment"] = {"FIXTURE_SETTING": "test"}
        self.initialize()
        self.authorize(["S1"])
        attempt = self.run("S1")
        self.review(attempt, "CHANGES_REQUIRED", route)
        return self.file(".tmp/return-to-" + route + ".json", {
            "step_run_hash": attempt["step_run_hash"], "route": route, "reason": "Synthetic return",
            "user_message_ref": "return-to-" + route, "decided_at": datetime.now(timezone.utc).isoformat(),
        })

    def return_step(self, route):
        evidence = self.return_step_receipt(route)
        self.cli("runtime-return", "S1", "--evidence", evidence)
        return json.loads(self.state.read_text(encoding="utf-8"))

    def rebuild_cleanly(self):
        self.building_report = None
        self.building_audit_id = "B002"
        self.contract["run_id"] = "rebuild"
        plan = self.root / "specs/build_plan.md"
        task = self.root / "specs/tasks/T01.md"
        git = ["git", "-C", str(self.root)]
        base = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        job = self.root / "job.py"
        job.write_text(job.read_text(encoding="utf-8") + "# New building cycle\n", encoding="utf-8")
        subprocess.run([*git, "add", plan, task, job], check=True)
        subprocess.run([*git, "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
                        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "rebuild"], check=True)
        head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        self.contract.update(code_commit=head, build_plan_sha256=fingerprint(plan),
                             task_specs={"T01": fingerprint(task)})
        self.cli("register-task", "T01", "--action", "resume_or_redispatch_implementer", "--evidence", task)
        for status, report in [
            ("task_review_pending", f"Task T01\nStatus: DONE\nCommit: {head}\nTDD Evidence"),
            ("task_complete", f"Task T01\nReviewed HEAD: {head}\nVerdict: PASS"),
            ("final_review_pending", None),
            ("building_audit_pending", f"Overall Review\nHEAD: {head}\nVerdict: PASS"),
        ]:
            args = ["--evidence", self.file(f".tmp/sdd/build_plan/rebuild/{status}.md", report)] if report else []
            self.cli("transition", "--to", status, *args)
        self.human_report = self.file("audits/building/report/rebuild-T01.md", "# T01 · Synthetic rebuild")
        self.gate = self.file(".tmp/sdd/build_plan/rebuild/building-gate.json", {
            "ledger": str(self.file(".tmp/sdd/build_plan/rebuild/progress.md",
                                     f"Task T01: complete (commits {base}..{head}, review clean) · {fingerprint(task)}\n")),
            "tasks": {"T01": {
                "brief": str(self.file(".tmp/sdd/build_plan/rebuild/task-01-brief.md", task.read_text(encoding="utf-8"))),
                "human_report": str(self.human_report),
            }},
        })

    def run(self, step, denied=None, retry=None):
        args = ["--evidence", self.file(f".tmp/retry-{step}-{retry['step_run_hash']}.json", retry)] if retry else []
        return self.cli("runtime-run", step, "--actor", "executor", *args, denied=denied)

    def review(self, attempt, verdict="PASS", route=None, denied=None, reviewer="step-reviewer",
               report_fields=None):
        name = f".tmp/review-{attempt['step_id']}-{attempt['attempt']}-{reviewer}"
        fields = {"step_run_hash": attempt["step_run_hash"], "verdict": verdict, "return_stage": route or "none",
                  "ac_statuses": json.dumps({"T01-AC01": verdict}), **(report_fields or {})}
        evidence = self.file(name + ".json", {
            "step_run_hash": attempt["step_run_hash"], "reviewer": reviewer, "verdict": verdict,
            "acs": {"T01-AC01": verdict}, "route": route,
            "report": str(self.file("audits/runtime/task-review/" + Path(name).name + ".md",
                                    "# Runtime Task Review\n" +
                                    "\n".join(f"- `{key}: {value}`" for key, value in fields.items()))),
        })
        return self.cli("runtime-review", attempt["step_id"], "--evidence", evidence, denied=denied)

    def audit(self, scope, denied=None, report_fields=None, *, prepare=False, **overrides):
        if scope != "final_chain":
            self.cli("runtime-report", scope)
        binding = self.cli("runtime-scope", scope)
        hash_label = "chain_hash" if scope == "final_chain" else "run_hash"
        assessment = overrides.get("assessment", "PASS")
        count = len(list((self.root / "audits/runtime").glob("*.md"))) + 1
        fields = {"audit_scope": binding["audit_scope"], "runtime_audit_id": binding["audit_id"],
                  hash_label: binding["scope_hash"], "accepted_run_hash": "null", "accepted_chain_hash": "null",
                  "runtime_audit_status": assessment,
                  "return_stage": overrides.get("route") or "none",
                  "limitations": json.dumps(overrides.get("limitations", [])), **(report_fields or {})}
        report_text = AUDIT_TEMPLATE.read_text(encoding="utf-8")
        for template_field in ("audit_scope", "runtime_audit_id", "run_hash", "runtime_audit_status",
                               "return_stage", "limitations"):
            report_text = "\n".join(line for line in report_text.splitlines()
                                    if not line.startswith("- `" + template_field + ":"))
        evidence = self.file(f".tmp/audit-{scope}-{count}.json", {
            "scope_hash": binding["scope_hash"], "auditor": "auditor",
            "report": str(self.file(f"audits/runtime/{count:03d}_{scope}.md", report_text + "\n" +
                                    "\n".join(f"- `{key}: {value}`" for key, value in fields.items()))),
            "assessment": "PASS", "limitations": [], "route": None, **overrides,
        })
        return evidence if prepare else self.cli("runtime-audit", scope, "--evidence", evidence, denied=denied)

    def accept(self, scope, audit, denied=None, **overrides):
        evidence = self.file(f".tmp/accept-{scope}-{audit['audit_id']}.json", {
            "audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"],
            "accepted_at": datetime.now(timezone.utc).isoformat(), "user_message_ref": f"user-accept-{scope}",
            "accepted_limitations": audit["limitations"], **overrides,
        })
        return self.cli("runtime-accept", scope, "--evidence", evidence, denied=denied)


@pytest.fixture
def scenario(tmp_path):
    return Scenario(tmp_path)


def test_runtime_attachments_are_local_but_bound_scientific_input_can_be_external(tmp_path):
    unit = tmp_path / "unit"
    unit.mkdir()
    sibling = tmp_path / "other unit"
    sibling.mkdir()
    scenario = Scenario(unit)
    external_data = sibling / "registered-input.txt"
    external_data.write_bytes(scenario.source.read_bytes())
    scenario.contract["inputs"]["source"]["path"] = str(external_data)
    scenario.initialize(denied="outside", contract_path=sibling / "contract.json")
    state_before = scenario.state.read_bytes()
    scenario.initialize(denied="outside", receipt_path=sibling / "building-acceptance.json")
    assert scenario.state.read_bytes() == state_before
    scenario.initialize()
    state_before = scenario.state.read_bytes()
    foreign = sibling / "authorization.json"
    foreign.write_text(json.dumps({
        "audit_id": scenario.building_audit_id,
        "contract_sha256": scenario.building["contract_sha256"],
        "authorized_at": "2024-01-01T00:02:00+00:00",
        "user_message_ref": "user-runtime-S1", "steps": ["S1"],
    }), encoding="utf-8")
    scenario.cli("runtime-authorize", "--evidence", foreign, denied="outside")
    assert scenario.state.read_bytes() == state_before
    scenario.authorize(["S1"])
    attempt = scenario.run("S1")
    assert attempt["inputs"]["source"]["path"] == str(external_data.resolve())


@pytest.mark.parametrize("hash_free_finish", [False, True])
def test_runtime_lifecycle_requires_independent_review_and_distinct_user_gates(scenario, hash_free_finish):
    scenario.cli("runtime-run", "S1", "--actor", "executor", denied="Runtime has not been initialized")
    scenario.initialize()
    scenario.run("S1", denied="not authorized")
    scenario.authorize(["S1", "S2"])
    scenario.run("S2", denied="dependency S1")
    first = scenario.run("S1")
    assert first["exit_code"] == 0
    scenario.run("S2", denied="dependency S1")
    scenario.review(first, reviewer="executor", denied="independent")
    scenario.review(first)
    scenario.run("S1", denied="already passed")
    second = scenario.run("S2")
    scenario.review(second)
    scenario.authorize(["S3"])
    scenario.run("S3", denied="not accepted")
    node = scenario.audit("N01")
    scenario.cli("runtime-scope", "final_chain", denied="not accepted")
    scenario.run("S3", denied="Runtime Audit gate")
    scenario.accept("N01", node, denied="scope", scope_hash="wrong")
    scenario.accept("N01", node, denied="after", accepted_at="2024-01-01T00:00:00Z")
    scenario.accept("N01", node)
    third = scenario.run("S3")
    assert Path(third["outputs"]["results/data/s3.txt"]["path"]).read_text() == "sample!!!"
    scenario.review(third)
    scenario.accept("N02", scenario.audit("N02"))
    finish = scenario.root / "reports" / "runtime_finish.md"
    scenario.cli("runtime-finish", "--artifact", finish, denied="not accepted")
    final = scenario.audit("final_chain")
    assert final["scope_hash"] != node["scope_hash"]
    scenario.cli("runtime-finish", "--artifact", finish, denied="Runtime Audit gate")
    scenario.accept("final_chain", final)
    scope = scenario.cli("runtime-scope", "final_chain")
    audit_ids = [final["audit_id"], *[node["audit_id"] for node in scope["nodes"]]]
    results = [record["path"] for outputs in scope["outputs"].values() for record in outputs.values()]
    if hash_free_finish:
        sections = ["## 阶段性结果", "计数为三。", "## 结果局限", "仅为测试数据。"]
        links = [f"- [审定结果 {index}]({Path(path).as_posix()})" for index, path in enumerate(results, 1)]
        for omitted, message in [
            (audit_ids[0], "accepted runtime_audit_id"),
            (audit_ids[1], "each accepted milestone audit"),
            (links[0], "link each audited output"),
        ]:
            report_lines = [*sections[:2], *audit_ids, *links, *sections[2:]]
            report_lines.remove(omitted)
            scenario.file(finish, "\n\n".join(report_lines) + "\n")
            scenario.cli("runtime-finish", "--artifact", finish, denied=message)
        report = "\n\n".join([*sections[:2], *audit_ids, *links, *sections[2:]]) + "\n"
        assert all(node["run_hash"] not in report for node in scope["nodes"])
    else:
        report = "\n".join(["## 当前状态与追溯", "## 结果概览", "## 已审结果清单", "## 关键发现与限制",
                            "## 复现与交付核对", final["scope_hash"], *audit_ids,
                            *[node["run_hash"] for node in scope["nodes"]], *results])
    scenario.file("reports/runtime_finish.md", report)
    assert scenario.cli("runtime-finish", "--artifact", finish)["status"] == "runtime_finished"
    assert (final["scope_hash"] in finish.read_text(encoding="utf-8")) == (not hash_free_finish)


def test_runtime_rejects_legacy_transition_and_stale_or_unscoped_authority(scenario):
    scenario.cli("transition", "--to", "runtime_authorized", "--user-accepted", denied="runtime-init")
    scenario.initialize(denied="must follow", accepted_at="2023-01-01T00:00:00Z")
    scenario.initialize()
    scenario.authorize(["S1"], denied="after", authorized_at="2024-01-01T00:00:00Z")
    scenario.authorize(["S1"], denied="future", authorized_at="2099-01-01T00:00:00Z")
    scenario.authorize(["outside"], denied="unknown step")
    scenario.authorize(["S1"], authorized_at=scenario.building["accepted_at"],
                       user_message_ref=scenario.building["acceptance_ref"])
    scenario.run("S2", denied="not authorized")
    (scenario.root / "job.py").write_text("# altered tracked code", encoding="utf-8")
    scenario.run("S1", denied="tracked worktree changes")


def test_runtime_rejects_dependency_cycles(scenario):
    scenario.contract["steps"]["S1"]["needs"] = ["S2"]
    scenario.initialize(denied="dependency cycle")


def test_runtime_rejects_graph_not_present_in_approved_plan(scenario):
    scenario.contract["steps"]["S2"]["needs"] = []
    scenario.contract["steps"]["S2"]["inputs"] = ["source"]
    scenario.contract["steps"]["S2"]["command"][2] = "{input:source}"
    scenario.initialize(denied="approved Runtime graph")


def test_runtime_rejects_unbound_script_argv(scenario):
    scenario.file("scratch.py", "raise RuntimeError('unreviewed')\n")
    scenario.contract["steps"]["S1"]["command"][1] = "scratch.py"
    scenario.initialize(denied="unbound code argument")


@pytest.mark.parametrize("name", ["auth-S1.json", "contract.json", "building-binding.json"])
def test_runtime_revalidates_bound_receipts(scenario, name):
    scenario.initialize()
    scenario.authorize(["S1"])
    (scenario.root / ".tmp" / name).unlink()
    scenario.run("S1", denied="fingerprint changed")


def test_runtime_revalidates_upstream_step_review_receipt(scenario):
    scenario.initialize()
    scenario.authorize(["S1", "S2"])
    first = scenario.run("S1")
    review = scenario.review(first)
    Path(review["receipt"]["path"]).write_text("{}", encoding="utf-8")
    scenario.run("S2", denied="fingerprint changed")


def test_runtime_requires_durable_building_gate(scenario):
    scenario.initialize(register_gate=False, denied="durable Building gate evidence")


@pytest.mark.parametrize("first_binding", ["manifest", "legacy", "null"])
def test_building_gate_cannot_replace_a_formal_reports_runtime_contract(scenario, first_binding):
    scenario.initialize(register_gate=False, denied="durable Building gate evidence",
                        hash_free_building=first_binding != "legacy")
    gate_data = json.loads(scenario.gate.read_text(encoding="utf-8"))
    contract = scenario.root / ".tmp/contract.json"
    binding = {"report_sha256": fingerprint(scenario.building_report),
               "contract_sha256": None if first_binding == "null" else fingerprint(contract)}
    if first_binding != "legacy":
        scenario.file(scenario.gate, gate_data | {"audit_binding": {"report_sha256": binding["report_sha256"]}})
        scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate,
                     denied="requires contract_sha256")
        scenario.file(scenario.gate, gate_data | {"audit_binding": binding})
    scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate)
    state_before = scenario.state.read_bytes()
    scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate)
    assert scenario.state.read_bytes() == state_before

    alternate = scenario.file(".tmp/alternate-contract.json", scenario.contract | {"run_id": "alternate"})
    replacement = scenario.file(scenario.gate.with_name("replacement-gate.json"), gate_data | {
        "audit_binding": binding | {"contract_sha256": fingerprint(alternate)},
    })
    scenario.cli("gate", "--artifact", scenario.root, "--evidence", replacement,
                 denied="cannot change its Runtime contract binding")
    if first_binding == "manifest":
        scenario.file(replacement, gate_data)
        scenario.cli("gate", "--artifact", scenario.root, "--evidence", replacement,
                     denied="cannot change its Runtime contract binding")
    assert scenario.state.read_bytes() == state_before
    scenario.contract["run_id"] = "alternate"
    scenario.initialize(contract_path=alternate, receipt_path=".tmp/alternate-receipt.json",
                        denied="Markdown contract_sha256" if first_binding == "legacy" else
                        "manifest bindings differ")
    assert scenario.state.read_bytes() == state_before

    if first_binding != "null":
        scenario.contract["run_id"] = "synthetic"
        scenario.initialize()


@pytest.mark.parametrize("declares_null, nested", [
    (False, False), (True, False), (False, True),
], ids=["digest", "null", "nested-digest"])
def test_first_building_gate_must_match_legacy_report_contract(scenario, declares_null, nested):
    legacy_fields = {"contract_sha256": "null"} if declares_null else None
    scenario.initialize(register_gate=False, denied="durable Building gate evidence",
                        legacy_building_fields=legacy_fields, nested_legacy_building_fields=nested)
    gate_data = json.loads(scenario.gate.read_text(encoding="utf-8"))
    contract = scenario.root / ".tmp/contract.json"
    alternate = scenario.file(".tmp/alternate-contract.json", scenario.contract | {"run_id": "alternate"})
    state_before = scenario.state.read_bytes()
    binding = {"report_sha256": fingerprint(scenario.building_report)}
    conflicting = [fingerprint(alternate)] if declares_null else [fingerprint(alternate), None]
    for contract_hash in conflicting:
        scenario.file(scenario.gate, gate_data | {"audit_binding": binding | {"contract_sha256": contract_hash}})
        scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate,
                     denied="Markdown contract_sha256 differs")
        assert scenario.state.read_bytes() == state_before

    contract_hash = None if declares_null else fingerprint(contract)
    scenario.file(scenario.gate, gate_data | {"audit_binding": binding | {"contract_sha256": contract_hash}})
    scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate)
    scenario.initialize(denied="manifest bindings differ" if declares_null else None)


@pytest.mark.parametrize("field, stale", [
    ("code_commit", "a" * 40), ("build_plan_sha256", "b" * 64), ("task_specs", "null"),
])
def test_first_building_gate_rejects_stale_legacy_identifiers(scenario, field, stale):
    scenario.initialize(register_gate=False, denied="durable Building gate evidence",
                        legacy_building_fields={field: stale})
    gate_data = json.loads(scenario.gate.read_text(encoding="utf-8"))
    scenario.file(scenario.gate, gate_data | {"audit_binding": {
        "report_sha256": fingerprint(scenario.building_report),
        "contract_sha256": fingerprint(scenario.root / ".tmp/contract.json"),
    }})
    scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate,
                 denied=f"Markdown {field} differs")


def test_runtime_revalidates_legacy_report_for_existing_manifest_gate(scenario):
    scenario.initialize(register_gate=False, denied="durable Building gate evidence")
    scenario.cli("gate", "--artifact", scenario.root, "--evidence", scenario.gate)

    scenario.contract["run_id"] = "alternate"
    alternate = scenario.file(".tmp/alternate-contract.json", scenario.contract)
    binding = {"report_sha256": fingerprint(scenario.building_report), "contract_sha256": fingerprint(alternate)}
    # Reproduce the durable records written by a first registration on an older Harness.
    gate_data = json.loads(scenario.gate.read_text(encoding="utf-8"))
    scenario.file(scenario.gate, gate_data | {"audit_binding": binding})
    state = json.loads(scenario.state.read_text(encoding="utf-8"))
    state["building_gate"]["audit_binding"] = binding
    state["building_gate"]["files"][0].update(
        sha256=fingerprint(scenario.gate), bytes=scenario.gate.stat().st_size)
    scenario.file(scenario.state, state)
    manifest = scenario.state.parent / "building/manifest.json"
    scenario.file(manifest, json.loads(manifest.read_text(encoding="utf-8")) | {"audit_binding": binding})
    state_before = scenario.state.read_bytes()

    scenario.initialize(contract_path=alternate, denied="Markdown contract_sha256 differs")

    assert scenario.state.read_bytes() == state_before


@pytest.mark.parametrize("section_format", [
    None, "~~~markdown\n{}\n~~~", "> {}", "[{}](example.md)", "{} — example", "<!--\n{}\n-->",
], ids=["missing", "fenced", "quoted", "linked", "inline-suffix", "html-comment"])
def test_building_audit_gate_requires_full_formal_report(scenario, section_format):
    report_text = "# Building Audit\nassessment: PASS\n"
    if section_format is not None:
        template = (TEMPLATES / "building-audit-report.md").read_text(encoding="utf-8")
        sections = [line for line in template.splitlines() if line.startswith("## ") and line[3:4].isdigit()]
        if section_format.startswith("~~~"):
            report_text += section_format.format("\n".join(sections)) + "\n"
        else:
            report_text += "\n".join(section_format.format(section) for section in sections) + "\n"
    report = scenario.file("audits/building/incomplete.md", report_text)
    events = scenario.state.with_name("events.jsonl")
    before = scenario.state.read_bytes(), events.read_bytes()

    scenario.cli("transition", "--to", "building_audit_gate", "--evidence", report, denied="layout")

    assert (scenario.state.read_bytes(), events.read_bytes()) == before


def test_runtime_accepts_durable_gate_after_building_repair(tmp_path):
    scenario = Scenario(tmp_path, building_repair=True)
    scenario.initialize()
    scenario.authorize(["S1"])
    assert scenario.run("S1")["exit_code"] == 0


def test_negative_building_audit_can_register_but_never_initialize_runtime(tmp_path):
    scenario = Scenario(tmp_path, overall_verdict="CHANGES_REQUIRED")
    scenario.initialize(building_assessment="BLOCKED", denied="passing Overall Review")
    state = json.loads(scenario.state.read_text(encoding="utf-8"))
    assert state["status"] == "building_audit_gate"
    assert state["building_gate"]
    assert "runtime" not in state


def test_runtime_binds_external_code_and_ignores_inherited_environment(tmp_path, monkeypatch):
    root = tmp_path / "worktree"
    root.mkdir()
    scenario = Scenario(root)
    explicit = tmp_path / "external.py"
    explicit.write_bytes((root / "job.py").read_bytes())
    step = scenario.contract["steps"]["S1"]
    step["command"][1] = "{code:launcher}"
    step["code_inputs"] = {"launcher": {"path": str(explicit), "sha256": fingerprint(explicit)}}
    step["environment"] = {"CHECK_NO_USER_SITE": "1"}
    scenario.initialize()
    scenario.authorize(["S1"])
    original = explicit.read_text(encoding="utf-8")
    explicit.write_text("# mutated\n", encoding="utf-8")
    scenario.run("S1", denied="fingerprint changed")
    explicit.write_text(original, encoding="utf-8")
    monkeypatch.setenv("SDD_TEST_UNAPPROVED_ENV", "must not be inherited")
    assert scenario.run("S1")["exit_code"] == 0


def test_runtime_rejects_ignored_worktree_dependency(scenario):
    scenario.initialize()
    scenario.authorize(["S1"])
    (scenario.root / ".git/info/exclude").write_text("dependency.py\n", encoding="utf-8")
    scenario.file("dependency.py", "UNAPPROVED = True\n")
    scenario.run("S1", denied="unbound code or dependency")


def local_python_environment(scenario):
    directory = scenario.root / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--copies", str(directory)], check=True)
    executable = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    libraries = (directory / "Lib/site-packages" if os.name == "nt"
                 else next(directory.glob("lib/python*/site-packages")))
    package = scenario.file(libraries / "audit_fixture_dependency.py", "IS_FIXTURE = True\n")
    scenario.file(".git/info/exclude", ".venv/\n")
    step = scenario.contract["steps"]["S1"]
    step["command"][0] = str(executable)
    step["executable_sha256"] = fingerprint(executable)
    return directory, package


def test_explicit_python_environment_runs_and_other_ignored_code_stays_blocked(scenario):
    directory, _ = local_python_environment(scenario)
    response = scenario.cli("python-environment-fingerprint", "--artifact", directory)
    scenario.contract["python_environment"] = json.loads(response.stdout)
    launcher = scenario.file(".tmp/verify-venv.py",
                             "import pathlib, runpy, sys\n"
                             "import audit_fixture_dependency\n"
                             f"assert pathlib.Path(sys.prefix) == pathlib.Path({str(directory)!r})\n"
                             "assert audit_fixture_dependency.IS_FIXTURE is True\n"
                             "runpy.run_path('job.py', run_name='__main__')\n")
    step = scenario.contract["steps"]["S1"]
    step["command"][1] = "{code:launcher}"
    step["code_inputs"] = {"launcher": {"path": str(launcher), "sha256": fingerprint(launcher)}}
    scenario.initialize()
    scenario.authorize(["S1"])
    scenario.file(".git/info/exclude", ".venv/\nother.py\n")
    other = scenario.file("other.py", "IS_UNBOUND = True\n")
    scenario.run("S1", denied="unbound code or dependency")
    other.unlink()
    attempt = scenario.run("S1")
    assert attempt["exit_code"] == 0 and not attempt["evidence_errors"]
    assert attempt["python_environment"] == scenario.contract["python_environment"]


def test_python_environment_digest_is_checked_at_runtime_init(scenario):
    directory, _ = local_python_environment(scenario)
    response = scenario.cli("python-environment-fingerprint", "--artifact", directory)
    binding = json.loads(response.stdout)
    scenario.contract["python_environment"] = {**binding, "sha256": "0" * 64}
    scenario.initialize(denied="Python environment fingerprint changed")
    assert "runtime" not in json.loads(scenario.state.read_text(encoding="utf-8"))


def test_undeclared_local_python_environment_is_not_exempt(scenario):
    local_python_environment(scenario)
    scenario.initialize()
    scenario.authorize(["S1"])
    scenario.run("S1", denied="unbound code or dependency")


def test_changed_python_environment_requires_new_binding(scenario):
    directory, package = local_python_environment(scenario)
    response = scenario.cli("python-environment-fingerprint", "--artifact", directory)
    scenario.contract["python_environment"] = json.loads(response.stdout)
    scenario.initialize()
    scenario.authorize(["S1"])
    original = package.read_bytes()
    package.write_bytes(original.replace(b"True", b"None"))
    before = scenario.state.read_bytes()
    scenario.run("S1", denied="Python environment fingerprint changed")
    assert scenario.state.read_bytes() == before
    package.write_bytes(original)
    attempt = scenario.run("S1")
    assert attempt["exit_code"] == 0
    package.write_bytes(original.replace(b"True", b"None"))
    scenario.review(attempt, denied="Python environment fingerprint changed")
    package.write_bytes(original)
    scenario.review(attempt)


def test_python_environment_detects_mutation_by_child_process(scenario):
    directory, package = local_python_environment(scenario)
    response = scenario.cli("python-environment-fingerprint", "--artifact", directory)
    scenario.contract["python_environment"] = json.loads(response.stdout)
    launcher = scenario.file(".tmp/mutate-venv.py",
                             "import pathlib, runpy\n"
                             "runpy.run_path('job.py', run_name='__main__')\n"
                             f"pathlib.Path({str(package)!r}).write_text('IS_FIXTURE = False', encoding='utf-8')\n")
    step = scenario.contract["steps"]["S1"]
    step["command"][1] = "{code:launcher}"
    step["code_inputs"] = {"launcher": {"path": str(launcher), "sha256": fingerprint(launcher)}}
    scenario.initialize()
    scenario.authorize(["S1"])
    original = package.read_bytes()
    attempt = scenario.run("S1")
    assert attempt["exit_code"] == 0
    assert any("Python environment fingerprint changed" in error for error in attempt["evidence_errors"])
    package.write_bytes(original)
    scenario.review(attempt, denied="requires successful execution and intact outputs")


def test_python_environment_rejects_system_site_packages(scenario):
    directory, _ = local_python_environment(scenario)
    config = directory / "pyvenv.cfg"
    original = config.read_text(encoding="utf-8")
    config.write_text(original.replace("include-system-site-packages = false",
                                       "include-system-site-packages = true"), encoding="utf-8")
    scenario.cli("python-environment-fingerprint", "--artifact", directory,
                 denied="must disable system site-packages")


@pytest.mark.parametrize("key", ["PYTHONPATH", "pythonhome", "LD_PRELOAD", "R_PROFILE_USER", "HOME", "APPDATA"])
def test_runtime_rejects_environment_code_injection(scenario, key):
    external = scenario.file(".tmp/external/sitecustomize.py", "raise RuntimeError('unbound startup')\n")
    scenario.contract["steps"]["S1"]["environment"] = {key: str(external.parent)}
    scenario.initialize(denied="loader environment variable")


def test_runtime_path_requires_explicit_executable_binding(scenario):
    executable = Path(sys.executable).resolve()
    step = scenario.contract["steps"]["S1"]
    step["environment"] = {"PATH": str(executable.parent), "FIXTURE_SETTING": "test"}
    scenario.initialize(denied="PATH directory requires a bound executable")


def test_runtime_accepts_bound_path(scenario):
    executable = Path(sys.executable).resolve()
    step = scenario.contract["steps"]["S1"]
    step["environment"] = {"PATH": str(executable.parent), "FIXTURE_SETTING": "test"}
    step["code_inputs"] = {"secondary": {"path": str(executable), "sha256": fingerprint(executable)}}
    scenario.initialize()
    scenario.authorize(["S1"])
    assert scenario.run("S1")["exit_code"] == 0


def test_return_to_building_starts_clean_cycle_after_repaired_task(tmp_path):
    scenario = Scenario(tmp_path, building_repair=True)
    returned = scenario.return_step("Building")
    assert returned["status"] == "building_incomplete"
    assert not returned["tasks"] and not returned["evidence"] and "building_gate" not in returned
    prior = returned["building_history"][0]
    assert len(prior["tasks"]["T01"]["building_chain"]["fix_rounds"]) == 1
    assert prior["building_gate"]["code_commit"] == scenario.contract["code_commit"]
    scenario.rebuild_cleanly()
    assert scenario.initialize(**new_building_acceptance())["run_id"] == "rebuild"
    active = json.loads(scenario.state.read_text(encoding="utf-8"))
    assert not active["tasks"]["T01"]["building_chain"].get("fix_rounds")
    assert active["building_history"][0] == prior
    assert active["runtime_history"] == returned["runtime_history"]
    scenario.authorize(["S1"], authorized_at=datetime.now(timezone.utc).isoformat(), user_message_ref="authorize-rebuild")
    assert scenario.run("S1")["exit_code"] == 0


@pytest.mark.parametrize("batch_id", [None, "B01"], ids=["legacy", "first-batch"])
def test_return_to_proposal_rebind_requires_new_approval_and_preserves_history(scenario, batch_id):
    returned = scenario.return_step("Proposal")
    plan = scenario.root / "specs/build_plan.md"
    task = scenario.root / "specs/tasks/T01.md"
    scenario.cli("transition", "--to", "building_incomplete", denied="proposal-rebind")
    plan_text = plan.read_text(encoding="utf-8").replace("## 项目目录结构", """### 拟得到的输出
| 输出 ID | 输出名称 | 逻辑路径 | 内容与用途 | 生成阶段 | 验收依据 |
|---|---|---|---|---|---|
| O01 | Updated output | results/data/s1.txt | Synthetic | Runtime | T01-AC01 |
## 项目目录结构
- path_schema: 1
| 任务 ID | 主入口路径 | 变更（新增／既有／迁移） |
|---|---|---|
| T01 | scripts/build/job.py | 迁移 |""").replace("tasks/T01.md", "tasks/task-01/task-01.md")
    if batch_id:
        plan_text = plan_text.replace(
            "| 节点 ID | 节点目的 | 包含的运行步骤 | 前置节点 | 阶段性成果与验收条件 | 用户授权范围 |",
            "| 节点 ID | 节点目的 | 建设批次 | 前置建设要求 | 包含的运行步骤 | "
            "Runtime 前置节点 | 阶段性成果与验收条件 |",
        ).replace(
            "|---|---|---|---|---|---|\n| N01 | fixture 1 | S1、S2 | 无 | output fixture | S1、S2 |\n"
            "| N02 | fixture 2 | S3 | N01 | output fixture | S3 |",
            "|---|---|---|---|---|---|---|\n"
            f"| N01 | fixture 1 | {batch_id} | 无 | S1、S2 | 无 | output fixture |\n"
            f"| N02 | fixture 2 | {batch_id} | 无 | S3 | N01 | output fixture |",
        )
    plan.write_text(plan_text, encoding="utf-8")
    revised_task = scenario.file("specs/tasks/task-01/task-01.md", task.read_text(encoding="utf-8").replace(
        "## 输入、脚本与输出\n", "## 输入、脚本与输出\n- 主入口路径：`scripts/build/job.py`\n"))
    task.unlink()
    assert json.loads(scenario.cli("status").stdout)["status"] == "proposal"
    for record in returned["building_history"][0]["spec_snapshots"].values():
        assert fingerprint(Path(record["path"])) == record["sha256"]
    approval = {
        "build_plan_sha256": fingerprint(plan), "task_specs": {"T01": fingerprint(revised_task)},
        "approved_at": datetime.now(timezone.utc).isoformat(), "user_message_ref": "user-spec-approval",
    }
    if batch_id:
        approval["batch_id"] = batch_id
    evidence = scenario.file(".tmp/revised-spec-approval.json", approval)
    scenario.cli("proposal-rebind", "--build-plan", plan, "--evidence", evidence, denied="fresh Spec approval")
    if batch_id:
        legacy_auth = returned["runtime_history"][0]["authorizations"][0]["approval"]
        approval["user_message_ref"] = legacy_auth["user_message_ref"]
        scenario.file(".tmp/revised-spec-approval.json", approval)
        scenario.cli("proposal-rebind", "--build-plan", plan, "--evidence", evidence, denied="fresh Spec approval")
    approval["user_message_ref"] = "user-approves-revised-scope"
    scenario.file(".tmp/revised-spec-approval.json", approval)
    scenario.cli("proposal-rebind", "--build-plan", plan, "--evidence", evidence)
    scenario.cli("register-task", "T01", "--action", "resume_or_redispatch_implementer", "--evidence",
                 scenario.root / ".tmp/sdd/build_plan/task-01-brief.md", denied="fresh Spec approval")
    scenario.cli("register-task", "T01", "--action", "resume_or_redispatch_implementer", "--evidence", revised_task)
    resumed = json.loads(scenario.state.read_text(encoding="utf-8"))
    assert resumed["runtime_history"] == returned["runtime_history"]
    assert resumed["spec_approval"] == approval
    scenario.run("S1", denied="Runtime has not been initialized")


@pytest.mark.parametrize("conflict", ["archive junction", "nested manifest repo", "parent gitlink"])
def test_return_to_proposal_rejects_workspace_conflicts(tmp_path, conflict):
    unit = tmp_path / "unit"
    unit.mkdir()
    scenario = Scenario(unit)
    receipt = scenario.return_step_receipt("Proposal")
    archive = scenario.state.parent / "history" / scenario.contract["run_id"]
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    if conflict == "archive junction":
        archive.parent.mkdir()
        if os.name == "nt":
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(archive), str(sibling)],
                           capture_output=True, check=True)
        else:
            archive.symlink_to(sibling, target_is_directory=True)
        denial = "Proposal archive"
    elif conflict == "nested manifest repo":
        subprocess.run(["git", "init", "--quiet", str(scenario.state.parent / "runtime")], check=True)
        denial = "nested Git repository"
    else:
        subprocess.run(["git", "-C", str(tmp_path), "init", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "--", "unit"], capture_output=True, check=True)
        denial = "Parent Git tracks"
    sidecars = [scenario.state, scenario.state.parent / "events.jsonl",
                scenario.state.parent / "runtime/manifest.json"]
    before = [path.read_bytes() for path in sidecars]

    scenario.cli("runtime-return", "S1", "--evidence", receipt, denied=denial)

    assert not list(sibling.iterdir())
    assert not (archive / "build-plan.md").exists()
    assert [path.read_bytes() for path in sidecars] == before


def test_return_to_proposal_does_not_partially_archive_on_snapshot_collision(scenario):
    receipt = scenario.return_step_receipt("Proposal")
    archive = scenario.state.parent / "history" / scenario.contract["run_id"]
    collision = scenario.file(archive / "T01.md", "previous evidence")
    state_bytes = scenario.state.read_bytes()

    scenario.cli("runtime-return", "S1", "--evidence", receipt, denied="Proposal archive collision")

    assert not (archive / "build-plan.md").exists()
    assert collision.read_text(encoding="utf-8") == "previous evidence"
    assert scenario.state.read_bytes() == state_bytes


def test_runtime_rejects_inconsistent_review_and_audit_markdown(scenario):
    scenario.initialize()
    scenario.authorize(["S1", "S2"])
    first = scenario.run("S1")
    scenario.review(first, report_fields={"verdict": "BLOCKED"}, denied="Markdown verdict differs")
    scenario.review(first)
    scenario.review(scenario.run("S2"))
    scenario.audit("N01", report_fields={"return_stage": "Building"}, denied="Markdown return_stage differs")
    scenario.audit("N01", report_fields={"limitations": '["altered"]'}, denied="Markdown limitations differs")


def test_runtime_pauses_independent_steps_at_formal_gate(tmp_path):
    scenario = Scenario(tmp_path, independent=True)
    scenario.initialize()
    scenario.authorize(["S1", "S2", "S3"])
    scenario.review(scenario.run("S1"))
    scenario.review(scenario.run("S2"))
    node = scenario.audit("N01")
    scenario.run("S3", denied="Runtime Audit gate")
    scenario.authorize(["S2"], denied="Runtime Audit gate")
    scenario.accept("N01", node)
    assert scenario.run("S3")["exit_code"] == 0


def test_runtime_pauses_second_ready_audit_at_formal_gate(tmp_path):
    scenario = Scenario(tmp_path, independent=True)
    scenario.initialize()
    scenario.authorize(["S1", "S2", "S3"])
    for step in ("S1", "S2", "S3"):
        scenario.review(scenario.run(step))
    second = scenario.audit("N02", prepare=True)
    first = scenario.audit("N01")
    scenario.cli("runtime-audit", "N02", "--evidence", second, denied="Runtime Audit gate")
    scenario.cli("runtime-report", "N02", denied="Runtime Audit gate")
    scenario.accept("N02", first, denied="Runtime Audit gate")
    assert scenario.cli("runtime-status")["status"] == "milestone_audit_gate"
    scenario.accept("N01", first)
    assert scenario.cli("runtime-audit", "N02", "--evidence", second)["scope_hash"]


def test_runtime_revalidates_accepted_node_and_scope_on_return(scenario):
    scenario.initialize()
    scenario.authorize(["S1", "S2", "S3"])
    scenario.review(scenario.run("S1"))
    second = scenario.run("S2")
    scenario.review(second)
    node = scenario.audit("N01", assessment="CHANGES_REQUIRED", route="Runtime")
    decision = {
        "audit_id": node["audit_id"], "scope_hash": node["scope_hash"], "route": "Runtime",
        "reason": "Transport", "user_message_ref": "user-request", "steps": ["S2"],
        "changes": ["transport"], "rerun_authorized": True, "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    output = Path(second["outputs"]["results/data/s2.txt"]["path"])
    original = output.read_bytes()
    output.write_text("changed output", encoding="utf-8")
    evidence = scenario.file(".tmp/return.json", decision)
    scenario.cli("runtime-return", "N01", "--evidence", evidence, denied="fingerprint changed")
    output.write_bytes(original)
    scenario.cli("runtime-return", "N01", "--evidence", evidence)
    scenario.review(scenario.run("S2"))
    current = scenario.audit("N01")
    scenario.accept("N01", current)
    (scenario.root / ".tmp" / f"accept-N01-{current['audit_id']}.json").unlink()
    scenario.run("S3", denied="fingerprint changed")


@pytest.mark.parametrize("accepted", [False, True])
def test_runtime_recovers_exact_approved_artifact_loss(scenario, accepted):
    scenario.initialize()
    scenario.authorize(["S1", "S2", "S3"])
    upstream = scenario.run("S1")
    scenario.review(upstream)
    lost_attempt = scenario.run("S2")
    scenario.review(lost_attempt)
    audit = scenario.audit("N01")
    if accepted:
        scenario.accept("N01", audit)
        scenario.review(scenario.run("S3"))
        dependent_audit = scenario.audit("N02")
    output_name = "results/data/s2.txt"
    lost = lost_attempt["outputs"][output_name]
    decision = {
        "audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"], "route": "Runtime",
        "reason": "Approved output was removed during transport", "user_message_ref": "user-recovers-s2",
        "steps": ["S2"], "changes": ["transport"], "rerun_authorized": True,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    requested_loss = {"step_id": "S2", "step_run_hash": lost_attempt["step_run_hash"], "output": output_name}
    evidence_path = ".tmp/artifact-loss-return.json"

    def submit(denied=None, **fields):
        evidence = scenario.file(evidence_path, {**decision, **fields})
        return scenario.cli("runtime-return", "N01", "--evidence", evidence, denied=denied)

    submit(denied="artifact loss requires actual fingerprint change", artifact_loss=[requested_loss])
    output = Path(lost["path"])
    if accepted:
        output.write_text("damaged output", encoding="utf-8")
        observed = {"path": str(output), "sha256": fingerprint(output), "bytes": output.stat().st_size}
        scenario.accept("N02", dependent_audit, denied="fingerprint changed")
        submit(denied="return requires a current unaccepted Runtime Audit")
    else:
        output.unlink()
        observed = None
        scenario.accept("N01", audit, denied="fingerprint changed")
        submit(denied="fingerprint changed")
    submit(denied="explicit scoped rerun", artifact_loss=[requested_loss], rerun_authorized=False)
    submit(denied="return decision audit scope mismatch", artifact_loss=[requested_loss], audit_id="wrong-audit")
    submit(denied="artifact loss does not bind an existing attempt", artifact_loss=[{**requested_loss, "step_run_hash": "a" * 64}])
    upstream_file = Path(upstream["outputs"]["results/data/s1.txt"]["path"])
    original_upstream = upstream_file.read_bytes()
    upstream_file.write_text("unrelated change", encoding="utf-8")
    submit(denied="fingerprint changed", artifact_loss=[requested_loss])
    upstream_file.write_bytes(original_upstream)
    audit_report = Path(audit["report"]["path"])
    original_report = audit_report.read_bytes()
    audit_report.write_text("changed report", encoding="utf-8")
    submit(denied="fingerprint changed", artifact_loss=[requested_loss])
    stored = scenario.cli("runtime-status")
    assert stored["status"] == "milestone_audit_gate"
    bound_audit = stored["audits"]["N01"]
    audit_report.write_bytes(original_report)

    returned = submit(artifact_loss=[requested_loss])
    assert returned["artifact_losses"] == [{**requested_loss, "expected": lost, "observed": observed}]
    assert returned["affected_steps"] == ["S2", "S3"]
    scenario.cli("runtime-report", "N01", denied="no passing Runtime Task Review")
    recovered = scenario.run("S2")
    assert recovered["attempt"] == 2
    assert recovered["upstream_steps"]["S1"]["step_run_hash"] == upstream["step_run_hash"]
    assert recovered["step_run_hash"] != lost_attempt["step_run_hash"]
    scenario.review(recovered)
    new_audit = scenario.audit("N01")
    assert new_audit["audit_id"] != audit["audit_id"]
    assert new_audit["scope_hash"] != audit["scope_hash"]
    stale_acceptance = scenario.file(".tmp/stale-recovery-acceptance.json", {"audit_id": audit["audit_id"],
                                                                          "scope_hash": audit["scope_hash"]})
    scenario.cli("runtime-accept", "N01", "--evidence", stale_acceptance, denied="acceptance scope mismatch")
    scenario.accept("N01", new_audit, user_message_ref="user-accept-recovered-N01")
    archived = [bound_audit, dependent_audit] if accepted else [bound_audit]
    assert scenario.cli("runtime-status")["archived_audits"] == archived
    scenario.run("S3", denied="fresh scoped authorization")
    scenario.authorize(["S3"], authorized_at=datetime.now(timezone.utc).isoformat(), user_message_ref="user-restarts-S3")
    assert scenario.run("S3")["upstream_audits"]["N01"]["audit_id"] == new_audit["audit_id"]


@pytest.mark.parametrize("independent", [False, True])
def test_runtime_recovers_bound_losses_across_invalidated_audits(tmp_path, independent):
    scenario = Scenario(tmp_path, independent=independent)
    scenario.initialize()
    scenario.authorize(["S1", "S2", "S3"])
    scenario.review(scenario.run("S1"))
    upstream = scenario.run("S2")
    scenario.review(upstream)
    anchor = scenario.audit("N01")
    scenario.accept("N01", anchor)
    downstream = scenario.run("S3")
    scenario.review(downstream)
    dependent = scenario.audit("N02")
    attempts = {"S2": upstream, "S3": downstream}
    losses = []
    for step, attempt in attempts.items():
        output, record = next(iter(attempt["outputs"].items()))
        Path(record["path"]).unlink()
        losses.append({"step_id": step, "step_run_hash": attempt["step_run_hash"], "output": output})
    decision = {
        "audit_id": anchor["audit_id"], "scope_hash": anchor["scope_hash"], "route": "Runtime",
        "reason": "Multiple approved outputs were lost during transport", "user_message_ref": "user-recovers-closure",
        "steps": ["S2", "S3"], "changes": ["transport"], "rerun_authorized": True, "artifact_loss": losses,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }

    def submit(label, denied=None, **overrides):
        evidence = scenario.file(f".tmp/closure-{label}.json", {**decision, **overrides})
        return scenario.cli("runtime-return", "N01", "--evidence", evidence, denied=denied)

    stored = scenario.state.read_bytes()
    if independent:
        submit("unrelated", denied="invalidation closure")
        assert scenario.state.read_bytes() == stored
        return
    submit("partial", denied="fingerprint changed", steps=["S2"], artifact_loss=losses[:1])
    submit("stale", denied="artifact loss does not bind an existing attempt",
           artifact_loss=[losses[0], {**losses[1], "step_run_hash": "a" * 64}])
    report = Path(dependent["report"]["path"])
    original = report.read_bytes()
    report.write_bytes(original + b"\nChanged.")
    submit("tampered-child", denied="fingerprint changed")
    report.write_bytes(original)
    assert scenario.state.read_bytes() == stored

    result = submit("approved")
    assert result["invalidated_scopes"] == ["N01", "N02", "final_chain"]
    assert result["affected_steps"] == ["S2", "S3"]
    assert result["artifact_losses"] == [
        {**loss, "expected": attempts[loss["step_id"]]["outputs"][loss["output"]], "observed": None}
        for loss in losses
    ]
    scenario.review(scenario.run("S2"))
    new_anchor = scenario.audit("N01")
    assert new_anchor["audit_id"] != anchor["audit_id"]
    submit("replay", denied="return decision audit scope mismatch", user_message_ref="user-replays-stale-closure")
    scenario.accept("N01", new_anchor, user_message_ref="user-accepts-recovered-anchor")
    scenario.run("S3", denied="fresh scoped authorization")
    scenario.authorize(["S3"], authorized_at=datetime.now(timezone.utc).isoformat(),
                       user_message_ref="user-authorizes-downstream-closure-recovery")
    recovered = scenario.run("S3")
    assert recovered["attempt"] == 2
    assert recovered["upstream_audits"]["N01"]["audit_id"] == new_anchor["audit_id"]
    scenario.review(recovered)
    assert scenario.audit("N02")["audit_id"] != dependent["audit_id"]


@pytest.mark.parametrize("route", ["Building", "Proposal", "Decision"])
def test_runtime_routes_bound_artifact_loss_without_reopening(scenario, route):
    scenario.initialize()
    scenario.authorize(["S1", "S2"])
    scenario.review(scenario.run("S1"))
    attempt = scenario.run("S2")
    scenario.review(attempt)
    audit = scenario.audit("N01", assessment="CHANGES_REQUIRED", route=route)
    output = "results/data/s2.txt"
    expected = attempt["outputs"][output]
    output_path = Path(expected["path"])
    output_path.unlink()
    loss = {"step_id": "S2", "step_run_hash": attempt["step_run_hash"], "output": output}
    decision = {
        "audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"], "route": route,
        "reason": "Return after transport loss", "user_message_ref": "user-routes-loss",
        "steps": ["S2"], "decided_at": datetime.now(timezone.utc).isoformat(),
    }

    def submit(filename, evidence, denied=None):
        return scenario.cli("runtime-return", "N01", "--evidence", scenario.file(filename, evidence), denied=denied)

    submit(".tmp/stale-return.json", decision, denied="fingerprint changed")
    returned = submit(".tmp/loss-return.json", {**decision, "artifact_loss": [loss]})
    assert returned == {"route": route, "artifact_losses": [{**loss, "expected": expected, "observed": None}]}
    if route == "Decision":
        resolution = {**decision, "route": "Building", "user_message_ref": "user-resolves-loss",
                      "decided_at": datetime.now(timezone.utc).isoformat()}
        submit(".tmp/stale-resolution.json", resolution, denied="fingerprint changed")
        output_path.write_text("new damaged contents", encoding="utf-8")
        resolved = submit(".tmp/loss-resolution.json", {**resolution, "artifact_loss": [loss]})
        assert resolved["artifact_losses"][0]["observed"]["sha256"] == fingerprint(output_path)
    state = json.loads(scenario.state.read_text(encoding="utf-8"))
    runtime = state["runtime_history"][-1]
    assert runtime["reopen"] == {}
    assert runtime["audits"]["N01"]["audit_id"] == audit["audit_id"]
    assert Path(audit["report"]["path"]).is_file()


def test_runtime_decision_hold_resolves_bound_step(scenario):
    held = scenario.return_step("Decision")
    assert held["status"] == "user_decision_pending"
    assert held["next_allowed_actions"] == ["wait_for_user_decision"]
    scenario.run("S2", denied="return-stage hold")
    decision = held["runtime"]["return_decisions"][-1]["decision"]
    evidence_path = ".tmp/resolve-decision.json"
    evidence = scenario.file(evidence_path, {**decision, "route": "Building"})
    scenario.cli("runtime-return", "S1", "--evidence", evidence, denied="user message already recorded")
    evidence = scenario.file(evidence_path, {**decision, "route": "Building", "user_message_ref": "user-resolves-hold",
                                            "decided_at": datetime.now(timezone.utc).isoformat()})
    scenario.cli("runtime-return", "S2", "--evidence", evidence, denied="held Runtime scope")
    scenario.cli("runtime-return", "S1", "--evidence", evidence)
    resolved = json.loads(scenario.state.read_text(encoding="utf-8"))
    assert resolved["status"] == "building_incomplete"
    assert [item["decision"]["route"] for item in resolved["runtime_history"][-1]["return_decisions"]] == ["Decision", "Building"]


def test_runtime_rejects_changed_inputs_or_output(scenario):
    scenario.initialize()
    scenario.authorize(["S1", "S2"])
    scenario.source.write_text("changed", encoding="utf-8")
    scenario.run("S1", denied="fingerprint changed")
    scenario.source.write_text("sample", encoding="utf-8")
    first = scenario.run("S1")
    scenario.review(first)
    Path(first["outputs"]["results/data/s1.txt"]["path"]).write_text("changed", encoding="utf-8")
    scenario.run("S2", denied="fingerprint changed")


def test_runtime_preserves_each_attempt_and_caps_five_repair_rounds(scenario):
    scenario.config.write_text("reject", encoding="utf-8")
    for step in scenario.contract["steps"].values():
        step["config"]["sha256"] = fingerprint(scenario.config)
    scenario.initialize()
    scenario.authorize(["S1"])
    attempts = []
    retry = None
    for number in range(1, 7):
        result = scenario.run("S1", retry=retry)
        attempts.append(result)
        assert result["attempt"] == number and result["exit_code"] == 4
        assert Path(result["report"]["path"]).is_file()
        scenario.review(result, denied="successful")
        scenario.review(result, verdict="CHANGES_REQUIRED", route="Runtime")
        retry = {"step_run_hash": result["step_run_hash"], "reason": "fixture run-condition failure",
                 "changes": ["environment"]}
    scenario.run("S1", retry=retry, denied="five repair rounds")
    assert len({result["step_run_hash"] for result in attempts}) == 6


def test_runtime_draft_audit_repair_cannot_bypass_step_repair_cap(scenario):
    scenario.config.write_text("r06", encoding="utf-8")
    scenario.contract["steps"]["S1"]["config"]["sha256"] = fingerprint(scenario.config)
    unaffected_config = scenario.file("unaffected.txt", "copy")
    for step in ("S2", "S3"):
        scenario.contract["steps"][step]["config"] = {"path": unaffected_config.name, "sha256": fingerprint(unaffected_config)}
    scenario.initialize()
    scenario.authorize(["S1", "S2"])
    retry = None
    for _ in range(5):
        result = scenario.run("S1", retry=retry)
        scenario.review(result, verdict="CHANGES_REQUIRED", route="Runtime")
        retry = {"step_run_hash": result["step_run_hash"], "reason": "Fixture condition", "changes": ["environment"]}
    last_attempt = scenario.run("S1", retry=retry)
    scenario.review(last_attempt)
    scenario.review(scenario.run("S2"))
    scope = scenario.cli("runtime-scope", "N01")
    scenario.cli("runtime-report", "N01")
    decision = scenario.file(".tmp/runtime/draft.json", {
        "scope_hash": scope["scope_hash"], "route": "Runtime", "reason": "Fixture cache",
        "steps": ["S1"], "changes": ["cache"], "auditor": "draft-auditor",
        "report": str(scenario.file(".tmp/runtime/draft.md", scope["scope_hash"])),
    })
    scenario.cli("runtime-audit-repair", "N01", "--evidence", decision, denied="five repair rounds")

    audit = scenario.audit("N01", assessment="CHANGES_REQUIRED", route="Runtime")
    output = "results/data/s1.txt"
    expected = last_attempt["outputs"][output]
    Path(expected["path"]).unlink()
    loss = {"step_id": "S1", "step_run_hash": last_attempt["step_run_hash"], "output": output}
    return_evidence = {
        "audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"],
        "reason": "Lost output after five repairs", "steps": ["S1"], "artifact_loss": [loss],
        "user_message_ref": "user-routes-exhausted-loss", "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    repair = scenario.file(".tmp/capped-rerun.json", {
        **return_evidence, "route": "Runtime", "changes": ["cache"], "rerun_authorized": True,
    })
    scenario.cli("runtime-return", "N01", "--evidence", repair, denied="five repair rounds")
    hold = scenario.file(".tmp/capped-hold.json", {**return_evidence, "route": "Decision"})
    assert scenario.cli("runtime-return", "N01", "--evidence", hold)["artifact_losses"] == [
        {**loss, "expected": expected, "observed": None},
    ]
    upstream = scenario.file(".tmp/capped-upstream.json", {
        **return_evidence, "route": "Proposal", "user_message_ref": "user-exits-exhausted-loss",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    })
    assert scenario.cli("runtime-return", "N01", "--evidence", upstream)["route"] == "Proposal"



def test_runtime_audit_repair_and_return_preserve_evidence(scenario):
    scenario.initialize()
    scenario.authorize(["S1", "S2", "S3"])
    upstream = scenario.run("S1")
    scenario.review(upstream)
    scenario.review(scenario.run("S2"))
    initial = scenario.cli("runtime-scope", "N01")
    scenario.cli("runtime-audit", "N01", denied="generate current Runtime Report")
    scenario.cli("runtime-report", "N01")
    repair = scenario.file(".tmp/runtime/draft.json", {
        "scope_hash": initial["scope_hash"], "route": "Runtime", "reason": "Repair fixture cache",
        "steps": ["S2"], "changes": ["cache"], "auditor": "draft-auditor",
        "report": str(scenario.file(".tmp/runtime/draft.md", initial["scope_hash"])),
    })
    result = scenario.cli("runtime-audit-repair", "N01", "--evidence", repair)
    assert result["affected_steps"] == ["S2", "S3"]
    scenario.cli("runtime-audit-repair", "N01", "--evidence", repair, denied="one consolidated")
    second = scenario.run("S2")
    assert second["attempt"] == 2
    assert second["upstream_steps"]["S1"]["step_run_hash"] == upstream["step_run_hash"]
    scenario.review(second)
    blocked = scenario.audit("N01", assessment="CHANGES_REQUIRED", route="Runtime")
    scenario.accept("N01", blocked, denied="return decision")
    decision = scenario.file(".tmp/return.json", {
        "audit_id": blocked["audit_id"], "scope_hash": blocked["scope_hash"], "route": "Runtime",
        "reason": "Repair fixture transport", "user_message_ref": "user-reject-runtime",
        "decided_at": datetime.now(timezone.utc).isoformat(), "steps": ["S2"], "changes": ["transport"],
        "rerun_authorized": False,
    })
    scenario.cli("runtime-return", "N01", "--evidence", decision, denied="explicit scoped rerun")
    decision_data = json.loads(decision.read_text(encoding="utf-8"))
    decision_data["rerun_authorized"] = True
    scenario.file(".tmp/return.json", decision_data)
    scenario.cli("runtime-return", "N01", "--evidence", decision)
    scenario.review(scenario.run("S2"))
    repaired = scenario.audit("N01")
    assert repaired["scope_hash"] != blocked["scope_hash"]
    assert Path(blocked["report"]["path"]).is_file()
    scenario.accept("N01", repaired)
    scenario.run("S3", denied="fresh scoped authorization")
    scenario.authorize(["S3"], authorized_at=datetime.now(timezone.utc).isoformat())
    result = scenario.run("S3")
    assert result["upstream_audits"]["N01"]["audit_id"] == repaired["audit_id"]


def test_runtime_recovers_an_interrupted_start_without_reusing_attempt(scenario):
    scenario.contract["steps"]["S1"]["command"][3] = "{output-dir:results/data}"
    scenario.initialize()
    scenario.authorize(["S1"])
    original = scenario.run("S1")
    assert original["exit_code"] == 0
    stored = json.loads(scenario.state.read_text(encoding="utf-8"))
    attempt = stored["runtime"]["steps"]["S1"][0]
    # Restore the durable pre-launch state to model a supervisor crash before completion was written.
    del attempt["facts"]
    scenario.state.write_text(json.dumps(stored), encoding="utf-8")
    scenario.run("S1", denied="still running or interrupted")
    evidence = scenario.file(".tmp/interruption.json", {
        **{key: attempt["start"][key] for key in ("run_id", "step_id", "attempt", "started_at")},
        "confirmed_not_running": True, "operator": "supervisor", "reason": "fixture supervisor crash",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    })
    interruption = scenario.cli("runtime-interrupt", "S1", "--evidence", evidence)
    assert interruption["exit_code"] is None
    assert Path(original["report"]["path"]).is_file()
    scenario.review(interruption, verdict="BLOCKED", route="Runtime")
    recovered = scenario.run("S1", retry={
        "step_run_hash": interruption["step_run_hash"], "reason": "restore supervisor", "changes": ["state"],
    })
    assert recovered["attempt"] == 2 and recovered["exit_code"] == 0
