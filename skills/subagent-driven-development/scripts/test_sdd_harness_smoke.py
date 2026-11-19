import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HARNESS = Path(__file__).with_name("sdd-harness.py")


def _record(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class HarnessSmokeTests(unittest.TestCase):
    def test_runtime_return_to_proposal_reconciles_all_manifests(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            reader = root / "reader.md"
            plan = root / "plan.md"
            reader.write_text("reader\n", encoding="utf-8")
            plan.write_text("plan\n", encoding="utf-8")
            refs = {"reader_spec": _record(reader), "build_plan": _record(plan)}
            state = {
                "phase": "runtime",
                "status": "runtime_fix_pending",
                "task_id": None,
                "fix_round": 0,
                "tasks": {},
                "evidence": {},
                "refs": refs,
                "next_allowed_actions": ["retry_runtime_step", "return_building", "return_proposal"],
            }
            _write(root / "state.json", state)
            common = {"reader_spec": refs["reader_spec"], "build_plan": refs["build_plan"]}
            _write(root / "analysis-state.json", {"phase": "runtime", "status": "runtime_fix_pending", "building_manifest": "building/manifest.json", "runtime_manifest": "runtime/manifest.json", **common, "next_allowed_actions": state["next_allowed_actions"]})
            _write(root / "building/manifest.json", {"phase": "building", "status": "task_complete", **common, "runtime_manifest": "runtime/manifest.json"})
            _write(root / "runtime/manifest.json", {"phase": "runtime", "status": "runtime_fix_pending", **common, "building_manifest": "building/manifest.json"})
            result = subprocess.run(
                [sys.executable, str(HARNESS), str(root / "state.json"), "transition", "--to", "proposal", "--action", "return_proposal"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            analysis = json.loads((root / "analysis-state.json").read_text(encoding="utf-8"))
            building = json.loads((root / "building/manifest.json").read_text(encoding="utf-8"))
            runtime = json.loads((root / "runtime/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis["status"], "proposal")
            self.assertEqual(building["status"], "proposal")
            self.assertEqual(runtime["status"], "blocked")

    def test_extension_registration_uses_finite_building_action(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            reader = root / "reader.md"
            plan = root / "plan.md"
            task_spec = root / "task.md"
            for path in (reader, plan, task_spec):
                path.write_text(path.name + "\n", encoding="utf-8")
            refs = {"reader_spec": _record(reader), "build_plan": _record(plan)}
            state = {
                "phase": "building",
                "status": "building_incomplete",
                "task_id": "T01",
                "fix_round": 0,
                "tasks": {"T01": {"status": "task_complete", "task_spec_path": str(task_spec.resolve()), "task_spec_sha256": _record(task_spec)["sha256"]}},
                "evidence": {},
                "refs": refs,
                "next_allowed_actions": ["resume_or_redispatch_implementer"],
            }
            _write(root / "state.json", state)
            common = {"reader_spec": refs["reader_spec"], "build_plan": refs["build_plan"]}
            _write(root / "analysis-state.json", {"phase": "building", "status": "building_incomplete", "building_manifest": "building/manifest.json", "runtime_manifest": "runtime/manifest.json", **common, "next_allowed_actions": state["next_allowed_actions"]})
            _write(root / "building/manifest.json", {"phase": "building", "status": "building_incomplete", **common, "runtime_manifest": "runtime/manifest.json"})
            _write(root / "runtime/manifest.json", {"phase": "runtime", "status": "blocked", **common, "building_manifest": "building/manifest.json"})
            result = subprocess.run(
                [sys.executable, str(HARNESS), str(root / "state.json"), "register-task", "T01-EXT01", "--action", "resume_or_redispatch_implementer", "--evidence", str(task_spec), "--affected-task", "T01", "--reusable-output", "T01", "--invalidated-output", "T01-output", "--inheritance-constraint", "inherit T01 inputs"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            state_after = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_after["tasks"]["T01-EXT01"]["next_allowed_actions"], ["resume_or_redispatch_implementer"])


if __name__ == "__main__":
    unittest.main()
