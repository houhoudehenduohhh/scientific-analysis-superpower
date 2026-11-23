"""Runtime commands for the SDD Harness. Execute only the approved local argv."""

import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


COMMANDS = {
    "runtime-init", "runtime-authorize", "runtime-run", "runtime-review",
    "runtime-report", "runtime-scope", "runtime-audit", "runtime-accept", "runtime-audit-repair",
    "runtime-return", "runtime-interrupt", "runtime-finish", "runtime-status", "runtime-next-batch", "runtime-next-node",
}
PASS = {"PASS", "PASS_WITH_NOTES"}
FAIL = {"CHANGES_REQUIRED", "BLOCKED"}
ROUTES = {"Runtime", "Building", "Proposal", "Decision"}
RETRY_CONDITIONS = {"environment", "transport", "cache", "scheduler", "state"}
ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}"
SHA256 = r"[0-9a-f]{64}"
RESULT_CATEGORIES = {"data", "plot", "smoke_test"}
RUNTIME_AUDIT_INDEX = "| Task／步骤／节点 ID | 目的与输出 | AC、运行状态及完成边界 | 当前状态 |"
CODE_SUFFIX = re.compile(r"\.(?:pyw?|pyc|pyo|pyd|r|rscript|sh|ps1|bat|cmd|exe|dll|so(?:\.\d+)*|dylib|jar|mjs|js|lua|pl|rb|pth)$", re.I)
LOADER_ENV_PREFIXES = ("PYTHON", "LD_", "DYLD_", "R_", "NODE_", "PERL", "RUBY", "LUA_", "DOTNET_", "COMPLUS_")
LOADER_ENV_KEYS = {"CLASSPATH", "JAVA_HOME", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS",
                   "BASH_ENV", "ENV", "ZDOTDIR", "PSMODULEPATH", "PATHEXT", "SYSTEMROOT", "WINDIR",
                   "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
                   "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS", "XDG_DATA_HOME", "XDG_DATA_DIRS"}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def runtime_message_refs(run, *, include_building_acceptance=True):
    binding = run["building_audit"]["binding"]
    refs = {binding["spec_approval_ref"]}
    if include_building_acceptance:
        refs.add(binding["acceptance_ref"])
    refs.update(entry["approval"]["user_message_ref"] for entry in run["authorizations"])
    refs.update(entry["decision"]["user_message_ref"] for entry in run["return_decisions"])
    refs.update(audit["acceptance"]["user_message_ref"]
                for audit in [*run["audits"].values(), *run["archived_audits"]]
                if audit.get("acceptance"))
    return refs


def execution_scope_id(record):
    return record.get("node_id", record.get("batch_id"))


def earlier_batched_run_message_refs(state, batch_id):
    if batch_id is None:
        return set()
    return {ref for run in state.get("runtime_history", [])
            for ref in runtime_message_refs(run)}


def require_fresh_batch_message_ref(state, batch_id, message_ref, role, *, include_building_acceptance=True):
    if batch_id is None:
        return
    require(message_ref not in earlier_batched_run_message_refs(state, batch_id),
            f"{role} message already used by an earlier batch or Runtime cycle")
    run = state.get("runtime")
    if run is None:
        used_refs = {state["spec_approval"]["user_message_ref"]}
    else:
        used_refs = runtime_message_refs(run, include_building_acceptance=include_building_acceptance)
    require(message_ref not in used_refs, f"{role} message already used in the current batch")


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    require(isinstance(value, str), "timestamp must be an ISO 8601 string with timezone")
    try:
        candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit("invalid ISO 8601 timestamp") from None
    require(candidate.utcoffset() is not None, "timestamp must include timezone")
    require(candidate <= datetime.now(timezone.utc), "timestamp cannot be in the future")
    return candidate


def text(value, label):
    require(isinstance(value, str) and value.strip(), f"{label} must be nonempty text")
    return value


def objects(value, label, *, nonempty=False):
    require(isinstance(value, dict) and (value or not nonempty), f"invalid {label} object")
    return value


def names(value, label, *, nonempty=False):
    require(isinstance(value, list) and (value or not nonempty), f"invalid {label} list")
    for item in value:
        text(item, label)
    require(len(set(value)) == len(value), f"duplicate {label}")
    return value


def matches(value, pattern, label):
    require(isinstance(value, str) and re.fullmatch(pattern, value), f"invalid {label}")
    return value


def digest_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fingerprint(path):
    require(path.is_file(), f"missing file: {path}")
    return {"path": str(path), "sha256": digest_file(path), "bytes": path.stat().st_size}


def verify_file(record):
    path = Path(record["path"])
    require(path.is_file() and path.resolve() == path and digest_file(path) == record["sha256"],
            f"fingerprint changed: {path}")


def digest_value(value):
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def json_object(pairs):
    result = dict(pairs)
    require(len(pairs) == len(result), "duplicate keys in bound JSON evidence")
    return result


def read_json(raw):
    path = Path(text(raw, "--evidence or --artifact")).resolve()
    body = path.read_bytes()
    data = objects(json.loads(body.decode("utf-8-sig"), object_pairs_hook=json_object), str(path))
    return data, {"path": str(path), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def path_at(root, value):
    return (root / text(value, "path")).resolve()


def inside(root, value, parent):
    path = path_at(root, value)
    prefix = root.joinpath(*parent.split("/"))
    require(path.is_relative_to(prefix) and path != prefix, f"path must be under {prefix}: {path}")
    return path


def formal_audit_path(state, worktree, value, phase):
    import sdd_unit_git as unit_git

    unit_root = Path(state.get("git", {}).get("unit_root", worktree))
    parent = unit_root / "audits" / phase
    candidate = unit_root / text(value, "formal audit report path")
    label = f"formal {phase.title()} Audit"
    require(candidate.suffix.lower() == ".md" and candidate.parent == parent,
            f"{label} must be Markdown directly in {parent}")
    canonically_inside(candidate, parent)
    unit_git.inside(candidate, unit_root, label, unit_paths=True)
    unit_git.reject_hardlink(candidate)
    return candidate


def registered_building_audit_path(state, worktree, record):
    # A registered report predates this registration attempt. Preserve both its
    # original path and its fingerprint, including earlier worktree-local reports.
    verify_file(record)
    unit_root = Path(state.get("git", {}).get("unit_root", worktree))
    if Path(record["path"]).is_relative_to(unit_root / "audits" / "building"):
        return inside(unit_root, record["path"], "audits/building")
    return inside(worktree, record["path"], "audits/building")


def file_binding(root, value):
    value = objects(value, "file binding")
    matches(value.get("sha256"), SHA256, "file SHA-256")
    result = {"path": str(path_at(root, value.get("path"))), "sha256": value["sha256"]}
    verify_file(result)
    return result


def graph_order(graph, label, *, previous=()):
    pending = {key: set(names(value.get("needs"), f"{label} dependencies")) for key, value in graph.items()}
    ordered = []
    satisfied = set(previous)
    while pending:
        ready = sorted(key for key, needs in pending.items() if needs <= satisfied)
        if not ready:
            unknown = set().union(*pending.values()) - graph.keys() - satisfied
            require(not unknown, f"unknown {label} dependency: {sorted(unknown)}")
            raise SystemExit(f"{label} dependency cycle")
        ordered.extend(ready)
        satisfied.update(ready)
        for key in ready:
            del pending[key]
    return ordered


def output_name(value):
    path = PurePosixPath(value)
    require(path.as_posix() == value and len(path.parts) >= 3
            and path.parts[0] == "results" and path.parts[1] in RESULT_CATEGORIES
            and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", x) and not x.endswith(".")
                    and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", x, re.I)
                    for x in path.parts), f"invalid output path: {value}")
    return path


def paths_without_collisions(values):
    paths = [PurePosixPath(value.casefold()) for value in values]
    unique = set(paths)
    require(len(paths) == len(unique) and not any(unique.intersection(path.parents) for path in paths),
            "Runtime output paths collide after normalization")


def canonically_inside(path, prefix):
    require(path != prefix and path.is_relative_to(prefix) and path.resolve() == path,
            f"path must be under {prefix} without redirection: {path}")
    return path


def substitutions(step, steps):
    allowed = {"{config}"} if step.get("config") else set()
    allowed.update("{input:" + name + "}" for name in step["inputs"])
    allowed.update("{code:" + name + "}" for name in step.get("code_inputs", {}))
    allowed.update("{output:" + name + "}" for name in step["outputs"])
    allowed.update("{output-dir:" + "/".join(output_name(name).parts[:2]) + "}" for name in step["outputs"])
    for upstream in step["needs"]:
        allowed.update("{upstream:" + upstream + ":" + name + "}" for name in steps[upstream]["outputs"])
    return allowed


def git(root, *args):
    import sdd_unit_git as unit_git

    result = unit_git.git(root, *args, check=False)
    result.check_returncode()
    return result.stdout.strip()


def verify_code(root, commit):
    require(Path(git(root, "rev-parse", "--show-toplevel")).resolve() == root, "code_root must be the Git worktree root")
    require(git(root, "rev-parse", "HEAD") == commit, "current Git HEAD differs from audited HEAD; return to Building")
    require(not git(root, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=none"),
            "tracked worktree changes; return to Building")


def markdown_value(content, key, *, json_value=False, default=...):
    values = re.findall(r"^[ \t]*(?:-[ \t]+)?`?" + re.escape(key) + r"`?[ \t]*[:：][ \t]*(.*?)`?[ \t]*$",
                        content, flags=re.MULTILINE)
    if not values and default is not ...:
        return default
    require(len(values) == 1, f"Markdown must declare exactly one {key}")
    return json.loads(values[0], object_pairs_hook=json_object) if json_value else values[0]


def markdown_field(content, key, expected, *, json_value=False, allow_missing=False):
    default = expected if allow_missing else ...
    require(markdown_value(content, key, json_value=json_value, default=default) == expected,
            f"Markdown {key} differs from bound evidence")


def plan_table(content, heading, columns):
    section = re.search(r"(?ms)^## " + heading + r"\s*\n(.*?)(?=^## |\Z)", content)
    require(section, f"approved Runtime graph section missing: {heading}")
    rows = [line.strip().strip("|").split("|") for line in section[1].splitlines()
            if line.strip().startswith("|") and line.strip().endswith("|")]
    require(len(rows) >= 3 and len(rows[0]) == columns, f"approved Runtime graph table missing: {heading}")
    data = [[cell.strip().strip("`") for cell in row] for row in rows[2:]]
    require(all(len(row) == columns for row in data), f"invalid approved Runtime graph row: {heading}")
    require(len({row[0] for row in data}) == len(data), f"duplicate approved Runtime graph ID: {heading}")
    return data


def plan_ids(cell):
    if cell in {"", "无", "—", "-", "none"}:
        return set()
    values = [value.strip().strip("`") for value in re.split(r"[,，、;；/／\s]+", cell)]
    return {matches(value, ID, "approved Runtime graph identifier") for value in values if value}


def verify_plan_graph(content, nodes, steps, batch_id=None):
    if batch_id is not None:
        from sdd_layout import batch_plan

        layout = batch_plan(content)
        batch = layout["batches"][batch_id]
        require(batch["nodes"] == nodes.keys() and batch["steps"] == steps.keys(),
                "contract IDs differ from the approved Building batch")
        for node, spec in nodes.items():
            require(set(spec["needs"]) == layout["nodes"][node]["needs"],
                    f"node {node} differs from approved Runtime graph")
        for step, spec in steps.items():
            expected = layout["steps"][step]
            require(expected["task"] == spec["task_id"]
                    and step in layout["nodes"][spec["node"]]["steps"]
                    and expected["needs"] & layout["steps"].keys() == set(spec["needs"])
                    and expected["needs"] & layout["nodes"].keys() <= set(nodes[spec["node"]]["needs"]),
                    f"step {step} differs from approved Runtime graph")
        return
    plan_steps = plan_table(content, "Runtime 执行图", 6)
    plan_nodes = plan_table(content, "阶段性验收节点", 6)
    require({row[0] for row in plan_steps} == steps.keys() and {row[0] for row in plan_nodes} == nodes.keys(),
            "contract IDs differ from approved Runtime graph")
    for step_id, task, dependencies, *_ in plan_steps:
        spec = steps[step_id]
        approved = plan_ids(dependencies)
        require(plan_ids(task) == {spec.get("task_id")} and approved & steps.keys() == set(spec["needs"])
                and approved <= steps.keys() | nodes.keys()
                and approved & nodes.keys() <= set(nodes[spec["node"]]["needs"]),
                f"step {step_id} differs from approved Runtime graph")
    for node_id, _, members, dependencies, *_ in plan_nodes:
        require(plan_ids(members) == {step_id for step_id, spec in steps.items() if spec["node"] == node_id}
                and plan_ids(dependencies) == set(nodes[node_id]["needs"]),
                f"node {node_id} differs from approved Runtime graph")


def command_files(root, step, available, tracked):
    declared = objects(step.get("code_inputs", {}), "step code_inputs")
    files = {matches(name, ID, "code input ID"): file_binding(root, value)
             for name, value in declared.items()}
    allowed_paths = {Path(record["path"]) for record in files.values()}
    for arg in step["command"][1:]:
        if arg in available:
            continue
        value = arg.partition("=")[2] if arg.startswith("-") and "=" in arg else arg
        candidate = root / value
        if candidate.exists() or re.search(r"[/\\]", value) or CODE_SUFFIX.search(value):
            path = candidate.resolve()
            require(path in allowed_paths or (candidate == path and path in tracked),
                    f"unbound code argument: {value}")
            if path not in allowed_paths:
                files["git:" + path.relative_to(root).as_posix()] = fingerprint(path)
    return files


def verify_untracked_code(root, allowed_files):
    approved = {Path(record["path"]) for record in allowed_files}
    for value in git(root, "ls-files", "-z", "--others").split("\0"):
        if value:
            path = root / value
            link = path.is_symlink() or (os.name == "nt" and getattr(path, "is_junction", lambda: False)())
            if not link and not CODE_SUFFIX.search(value):
                continue
            require(path in approved and path.resolve() == path, f"unbound code or dependency in Runtime worktree: {path}")


def platform_environment():
    environment = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    if os.name != "nt":
        return environment
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    require(0 < length < len(buffer), "could not determine Windows system directory")
    return {**environment, "SYSTEMROOT": buffer.value, "WINDIR": buffer.value}


def step_environment(step, code_files):
    environment = objects(step.get("environment", {}), "step environment")
    result = {}
    for key, value in environment.items():
        matches(key, r"[A-Za-z_][A-Za-z0-9_]*", "environment variable name")
        require(isinstance(value, str) and "\0" not in value, f"environment value {key} must be text without NUL")
        upper = key.upper()
        require(upper not in LOADER_ENV_KEYS and not upper.startswith(LOADER_ENV_PREFIXES),
                f"loader environment variable is prohibited: {key}")
        name = upper if os.name == "nt" else key
        require(name not in result, "duplicate Windows environment variable")
        result[name] = value
    if "PATH" in result:
        bound = {Path(code_files[name]["path"]) for name in step.get("code_inputs", {})}
        directories = [Path(path) for path in result["PATH"].split(os.pathsep)]
        for directory in directories:
            require(directory.is_absolute() and directory.is_dir() and directory.resolve() == directory,
                    "PATH requires canonical absolute directories")
            require(any(path.parent == directory and os.access(path, os.X_OK)
                        and (os.name != "nt" or path.suffix.lower() in {".exe", ".com"}) for path in bound),
                    f"PATH directory requires a bound executable in code_inputs: {directory}")
        for executable in bound:
            if executable.parent in directories:
                candidates = (directory / executable.name for directory in directories)
                first = next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
                require(first == executable, f"PATH shadows bound executable: {executable}")
    return result


def verified_contract(contract, state, *, previous_nodes=None, previous_steps=None):
    matches(contract.get("run_id"), ID, "run ID")
    root = Path(text(contract.get("code_root"), "code_root")).resolve(strict=True)
    if state.get("git"):
        require(root == Path(state["git"]["worktree"]), "Runtime code_root differs from the functional-unit worktree")
    commit = matches(contract.get("code_commit"), r"[0-9a-f]{40}|[0-9a-f]{64}", "audited HEAD")
    verify_code(root, commit)
    require(contract.get("build_plan_sha256") == state["refs"]["build_plan"]["sha256"],
            "current Build Plan fingerprint differs from Runtime contract")
    tasks = objects(contract.get("task_specs"), "task_specs", nonempty=True)
    expected = {key: value.get("task_spec_sha256") for key, value in state["tasks"].items()}
    require(tasks == expected, "current Task MD fingerprints differ from Runtime contract")
    require(state["evidence"].get("task_complete"), "completed Building Task Review evidence is missing")
    inputs = objects(contract.get("inputs"), "inputs")
    for key, entry in inputs.items():
        matches(key, ID, "input ID")
        file_binding(root, entry)
        text(entry.get("identity"), f"input {key} identity")
        text(entry.get("qualification"), f"input {key} qualification")
    nodes = objects(contract.get("nodes"), "nodes", nonempty=True)
    steps = objects(contract.get("steps"), "steps", nonempty=True)
    for node, value in nodes.items():
        matches(node, r"N[0-9]{2,}", "node ID")
        objects(value, "node")
    for name, step in steps.items():
        matches(name, ID, "step ID")
        objects(step, "step")
    all_steps = {**(previous_steps or {}), **steps}
    require(not nodes.keys() & (previous_nodes or {}).keys() and not steps.keys() & (previous_steps or {}).keys(),
            "contract IDs overlap a completed Building batch")
    node_order = graph_order(nodes, "node", previous=previous_nodes or ())
    step_order = graph_order(steps, "step", previous=previous_steps or ())
    plan = Path(state["refs"]["build_plan"]["path"]).read_text(encoding="utf-8")
    markdown_field(plan, "decision", "approved")
    tracked_paths = git(root, "ls-tree", "-r", "-z", "--name-only", commit).split("\0")
    tracked = {root / path for path in tracked_paths if path}
    code_files, executables = {}, {}
    for name, step in steps.items():
        node = text(step.get("node"), "step node")
        require(node in nodes, f"unknown node for step {name}")
        task = text(step.get("task_id"), "step task_id")
        require(task in tasks, f"unknown Building Task {task} for {name}")
        spec = Path(state["tasks"][task]["task_spec_path"]).read_text(encoding="utf-8")
        markdown_field(spec, "approval_status", "approved")
        for ac in names(step.get("acs"), "ACs", nonempty=True):
            matches(ac, re.escape(task) + r"-AC[0-9]{2,}", "AC ID")
            require(re.search(r"(?<![\w-])" + re.escape(ac) + r"(?![\w-])", spec),
                    f"AC {ac} not found in bound Task MD")
        for upstream in step["needs"]:
            dependency_node = all_steps[upstream].get("node")
            require(dependency_node == node or dependency_node in nodes[node]["needs"],
                    f"step {name} has undeclared cross-node prerequisite {upstream}")
        require(set(names(step.get("inputs"), "step inputs")) <= inputs.keys(), f"unknown input for {name}")
        for output in names(step.get("outputs"), "step outputs", nonempty=True):
            output_name(output)
        if step.get("config") is not None:
            file_binding(root, step["config"])
        command = step.get("command")
        require(isinstance(command, list) and command and all(isinstance(arg, str) and arg for arg in command),
                f"invalid command argv for {name}")
        executable = Path(command[0])
        require(executable.is_absolute() and executable.is_file() and executable.resolve().suffix.lower() not in {".cmd", ".bat"},
                f"command for {name} requires an absolute executable path")
        executables[name] = file_binding(root, {"path": command[0], "sha256": step.get("executable_sha256")})
        available = substitutions(step, all_steps)
        for arg in command:
            require(not re.fullmatch(r"\{(?:config\}|(?:input|output|output-dir|upstream|code):.*\})", arg)
                    or arg in available, f"unapproved argument reference {arg}")
        code_files[name] = command_files(root, step, available, tracked)
        require(all("{output:" + out + "}" in command
                    or "{output-dir:" + "/".join(output_name(out).parts[:2]) + "}" in command
                    for out in step["outputs"]),
                f"command for {name} must receive every approved output path")
        require(all("{input:" + source + "}" in command for source in step["inputs"]),
                f"command for {name} must receive every approved input path")
        resources = objects(step.get("resources"), "step resources")
        timeout = resources.get("timeout_seconds")
        require(type(timeout) is int and timeout > 0, f"positive timeout_seconds required for {name}")
        step_environment(step, code_files[name])
    for node in nodes:
        require(any(step["node"] == node for step in steps.values()), f"no steps declared for node {node}")
    verify_plan_graph(plan, nodes, steps, execution_scope_id(state.get("spec_approval", {})))
    return root, node_order, step_order, executables, code_files


def markdown(path, heading, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(f"# {heading}\n\n")
        handle.write("## 运行身份\n\n")
        for key in ("run_id", "node_id", "step_id", "attempt", "step_run_hash", "run_hash", "building_audit_id",
                    "code_commit", "build_plan_sha256", "task_id"):
            if key in data:
                handle.write(f"- `{key}` · `{data[key]}`\n")
        handle.write("\n## 实际输入、配置与环境\n\n")
        handle.write("附录记录运行参数、输入身份和 SHA-256 指纹。\n\n")
        handle.write("## 执行经过\n\n")
        if "step_id" in data:
            handle.write(f"- 开始时间 · {data['started_at']}\n- 结束时间 · {data['finished_at']}\n")
            handle.write(f"- 退出码 · {data['exit_code']}\n- 耗时（秒） · {data['elapsed_seconds']}\n")
        else:
            for step, attempts in data["steps"].items():
                for attempt in attempts:
                    handle.write(f"- `{step}` · 第 {attempt['start']['attempt']} 次 · "
                                 f"{attempt['review']['verdict']} · `{attempt['facts']['report']['path']}`\n")
        handle.write("\n## 输出清单与事实检查\n\n")
        outputs = data.get("outputs")
        if outputs is not None:
            for binding in outputs.values():
                handle.write(f"- `{binding['path']}` · {binding['bytes']} 字节 · `{binding['sha256']}`\n")
        else:
            handle.write("逐步产物和未完成尝试见附录。\n")
        handle.write("\n## 后续审查输入\n\n")
        handle.write("请核查输出与获批验收条件。附录为 Harness 自动生成的机器事实记录。\n\n")
        handle.write("````json\n")
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
        handle.write("\n````\n")
    return fingerprint(path)


def validate_limits(data):
    limits = names(data.get("limitations"), "limitations")
    require(data["assessment"] != "PASS_WITH_NOTES" or limits, "PASS_WITH_NOTES requires stated limitations")
    return limits


def review_route(data, verdict):
    route = data.get("route")
    require((verdict in FAIL and route in ROUTES) or (verdict in PASS and route is None),
            "failing review or audit requires an explicit return route")


def distinct_file(record, others, label):
    path = Path(record["path"])
    require(all(record["sha256"] != other["sha256"] and (not Path(other["path"]).exists()
                or not path.samefile(other["path"])) for other in others), f"{label} evidence must be independent")


def verify_review(record):
    verify_file(record["receipt"])
    verify_file(record["report"])


def verify_attempt_inputs(facts):
    if facts["config"]:
        verify_file(facts["config"])
    for binding in [facts["executable"], *facts["code_files"].values(), *facts["inputs"].values()]:
        verify_file(binding)


def verify_audit(audit):
    verify_review(audit)
    if audit.get("summary"):
        verify_file(audit["summary"])
    if audit.get("publication"):
        verify_file(audit["publication"])
    if audit.get("acceptance"):
        verify_file(audit["acceptance"]["receipt"])


def step_permission(data, step):
    reopen = data["reopen"].get(step)
    if reopen and reopen.get("is_user_authorized"):
        return reopen
    return next((entry for entry in reversed(data["authorizations"])
                 if step in entry["approval"]["steps"]), None)


def permission_is_current(permission, reopen):
    return permission and (not reopen or not reopen.get("requires_fresh_authorization")
                           or (timestamp(permission["recorded_at"]) > timestamp(reopen["recorded_at"])
                               and timestamp(permission["approval"]["authorized_at"]) >=
                               timestamp(reopen["decision"]["decided_at"])))


def verify_building_gate(gate, state, root, commit):
    require(gate and gate["code_root"] == str(root) and gate["code_commit"] == commit,
            "durable Building gate evidence for the audited HEAD is required")
    for record in gate["files"]:
        verify_file(record)
    require(gate["build_plan"] == state["refs"]["build_plan"]
            and gate["audit"] == state["evidence"]["building_audit"]
            and gate["task_specs"] == {key: value["task_spec_sha256"] for key, value in state["tasks"].items()},
            "Building gate evidence has changed")
    verify_overall_review(state, state["evidence"].get("building_audit_pending", []), commit,
                          audit=gate["audit"], for_runtime=True)
    if gate.get("audit_binding") is not None:
        verify_building_report_bindings(
            gate["audit"][0], gate["audit_binding"], commit, gate["build_plan"]["sha256"], gate["task_specs"])


def overall_review_metadata(content):
    lines = content.splitlines()
    title = next((line for line in lines if line.strip()), "")
    require(re.fullmatch(r" {0,3}(?:#{1,6}[ \t]+)?(?:Overall Review|Final Review|整体初审|整体审查)[ \t]*",
                         title, flags=re.IGNORECASE),
            "Overall Review report must start with the whole-branch review title")

    return "\n".join(markdown_lines_outside_code(lines))


def markdown_lines_outside_code(lines, *, preserve_hidden_boundaries=False):
    """Keep Markdown structure visible outside literal code and raw HTML."""
    closing_fence = None
    closing_html = None
    in_comment = False
    hidden = "<!-- -->" if preserve_hidden_boundaries else ""
    for line in lines:
        if closing_fence is not None:
            if closing_fence.fullmatch(line):
                closing_fence = None
            yield ""
            continue
        if closing_html is not None:
            if closing_html.search(line):
                closing_html = None
            yield hidden if line.strip() else ""
            continue
        fence = None if in_comment else re.fullmatch(r" {0,3}(`{3,})[^`]*| {0,3}(~{3,}).*", line)
        if fence:
            marker = fence[1] or fence[2]
            closing_fence = re.compile(r" {0,3}" + marker + marker[0] + r"*[ \t]*")
            yield ""
            continue
        if not in_comment and line.expandtabs(4).startswith("    "):
            yield ""
            continue
        if in_comment or "<!--" in line:
            while line:
                _, boundary, line = line.partition("-->" if in_comment else "<!--")
                if not boundary:
                    break
                in_comment = not in_comment
            yield hidden
            continue
        html = re.match(r" {0,3}</?([A-Za-z][A-Za-z0-9-]*)(?=[ \t/>]|$)", line)
        if html:
            tag = html[1].lower()
            if tag in {"pre", "script", "style", "textarea"} and not line.lstrip().startswith("</"):
                end = re.compile(r"</" + tag + r"[ \t]*>", re.I)
                if not end.search(line):
                    closing_html = end
            else:
                closing_html = re.compile(r"^[ \t]*$")
            yield hidden
            continue
        yield line


def verify_runtime_index(content, node_ids, steps):
    from sdd_layout import table

    message = "Runtime Audit requires the human-readable acceptance index with scoped node, Task, step and AC IDs"
    try:
        rows = table(content, "## 6. 任务验收索引", RUNTIME_AUDIT_INDEX, label="acceptance index", require_block_break=True)
    except ValueError as exc:
        raise SystemExit(f"{message}. {exc}") from None
    require(all(all(re.search(r"\w", cell) for cell in row) for row in rows), message)

    def indexed(values, column):
        words = set(re.findall(r"[A-Za-z0-9_-]+", " ".join(row[column] for row in rows)))
        return values <= words

    identifiers = {*node_ids, *steps, *(step["task_id"] for step in steps.values())}
    acs = {ac for step in steps.values() for ac in step["acs"]}
    require(indexed(identifiers, 0) and indexed(acs, 2), message)


def verify_overall_review(state, records, commit, *, audit=None, for_runtime=False):
    require(len(records) == 1, "Building Audit requires one independent Overall Review report")
    review = records[0]
    verify_file(review)
    role_records = list(audit or ())
    for task in state["tasks"].values():
        chain = task.get("building_chain", {})
        role_records.extend(chain.get("implementation", []) + chain.get("review", []))
        for repair in chain.get("fix_rounds", []):
            role_records.extend(repair.get("findings", []) + repair.get("implementation", []))
    distinct_file(review, role_records, "Overall Review")
    content = overall_review_metadata(Path(review["path"]).read_text(encoding="utf-8-sig"))
    content = re.sub(r"(?m)^([ \t]*(?:-[ \t]+)?`?(?:HEAD|Verdict)`?[ \t]*[:：][ \t]*)`([^`\r\n]+)`([ \t]*)$",
                     r"\1\2\3", content)
    try:
        verdict = markdown_value(content, "Verdict")
        require(verdict in {"PASS", "CHANGES_REQUIRED"}, "Verdict must be PASS or CHANGES_REQUIRED")
        markdown_field(content, "HEAD", commit)
    except SystemExit as exc:
        raise SystemExit(f"Overall Review: {exc}") from None
    if audit is not None:
        require(len(audit) == 1, "Building gate requires one formal Building Audit")
        report = Path(audit[0]["path"]).read_text(encoding="utf-8-sig")
        assessment = markdown_value(report, "assessment")
        require(assessment in PASS | FAIL, "invalid formal Building Audit assessment")
        require(assessment not in PASS or verdict == "PASS",
                "passing Building Audit requires a passing Overall Review")
        if for_runtime:
            require(verdict == "PASS", "Runtime requires a passing Overall Review")
            require(assessment in PASS, "Runtime requires a passing Building Audit")
    return review


def verify_building_report_bindings(report, binding, commit, build_plan_sha256, task_specs):
    require(binding["report_sha256"] == report["sha256"], "Building Audit report fingerprint mismatch")
    path = Path(report["path"])
    require(path.is_file() and path.resolve() == path, f"fingerprint changed: {path}")
    content = path.read_bytes()
    require(hashlib.sha256(content).hexdigest() == report["sha256"], f"fingerprint changed: {path}")
    # Recognize the same declarations as the legacy gate, including nested list entries.
    report_text = "\n".join(content.decode("utf-8-sig").splitlines())
    fields = (
        ("code_commit", commit), ("build_plan_sha256", build_plan_sha256),
        ("task_specs", task_specs), ("contract_sha256", binding["contract_sha256"] or "null"),
    )
    for field, expected in fields:
        markdown_field(report_text, field, expected, json_value=field == "task_specs", allow_missing=True)


def record_building_gate(state, root, evidence_path, verify_report_layout, *, evidence_root=None):
    import sdd_layout
    import sdd_unit_git as unit_git

    root = root.resolve(strict=True)
    commit = git(root, "rev-parse", "HEAD")
    verify_code(root, commit)
    data, receipt = read_json(evidence_path)
    ledger = path_at(root, data.get("ledger"))
    if evidence_root is not None:
        unit_git.inside(ledger, evidence_root, "Building ledger", unit_paths=True)
    require(ledger.name == "progress.md", "Building gate requires the SDD progress.md ledger")
    ledger_text = ledger.read_text(encoding="utf-8")
    tasks = objects(data.get("tasks"), "Building gate tasks", nonempty=True)
    require(tasks.keys() == state["tasks"].keys(), "Building gate requires evidence per registered task")
    task_specs = {key: task["task_spec_sha256"] for key, task in state["tasks"].items()}
    if state.get("spec_approval"):
        require(state["spec_approval"]["task_specs"] == task_specs,
                "Building gate requires every Task in the current Spec approval")
    audit = state["evidence"].get("building_audit", [])
    require(len(audit) == 1, "Building gate requires current formal Building Audit")
    report = registered_building_audit_path(state, root, audit[0])
    verify_report_layout(report, "building")
    audit_text = report.read_text(encoding="utf-8")
    plan_path = Path(state["refs"]["build_plan"]["path"])
    structured = sdd_layout.structured_plan(plan_path.read_text(encoding="utf-8"))
    task_ids = tasks.keys() if execution_scope_id(state.get("spec_approval", {})) else None
    if structured:
        unit_root = Path(state.get("git", {}).get("unit_root", root))
        require(report.parent in {root / "audits/building", unit_root / "audits/building"}
                and report.suffix.lower() == ".md", "formal Building Audit must be Markdown directly in audits/building")
        sdd_layout.verify_acceptance_index(audit_text, plan_path, task_ids=task_ids)
    final_review = verify_overall_review(state, state["evidence"].get("building_audit_pending", []),
                                         commit, audit=audit)
    audit_binding = None
    if "audit_binding" in data:
        audit_binding = objects(data["audit_binding"], "Building audit binding")
        report_sha256 = matches(audit_binding.get("report_sha256"), SHA256, "Building Audit report SHA-256")
        require("contract_sha256" in audit_binding, "Building audit binding requires contract_sha256")
        contract_sha256 = audit_binding["contract_sha256"]
        if contract_sha256 is not None:
            matches(contract_sha256, SHA256, "Building Audit Runtime contract SHA-256")
        audit_binding = {"report_sha256": report_sha256, "contract_sha256": contract_sha256}
    previous_gate = state.get("building_gate")
    if previous_gate and previous_gate["audit"][0]["sha256"] == audit[0]["sha256"]:
        require(previous_gate.get("audit_binding") == audit_binding,
                "a recorded Building Audit cannot change its Runtime contract binding")
    if audit_binding is not None:
        verify_building_report_bindings(audit[0], audit_binding, commit, state["refs"]["build_plan"]["sha256"],
                                        task_specs)
    files = [receipt, fingerprint(ledger), final_review]
    role_records = [*audit, final_review]
    task_bases = []
    for task, info in state["tasks"].items():
        approval = tasks[task]
        chain = info.get("building_chain", {})
        require(chain.get("implementation") and chain.get("review"),
                f"Building gate requires complete Implementer and Task Review evidence for {task}")
        brief = path_at(root, approval.get("brief"))
        if evidence_root is not None:
            unit_git.inside(brief, evidence_root, "Task brief", unit_paths=True)
        require(brief.suffix.lower() == ".md", f"Building task {task} brief must be Markdown")
        spec_sha256 = info["task_spec_sha256"]
        match = re.search(r"(?m)^.*\bTask " + re.escape(task) +
                          r":\s*complete\s*\(commits\s+([0-9a-f]{7,64})\.\.([0-9a-f]{7,64}),\s*review clean\)([^\n]*)$",
                          ledger_text)
        require(match and spec_sha256 in match[3], f"Building ledger lacks approved Task and scoped commits for {task}")
        base, head = [git(root, "rev-parse", "--verify", ref + "^{commit}") for ref in match.group(1, 2)]
        task_bases.append(base)
        require(base != head, f"Building task {task} requires a committed change")
        git(root, "merge-base", "--is-ancestor", base, head)
        git(root, "merge-base", "--is-ancestor", head, commit)
        implementation = Path(chain["implementation"][0]["path"]).read_text(encoding="utf-8")
        review = Path(chain["review"][0]["path"]).read_text(encoding="utf-8")
        task_binding = r"(?<![\w-])" + re.escape(task) + r"(?![\w-])"
        implementation_heads = re.findall(r"(?im)^\s*(?:-\s+)?(?:\*\*|`)?Commit(?:\*\*|`)?\s*[:：]\s*(?:\*\*|`)?([0-9a-f]{7,64})",
                                          implementation)
        require(re.search(task_binding, implementation) and len(implementation_heads) == 1,
                f"Implementer evidence must identify Task and initial commit for {task}")
        implementation_head = git(root, "rev-parse", "--verify", implementation_heads[0] + "^{commit}")
        require(implementation_head != base, f"Implementer evidence must identify a change for {task}")
        git(root, "merge-base", "--is-ancestor", base, implementation_head)
        git(root, "merge-base", "--is-ancestor", implementation_head, head)
        rounds = chain.get("fix_rounds", [])
        require((implementation_head == head) == (not rounds),
                f"Building task {task} commit range requires its repair history")
        for index, repair in enumerate(rounds, 1):
            require(repair.get("findings") and repair.get("implementation")
                    and re.search(r"(?m)Task " + re.escape(task) + f": fix round {index}/5", ledger_text),
                    f"Building task {task} is missing fix round {index} evidence")
        require(re.search(task_binding, review) and match[2] in review,
                f"Task Review must identify Task and reviewed commit for {task}")
        markdown_field(review, "Verdict", "PASS")
        brief_record = fingerprint(brief)
        require(brief_record["sha256"] == spec_sha256 and not brief.samefile(info["task_spec_path"]),
                f"Task brief snapshot differs from approved Task MD for {task}")
        task_records = [brief_record]
        if not structured:
            human_report = inside(root, approval.get("human_report"), "audits/building/report")
            require(human_report.suffix.lower() == ".md", f"Building task {task} human report must be Markdown")
            require(re.search(task_binding, human_report.read_text(encoding="utf-8"))
                    and human_report.name in audit_text, f"formal Building Audit must index the human report for {task}")
            task_records.append(fingerprint(human_report))
        repair_records = [record for repair in rounds for role in ("findings", "implementation") for record in repair[role]]
        for record in [*chain["implementation"], *repair_records, *chain["review"], *task_records]:
            distinct_file(record, role_records, f"Building task {task}")
            role_records.append(record)
            files.append(record)
    for record in files:
        verify_file(record)
    if structured:
        baseline = state.get("building_baseline") or state.get("git", {}).get("baseline_commit")
        if baseline:
            git(root, "merge-base", "--is-ancestor", baseline, commit)
            task_bases.append(baseline)
        sdd_layout.verify_building_paths(root, plan_path, task_bases, commit, task_ids=task_ids)
    return {
        "code_root": str(root), "code_commit": commit, "files": files,
        "build_plan": state["refs"]["build_plan"], "audit": audit,
        "task_specs": task_specs,
        **({"audit_binding": audit_binding} if audit_binding is not None else {}),
    }


class Runtime:
    def __init__(self, state, save, verify_report_layout, *, state_path=None):
        self.state = state
        self.state_path = Path(state_path).resolve() if state_path is not None else None
        self.worktree = Path(state["git"]["worktree"]) if state.get("git") else None
        self.save = save
        self.verify_report_layout = verify_report_layout
        self.scopes = {}
        self.requested_losses = set()
        self.observed_losses = {}
        self.retired_losses = {}
        self.previous_nodes = {}
        self.previous_steps = {}
        self.data = state.get("runtime")
        self.runtime_root = None
        if self.data:
            self.contract = self.data["contract"]
            self.root = Path(self.contract["code_root"]).resolve()
            self.steps = self.contract["steps"]
            self.nodes = self.contract["nodes"]
            self.run_id = self.contract["run_id"]
            if self.data["schema_version"] == 2:
                self.runtime_root = self.run_workspace(self.root, self.run_id)
            for returned in self.data["return_decisions"]:
                if returned["decision"]["route"] != "Runtime":
                    continue
                for loss in returned.get("artifact_losses", []):
                    self.retired_losses[(loss["step_id"], loss["step_run_hash"], loss["output"])] = (returned, loss)

    def verify_completed_batches(self):
        histories = {item["run_id"]: item for item in self.state.get("building_history", [])}
        for run in self.state.get("runtime_history", []):
            if "batch_completed_at" not in run:
                continue
            history = histories[run["contract"]["run_id"]]
            original = Runtime({**history, "git": self.state["git"], "runtime": run}, None,
                               self.verify_report_layout, state_path=self.state_path)
            original.previous_nodes = self.previous_nodes.copy()
            original.previous_steps = self.previous_steps.copy()
            snapshots = history["spec_snapshots"]
            for record in [*snapshots.values(), history["refs"]["spec_approval"], run["contract_ref"],
                           run["building_audit"]["receipt"], run["building_audit"]["report"]]:
                verify_file(record)
            require(snapshots["build-plan"]["sha256"] == run["contract"]["build_plan_sha256"]
                    and {task: snapshots[task]["sha256"] for task in run["contract"]["task_specs"]}
                    == run["contract"]["task_specs"], "completed batch Spec binding changed")
            for task, snapshot in history["tasks"].items():
                verify_file({"path": snapshot["task_spec_path"], "sha256": snapshots[task]["sha256"]})
            verify_building_gate(history["building_gate"], original.state, original.root,
                                 original.contract["code_commit"])
            require(not self.previous_nodes.keys() & original.nodes.keys()
                    and not self.previous_steps.keys() & original.steps.keys(),
                    "duplicate IDs in completed Building batches")
            for node in run["node_order"]:
                original.accepted_node(node)
                self.previous_nodes[node] = original
            self.previous_steps.update({step: original for step in run["step_order"]})

    def next_batch(self, args):
        by_node = "node_id" in self.data
        command = "runtime-next-node" if by_node else "runtime-next-batch"
        require(args.action == command, f"this Build Plan uses {command}")
        require(not args.value and not args.evidence and not args.artifact,
                f"{command} uses the current accepts and takes no scope or evidence")
        next_key = "next_node" if by_node else "next_batch"
        next_scope = self.data.get(next_key)
        require(next_scope, "no later execution scope in the approved Build Plan")
        require(all(self.data["audits"].get(node, {}).get("acceptance") for node in self.nodes),
                "complete and accept every current batch milestone before advancing"
                if not by_node else "accept the current Runtime node before advancing")
        for node in self.data["node_order"]:
            self.accepted_node(node)
        self.data.update(batch_completed_at=now(), return_stage="Proposal")
        self.save(command)
        return {"status": "proposal", next_key: next_scope}

    def run_workspace(self, root, run_id):
        require(self.state_path is not None, "Runtime requires the bound state path")
        workspace = canonically_inside(self.state_path.parent, root / ".tmp" / "sdd")
        return canonically_inside(workspace / "runtime" / run_id, workspace)

    def runtime_file(self, raw, folder):
        return canonically_inside(self.root / text(raw, "Runtime evidence path"), self.runtime_root / folder)

    def attachment_path(self, raw):
        import sdd_unit_git as unit_git

        raw_path = Path(text(raw, "--evidence or --artifact")).absolute()
        path = raw_path.resolve()
        if self.runtime_root is not None:
            canonically_inside(raw_path, self.runtime_root / "evidence")
        if self.worktree is not None:
            unit_git.inside(path, self.worktree, "Runtime attachment", unit_paths=True)
        return path

    def read_attachment(self, raw):
        return read_json(str(self.attachment_path(raw)))

    def initialize(self, args):
        import sdd_layout

        require(not self.data and self.state["status"] == "building_audit_gate",
                "runtime-init requires current Building Audit gate and no existing Runtime")
        reports = self.state["evidence"].get("building_audit", [])
        require(len(reports) == 1, "one current Building Audit report must be registered")
        contract, contract_ref = self.read_attachment(args.artifact)
        evidence, receipt = self.read_attachment(args.evidence)
        root, node_order, step_order, executables, code_files = verified_contract(
            contract, self.state, previous_nodes=self.previous_nodes,
            previous_steps={step: runtime.steps[step] for step, runtime in self.previous_steps.items()},
        )
        plan = Path(self.state["refs"]["build_plan"]["path"]).read_text(encoding="utf-8")
        batch_id = execution_scope_id(self.state.get("spec_approval", {}))
        next_batch = None
        if batch_id is not None:
            layout = sdd_layout.batch_plan(plan)
            order = list(layout["batches"])
            remaining = order[order.index(batch_id) + 1:]
            next_batch = remaining[0] if remaining else None
            require(layout["batches"][batch_id]["needs"] <= self.previous_nodes.keys(),
                    "Building batch prerequisites must have accepted Runtime milestones")
        structured = sdd_layout.structured_plan(plan)
        if structured:
            self.runtime_root = self.run_workspace(root, contract["run_id"])
            self.attachment_path(args.artifact)
            self.attachment_path(args.evidence)
            for name in [contract["run_id"], *contract["steps"]]:
                output_name(f"results/data/{name}/candidate")
            for values in (contract["steps"], contract["nodes"]):
                require(len({name.casefold() for name in values}) == len(values),
                        "Runtime IDs collide after normalization")
            logical_outputs = [name for step in contract["steps"].values() for name in step["outputs"]]
            paths_without_collisions(logical_outputs)
            require(set(logical_outputs) <= sdd_layout.result_paths(plan),
                    "Runtime contract includes output paths outside the approved Build Plan")
            for category in RESULT_CATEGORIES:
                target = canonically_inside(root / "results" / category / contract["run_id"], root / "results")
                require(not target.exists(), f"published Runtime run_id already exists: {target}")
        verify_building_gate(self.state.get("building_gate"), self.state, root, contract["code_commit"])
        report = registered_building_audit_path(self.state, root, reports[0])
        require(report.suffix.lower() == ".md", "Building Audit report must be Markdown")
        require(evidence.get("report_sha256") == reports[0]["sha256"], "Building Audit report binding mismatch")
        audit_id = matches(evidence.get("audit_id"), ID, "Building audit_id")
        assessment = evidence.get("assessment")
        require(assessment in PASS, "Building Audit assessment must allow acceptance")
        self.verify_report_layout(report, "building")
        report_text = report.read_text(encoding="utf-8")
        for field, expected in (("audit_id", audit_id), ("assessment", assessment), ("audit_user_decision", "pending"),
                                ("accepted_audit_id", "null"), ("execution_authorized_by_user", "no")):
            markdown_field(report_text, field, expected)
        require(evidence.get("audit_user_decision") == "accepted" and evidence.get("accepted_audit_id") == audit_id,
                "Building Audit requires current audit_id acceptance")
        for field in ("code_commit", "build_plan_sha256", "task_specs"):
            require(evidence.get(field) == contract[field], f"Building Audit binding mismatch: {field}")
        require(evidence.get("contract_sha256") == contract_ref["sha256"], "approved Runtime contract fingerprint mismatch")
        audit_binding = self.state["building_gate"].get("audit_binding")
        if audit_binding is None:
            for field in ("code_commit", "build_plan_sha256", "task_specs"):
                markdown_field(report_text, field, contract[field], json_value=field == "task_specs")
            markdown_field(report_text, "contract_sha256", contract_ref["sha256"])
        else:
            require(audit_binding == {"report_sha256": reports[0]["sha256"], "contract_sha256": contract_ref["sha256"]},
                    "Building Audit manifest bindings differ from the current report or Runtime contract")
        limits = validate_limits(evidence)
        markdown_field(report_text, "limitations", limits, json_value=True)
        require(evidence.get("accepted_limitations") == limits, "Building Audit limitations require explicit acceptance")
        acceptance_ref = text(evidence.get("acceptance_ref"), "Building Audit user acceptance reference")
        require_fresh_batch_message_ref(self.state, batch_id, acceptance_ref, "Building Audit acceptance")
        text(evidence.get("spec_approval_ref"), "approved Build Plan and Task MD user message reference")
        presented_at = timestamp(evidence.get("report_presented_at"))
        require(timestamp(evidence.get("accepted_at")) > presented_at,
                "Building Audit acceptance must follow report presentation")
        spec_approval = self.state.get("spec_approval")
        if spec_approval:
            require(evidence["spec_approval_ref"] == spec_approval["user_message_ref"] and
                    contract["task_specs"] == spec_approval["task_specs"] and
                    presented_at > timestamp(spec_approval["approved_at"]),
                    "Building Audit must bind the current Spec approval and follow it")
        prior_runs = self.state.get("runtime_history", [])
        if prior_runs:
            for prior in prior_runs:
                previous_audit = prior["building_audit"]
                require(contract["run_id"] != prior["contract"]["run_id"], "new Runtime cycle requires a fresh run_id")
                require(audit_id != previous_audit["binding"]["audit_id"] and
                        evidence["acceptance_ref"] != previous_audit["binding"]["acceptance_ref"],
                        "new Runtime cycle requires a fresh Building Audit and user acceptance")
                distinct_file(reports[0], [previous_audit["report"]], "new Building Audit")
            prior = prior_runs[-1]
            if "batch_completed_at" in prior:
                require(presented_at > timestamp(prior["batch_completed_at"])
                        and all(evidence["acceptance_ref"] != audit["acceptance"]["user_message_ref"]
                                for audit in prior["audits"].values()),
                        "new Building Audit and acceptance must follow completion of the preceding batch")
            else:
                decision = prior["return_decisions"][-1]["decision"]
                require(presented_at > timestamp(decision["decided_at"]) and evidence["acceptance_ref"] != decision["user_message_ref"],
                        "new Building Audit and acceptance must follow the Runtime return decision")
            if prior["return_stage"] == "Building":
                require(contract["code_commit"] != prior["contract"]["code_commit"],
                        "return to Building requires a newly audited HEAD")
        self.state["runtime"] = {
            "schema_version": 2 if structured else 1, "contract": contract, "contract_ref": contract_ref,
            "building_audit": {"receipt": receipt, "binding": evidence, "report": reports[0]},
            "node_order": node_order, "step_order": step_order, "authorizations": [],
            "steps": {name: [] for name in step_order},
            "executables": executables, "code_files": code_files,
            "platform_environment": platform_environment(),
            "audits": {}, "archived_audits": [], "reopen": {}, "audit_repairs": {}, "reports": {},
            "return_decisions": [], "status": "runtime_authorization_pending",
        }
        if structured:
            self.state["runtime"]["published"] = {}
        if batch_id is not None:
            scope_key = layout["scope_key"]
            next_key = "next_node" if scope_key == "node_id" else "next_batch"
            self.state["runtime"].update({scope_key: batch_id, next_key: next_batch})
        self.save("runtime-init")
        return {"status": "runtime_authorization_pending", "run_id": contract["run_id"],
                "contract_sha256": contract_ref["sha256"], "building_audit_id": audit_id}

    def authorize(self, args):
        approval, receipt = self.read_attachment(args.evidence)
        binding = self.data["building_audit"]["binding"]
        require(approval.get("audit_id") == binding["audit_id"]
                and approval.get("contract_sha256") == self.data["contract_ref"]["sha256"],
                "authorization does not bind the current Building Audit and contract")
        require(timestamp(approval.get("authorized_at")) >= timestamp(binding["accepted_at"]),
                "Runtime authorization must occur at or after Building Audit acceptance")
        message_ref = text(approval.get("user_message_ref"), "Runtime authorization user message reference")
        require_fresh_batch_message_ref(self.state, execution_scope_id(self.data), message_ref,
                                        "Runtime authorization", include_building_acceptance=False)
        require(all(message_ref != entry["approval"]["user_message_ref"]
                    for run in self.state.get("runtime_history", []) for entry in run["authorizations"]),
                "new Runtime cycle requires fresh scoped authorization")
        require(all(entry["approval"]["user_message_ref"] != message_ref for entry in self.data["authorizations"]),
                "Runtime authorization user message already recorded")
        scope = names(approval.get("steps"), "authorized steps", nonempty=True)
        require(set(scope) <= self.steps.keys(), "unknown step in Runtime authorization")
        self.data["authorizations"].append({"approval": approval, "receipt": receipt, "recorded_at": now()})
        self.save("runtime-authorize")
        return {"authorized_steps": sorted({step for entry in self.data["authorizations"]
                                            for step in entry["approval"]["steps"]})}

    def checked_step(self, name):
        require(name in self.steps, "unknown step")
        return self.steps[name]

    def check_attempt(self, attempt, *, outputs=True, historical=False):
        require("facts" in attempt, "previous Runtime attempt still running or interrupted without disposition")
        facts = attempt["facts"]
        require(digest_value({key: value for key, value in facts.items() if key not in {"step_run_hash", "report"}})
                == facts["step_run_hash"], "Runtime attempt hash mismatch")
        verify_file(facts["report"])
        verify_file(facts["authorization"])
        if facts["retry"]:
            verify_file(facts["retry"]["receipt"])
            if facts["retry"].get("report"):
                verify_file(facts["retry"]["report"])
        if facts.get("interruption"):
            verify_file(facts["interruption"]["receipt"])
        for log in facts["logs"].values():
            verify_file(log)
        if outputs:
            for name, output in facts["outputs"].items():
                self.check_output((facts["step_id"], facts["step_run_hash"], name), output, historical=historical)
        return facts

    def check_output(self, key, output, *, historical):
        expected = self.effective_output(key, output)
        if key in self.requested_losses:
            path = Path(expected["path"])
            require(path.resolve() == path, f"artifact loss path is redirected: {path}")
            try:
                mode = path.stat().st_mode
            except FileNotFoundError:
                observed = None
            else:
                require(stat.S_ISREG(mode), f"artifact loss path is not a regular file: {path}")
                observed = fingerprint(path)
            require(observed is None or expected["sha256"] != observed["sha256"],
                    f"artifact loss requires actual fingerprint change: {path}")
            loss = {"step_id": key[0], "step_run_hash": key[1], "output": key[2],
                    "expected": expected, "observed": observed}
            require(self.observed_losses.setdefault(key, loss) == loss, f"artifact loss changed during verification: {path}")
        elif historical and key in self.retired_losses:
            returned, loss = self.retired_losses[key]
            require(loss["expected"] == expected, "historical artifact loss binding changed")
            audit = next((item for item in self.data["archived_audits"]
                          if item["audit_id"] == returned["decision"]["audit_id"]
                          and item["scope_hash"] == returned["decision"]["scope_hash"]), None)
            require(audit, "historical artifact loss audit is missing")
            verify_audit(audit)
            verify_file(returned["receipt"])
        else:
            verify_file(expected)

    def effective_output(self, key, candidate):
        binding = self.data.get("published", {}).get(key[1], {}).get(key[2])
        if binding is None:
            return candidate
        require(binding["step_id"] == key[0] and binding["candidate"] == candidate,
                "published Runtime result no longer binds the audited attempt")
        result = binding["result"]
        expected = self.published_path(key[2], binding["version"])
        require(Path(result["path"]) == expected and result["sha256"] == candidate["sha256"]
                and result["bytes"] == candidate["bytes"], "published Runtime result binding mismatch")
        return result

    def effective_outputs(self, facts):
        return {name: self.effective_output((facts["step_id"], facts["step_run_hash"], name), candidate)
                for name, candidate in facts["outputs"].items()}

    def passed_step(self, name):
        attempts = self.data["steps"][name]
        require(name not in self.data["reopen"] and attempts and attempts[-1].get("review", {}).get("verdict") == "PASS",
                f"dependency {name} has no passing Runtime Task Review")
        attempt = attempts[-1]
        facts = self.check_attempt(attempt)
        verify_attempt_inputs(facts)
        verify_review(attempt["review"])
        return facts

    def accepted_node(self, node):
        if node in self.previous_nodes:
            return self.previous_nodes[node].accepted_node(node)
        audit = self.data["audits"].get(node)
        require(audit and audit.get("acceptance"), f"milestone {node} not accepted")
        binding = self.scope(node)
        require(binding["scope_hash"] == audit["scope_hash"], f"accepted milestone {node} scope changed")
        verify_audit(audit)
        if self.runtime_root is not None:
            receipt = audit["publication"]
            publication, _ = read_json(receipt["path"])
            require(publication["audit_id"] == audit["audit_id"], "Runtime publication audit binding mismatch")
            for step, attempts in binding["steps"].items():
                facts = attempts[-1]["facts"]
                published = self.data["published"].get(facts["step_run_hash"], {})
                require(publication["outputs"].get(facts["step_run_hash"]) == published
                        and published.keys() == facts["outputs"].keys(), f"Runtime publication is incomplete for {step}")
        return {"audit_id": audit["audit_id"], "run_hash": audit["scope_hash"]}

    def retry_binding(self, args, attempts):
        if not attempts:
            require(not args.evidence, "initial attempt cannot use retry evidence")
            return None
        latest = attempts[-1]
        facts = self.check_attempt(latest, outputs=False)
        review = latest.get("review")
        require(review, "previous attempt needs independent Runtime Task Review")
        require(review["verdict"] != "PASS", "Runtime step already passed")
        require(review["route"] == "Runtime", f"Runtime step routed to {review['route']}")
        require(len(attempts) <= 5, "five repair rounds exhausted; user decision required")
        verify_review(review)
        retry, receipt = self.read_attachment(args.evidence)
        require(retry.get("step_run_hash") == facts["step_run_hash"], "retry evidence does not bind previous attempt")
        text(retry.get("reason"), "retry reason")
        changes = names(retry.get("changes"), "retry changes", nonempty=True)
        require(set(changes) <= RETRY_CONDITIONS, "retry changes require an upstream stage or user decision")
        return {"retry": retry, "receipt": receipt}

    def run(self, args):
        name = args.value
        step = self.checked_step(name)
        actor = text(args.actor, "executor --actor")
        reopen = self.data["reopen"].get(name)
        permission = step_permission(self.data, name)
        require(permission, f"Runtime step {name} not authorized")
        verify_file(permission["receipt"])
        node = step["node"]
        require(node not in self.data["audits"], f"milestone {node} is at its Runtime Audit gate")
        upstream_nodes = {key: self.accepted_node(key) for key in self.nodes[node]["needs"]}
        dependencies = {}
        for key in step["needs"]:
            producer = self.previous_steps.get(key, self)
            facts = producer.passed_step(key)
            dependencies[key] = {"step_run_hash": facts["step_run_hash"], "outputs": producer.effective_outputs(facts)}
        attempts = self.data["steps"][name]
        if reopen:
            require(not args.evidence, "audit repair already supplies approved retry evidence")
            retry = reopen
            verify_file(retry["receipt"])
            if retry.get("report"):
                verify_file(retry["report"])
            require(permission_is_current(permission, reopen), f"Runtime step {name} requires fresh scoped authorization")
            if attempts:
                self.check_attempt(attempts[-1], historical=True)
                verify_review(attempts[-1]["review"])
        else:
            retry = self.retry_binding(args, attempts)
        verify_code(self.root, self.contract["code_commit"])
        executable = self.data["executables"][name]
        verify_file(executable)
        code_files = self.data["code_files"][name]
        for binding in code_files.values():
            verify_file(binding)
        verify_untracked_code(self.root, [*code_files.values(), executable])
        inputs = {key: {**self.contract["inputs"][key], **file_binding(self.root, self.contract["inputs"][key])}
                  for key in step["inputs"]}
        config = file_binding(self.root, step["config"]) if step.get("config") is not None else None
        number = len(attempts) + 1
        tag = f"r{number:02d}"
        log_name = f"scripts/logs/runtime/{self.run_id}/{name}/{tag}"
        log_dir = inside(self.root, log_name, "scripts/logs/runtime")
        require(log_dir == self.root / log_name, "Runtime log path has a redirected parent")
        destinations = {}
        attempt_root = self.runtime_root / "attempts" / name / tag if self.runtime_root else None
        if attempt_root is not None:
            canonically_inside(attempt_root, self.runtime_root / "attempts")
            require(not attempt_root.exists(), "attempt paths already exist; preserve prior Runtime evidence")
        for value in step["outputs"]:
            output = output_name(value)
            if attempt_root is not None:
                destinations[value] = canonically_inside(attempt_root.joinpath(*output.parts), attempt_root)
            else:
                relative = PurePosixPath(*output.parts[:2], self.run_id, name, tag, *output.parts[2:])
                destinations[value] = canonically_inside(self.root.joinpath(*relative.parts), self.root / "results")
        require(not log_dir.exists() and all(not target.exists() for target in destinations.values()),
                "attempt paths already exist; preserve prior Runtime evidence")
        arguments = {"{config}": config["path"]} if config else {}
        arguments.update({"{code:" + key + "}": code_files[key]["path"] for key in step.get("code_inputs", {})})
        arguments.update({"{input:" + key + "}": value["path"] for key, value in inputs.items()})
        arguments.update({"{output:" + key + "}": str(value) for key, value in destinations.items()})
        for prefix in {"results/" + category for category in RESULT_CATEGORIES}:
            if any(value.startswith(prefix + "/") for value in destinations):
                directory = attempt_root / prefix if attempt_root is not None else self.root / prefix / self.run_id / name / tag
                arguments["{output-dir:" + prefix + "}"] = str(directory)
        for source, facts in dependencies.items():
            for key, value in facts["outputs"].items():
                arguments["{upstream:" + source + ":" + key + "}"] = value["path"]
        command = [arguments.get(arg, arg) for arg in step["command"]]
        require(Path(command[0]).resolve() == Path(executable["path"]), "approved executable path changed")
        command[0] = executable["path"]
        start = {
            "run_id": self.run_id, "step_id": name, "node_id": node, "attempt": number, "actor": actor,
            "started_at": now(), "code_commit": self.contract["code_commit"], "cwd": str(self.root),
            "building_audit_id": self.data["building_audit"]["binding"]["audit_id"],
            "contract_sha256": self.data["contract_ref"]["sha256"],
            "authorization": permission["receipt"], "build_plan_sha256": self.contract["build_plan_sha256"],
            "task_id": step["task_id"], "task_spec_sha256": self.contract["task_specs"][step["task_id"]],
            "acs": step["acs"], "inputs": inputs, "config": config, "command": command,
            "resources": step["resources"], "executable": executable, "code_files": code_files,
            "environment": {**self.data["platform_environment"], **step_environment(step, code_files),
                            "PYTHONNOUSERSITE": "1"},
            "output_destinations": {key: str(value) for key, value in destinations.items()},
            "upstream_steps": dependencies,
            "upstream_audits": upstream_nodes, "retry": retry,
        }
        log_dir.mkdir(parents=True, exist_ok=False)
        for target in destinations.values():
            target.parent.mkdir(parents=True, exist_ok=True)
        attempt = {"start": start}
        attempts.append(attempt)
        self.data["reopen"].pop(name, None)
        self.save("runtime-run-start")
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        tick = time.monotonic()
        code, error = None, None
        with stdout.open("xb") as out, stderr.open("xb") as err:
            try:
                process = subprocess.run(command, cwd=self.root, timeout=step["resources"]["timeout_seconds"],
                                         env=start["environment"], stdin=subprocess.DEVNULL,
                                         stdout=out, stderr=err, shell=False, check=False)
                code = process.returncode
            except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                error = type(exc).__name__ + ": " + str(exc)
        evidence_errors = []
        try:
            verify_code(self.root, start["code_commit"])
            verify_untracked_code(self.root, [*code_files.values(), executable])
            for binding in [executable, *code_files.values(), *([config] if config else []), *inputs.values(),
                            *(item for source in dependencies.values() for item in source["outputs"].values())]:
                verify_file(binding)
        except (SystemExit, OSError, subprocess.CalledProcessError) as exc:
            evidence_errors.append(str(exc))
        outputs = {}
        for key, target in destinations.items():
            try:
                if target.is_file() and target.resolve() == target:
                    outputs[key] = fingerprint(target)
            except OSError as exc:
                evidence_errors.append(str(exc))
        facts = {
            **start, "finished_at": now(), "elapsed_seconds": round(time.monotonic() - tick, 6),
            "exit_code": code, "failure": error, "evidence_errors": evidence_errors, "outputs": outputs,
            "all_outputs_present": outputs.keys() == destinations.keys(),
            "logs": {"stdout": fingerprint(stdout), "stderr": fingerprint(stderr)},
            "unmeasured_resources": ["CPU", "memory", "scheduler quotas"],
        }
        return self.finish_attempt(attempt, facts)

    def finish_attempt(self, attempt, facts, *, interrupted=False):
        facts["step_run_hash"] = digest_value(facts)
        node, name, tag = facts["node_id"], facts["step_id"], f"r{facts['attempt']:02d}"
        suffix = "_interrupted" if interrupted else ""
        filename = f"runtime_{node}_{name}_{tag}{suffix}.md"
        report = (self.runtime_file(str(self.runtime_root / "reports" / filename), "reports")
                  if self.runtime_root else inside(self.root, f"audits/runtime/report/{self.run_id}/{filename}",
                                                   "audits/runtime/report"))
        facts["report"] = markdown(report, "Runtime 步骤事实记录", facts)
        attempt["facts"] = facts
        self.save("runtime-run-finish")
        return facts

    def interrupt(self, args):
        name = args.value
        self.checked_step(name)
        attempts = self.data["steps"][name]
        require(attempts and "facts" not in attempts[-1], "no in-progress Runtime attempt to recover")
        attempt = attempts[-1]
        start = attempt["start"]
        evidence, receipt = self.read_attachment(args.evidence)
        for key in ("run_id", "step_id", "attempt", "started_at"):
            require(evidence.get(key) == start[key], f"interruption evidence must bind the current {key}")
        require(evidence.get("confirmed_not_running") is True, "confirm the Runtime process and descendants have stopped")
        text(evidence.get("operator"), "interruption observer")
        reason = text(evidence.get("reason"), "interruption reason")
        observed_at = timestamp(evidence.get("observed_at"))
        require(observed_at > timestamp(start["started_at"]), "interruption observation must follow attempt start")
        tag = f"r{start['attempt']:02d}"
        log_dir = inside(self.root, f"scripts/logs/runtime/{self.run_id}/{name}/{tag}", "scripts/logs/runtime")
        logs = {channel: fingerprint(log_dir / (channel + ".log"))
                for channel in ("stdout", "stderr") if (log_dir / (channel + ".log")).is_file()}
        outputs = {key: fingerprint(Path(value)) for key, value in start["output_destinations"].items()
                   if Path(value).is_file() and Path(value).resolve() == Path(value)}
        facts = {
            **start, "finished_at": now(), "elapsed_seconds": None, "exit_code": None, "failure": reason,
            "all_outputs_present": outputs.keys() == start["output_destinations"].keys(),
            "evidence_errors": ["Interrupted before normal exit status could be recorded"],
            "outputs": outputs, "logs": logs, "interruption": {"evidence": evidence, "receipt": receipt},
        }
        return self.finish_attempt(attempt, facts, interrupted=True)

    def review(self, args):
        name = args.value
        step = self.checked_step(name)
        attempts = self.data["steps"][name]
        require(attempts, "Runtime step has no attempt to review")
        attempt = attempts[-1]
        require("review" not in attempt, "Runtime Task Review already recorded")
        facts = self.check_attempt(attempt)
        review, receipt = self.read_attachment(args.evidence)
        require(review.get("step_run_hash") == facts["step_run_hash"], "Runtime Task Review attempt mismatch")
        reviewer = text(review.get("reviewer"), "step reviewer")
        require(all(reviewer.strip().casefold() != item["start"]["actor"].strip().casefold() for item in attempts),
                "Runtime Task Review must be independent of the step executors")
        verdict = review.get("verdict")
        require(verdict in {"PASS", *FAIL}, "invalid Runtime Task Review verdict")
        acs = objects(review.get("acs"), "Runtime Task Review AC status")
        require(acs.keys() == set(step["acs"]) and all(value in {"PASS", *FAIL} for value in acs.values()),
                "Runtime Task Review must evaluate each approved AC")
        review_route(review, verdict)
        if verdict == "PASS":
            require(facts["exit_code"] == 0 and facts["all_outputs_present"] and not facts["evidence_errors"],
                    "passing Runtime Task Review requires successful execution and intact outputs")
            require(all(value == "PASS" for value in acs.values()), "passing Runtime Task Review requires all ACs to pass")
        report = (self.runtime_file(review.get("report"), "reviews") if self.runtime_root
                  else inside(self.root, review.get("report"), "audits/runtime/task-review"))
        require(report.suffix.lower() == ".md", "Runtime Task Review report must be Markdown")
        report_record = fingerprint(report)
        distinct_file(report_record, [item["facts"]["report"] for item in attempts],
                      "Runtime Task Review")
        report_content = report.read_text(encoding="utf-8")
        markdown_field(report_content, "step_run_hash", facts["step_run_hash"])
        markdown_field(report_content, "verdict", verdict)
        markdown_field(report_content, "return_stage", review["route"] or "none")
        markdown_field(report_content, "ac_statuses", acs, json_value=True)
        attempt["review"] = {**review, "report": report_record, "receipt": receipt}
        self.save("runtime-review")
        return {"step_id": name, **attempt["review"]}

    def scope(self, name):
        if name in self.scopes:
            return self.scopes[name]
        scope = {
            "audit_scope": "final_chain" if name == "final_chain" else "milestone",
            "run_id": self.run_id, "building_audit": self.data["building_audit"]["report"],
            "building_audit_id": self.data["building_audit"]["binding"]["audit_id"],
            "code_commit": self.contract["code_commit"],
            "build_plan_sha256": self.contract["build_plan_sha256"],
            "task_specs": self.contract["task_specs"], "contract_sha256": self.data["contract_ref"]["sha256"],
        }
        if name == "final_chain":
            require(not (self.data.get("next_node") or self.data.get("next_batch")),
                    "final Runtime Audit requires all Building batches or execution nodes")
            scope["nodes"] = [{"node_id": node, **self.accepted_node(node)}
                              for node in [*self.previous_nodes, *self.data["node_order"]]]
            scope["outputs"] = {}
            for step, producer in [*self.previous_steps.items(), *((step, self) for step in self.data["step_order"])]:
                scope["outputs"][step] = producer.effective_outputs(producer.passed_step(step))
        else:
            require(name in self.nodes, "unknown Runtime Audit scope")
            scope["node_id"] = name
            scope["upstream_audits"] = {node: self.accepted_node(node) for node in self.nodes[name]["needs"]}
            scope["steps"] = {}
            for step in self.data["step_order"]:
                if self.steps[step]["node"] != name:
                    continue
                self.passed_step(step)
                attempts = self.data["steps"][step]
                for attempt in attempts:
                    facts = self.check_attempt(attempt, historical=attempt is not attempts[-1])
                    verify_review(attempt["review"])
                    verify_attempt_inputs(facts)
                scope["steps"][step] = attempts
        scope_hash = digest_value(scope)
        scope["scope_hash"] = scope_hash
        scope["chain_hash" if name == "final_chain" else "run_hash"] = scope_hash
        # Audit identity is known before the reviewer writes the formal Markdown.
        scope["audit_id"] = digest_value({"scope_hash": scope_hash, "scope": name, "run_id": self.run_id})
        self.scopes[name] = scope
        return scope

    def audit(self, args):
        name = args.value
        scope = self.scope(name)
        require(name not in self.data["audits"], "Runtime Audit already registered; current user gate is pending or accepted")
        summary = self.node_report(name, scope) if name != "final_chain" else None
        audit, receipt = self.read_attachment(args.evidence)
        require(audit.get("scope_hash") == scope["scope_hash"], "Runtime Audit scope hash mismatch")
        auditor = text(audit.get("auditor"), "independent auditor").strip().casefold()
        relevant = scope.get("steps", self.data["steps"])
        definitions = self.steps
        if name == "final_chain":
            relevant = {**{step: run.data["steps"][step] for step, run in self.previous_steps.items()}, **relevant}
            definitions = {**{step: run.steps[step] for step, run in self.previous_steps.items()}, **definitions}
        require(all(auditor != attempt["start"]["actor"].strip().casefold()
                    for attempts in relevant.values() for attempt in attempts),
                "Runtime Audit must be independent of all executors in scope")
        verdict = audit.get("assessment")
        require(verdict in PASS | FAIL, "invalid Runtime Audit assessment")
        limits = validate_limits(audit)
        review_route(audit, verdict)
        report = formal_audit_path(self.state, self.root, audit.get("report"), "runtime")
        report_record = fingerprint(report)
        earlier_reports = [item["report"] for item in [*self.data["archived_audits"], *self.data["audits"].values()]]
        for run in self.state.get("runtime_history", []):
            earlier_reports.extend(item["report"] for item in [*run["archived_audits"], *run["audits"].values()])
        execution_reports = [record["facts"]["report"] for attempts in relevant.values() for record in attempts]
        step_reviews = [record["review"]["report"] for attempts in relevant.values() for record in attempts]
        distinct_file(report_record, [*earlier_reports, *execution_reports, *step_reviews, *([summary] if summary else [])],
                      "formal Runtime Audit")
        self.verify_report_layout(report, "runtime")
        report_content = report.read_text(encoding="utf-8")
        if self.runtime_root is not None:
            nodes = [node["node_id"] for node in scope["nodes"]] if name == "final_chain" else [name]
            verify_runtime_index(report_content, nodes, {step: definitions[step] for step in relevant})
        if "report_sha256" in audit:
            require(audit["report_sha256"] == report_record["sha256"], "Runtime Audit report fingerprint mismatch")
        else:
            markdown_field(report_content, "chain_hash" if name == "final_chain" else "run_hash", scope["scope_hash"])
            markdown_field(report_content, "accepted_run_hash", "null")
            markdown_field(report_content, "accepted_chain_hash", "null")
        for field, value in [("audit_scope", scope["audit_scope"]), ("runtime_audit_id", scope["audit_id"]),
                             ("runtime_audit_status", verdict), ("audit_user_decision", "pending"),
                             ("return_stage", audit["route"] or "none"), ("accepted_runtime_audit_id", "null")]:
            markdown_field(report_content, field, value)
        markdown_field(report_content, "limitations", limits, json_value=True)
        audit_record = {
            **audit, "audit_id": scope["audit_id"], "audit_scope": scope["audit_scope"], "scope": name,
            "receipt": receipt, "report": report_record, "limitations": limits, "registered_at": now(),
            "summary": summary,
        }
        self.data["audits"][name] = audit_record
        self.save("runtime-audit")
        return audit_record

    def node_report(self, name, scope):
        prior = self.data["reports"].get(name, [])
        require(prior and prior[-1]["scope_hash"] == scope["scope_hash"],
                f"generate current Runtime Report before audit for {name}")
        report = prior[-1]["report"]
        verify_file(report)
        return report

    def report(self, args):
        name = args.value
        require(name in self.nodes, "Runtime Report requires a milestone node ID")
        scope = self.scope(name)
        reports = self.data["reports"].setdefault(name, [])
        if reports and reports[-1]["scope_hash"] == scope["scope_hash"]:
            return self.node_report(name, scope)
        filename = f"runtime_{name}_{len(reports) + 1:02d}.md"
        summary = (self.runtime_file(str(self.runtime_root / "reports" / filename), "reports")
                   if self.runtime_root else inside(self.root, f"audits/runtime/report/{self.run_id}/{filename}",
                                                    "audits/runtime/report"))
        report = markdown(summary, "Runtime 节点事实汇总", scope)
        reports.append({"scope_hash": scope["scope_hash"], "report": report})
        self.save("runtime-report")
        return report

    def accept(self, args):
        name = args.value
        audit = self.data["audits"].get(name)
        require(audit and not audit.get("acceptance"), "current Runtime Audit is missing or already accepted")
        acceptance, receipt = self.read_attachment(args.evidence)
        scope = self.scope(name)
        if name != "final_chain":
            self.node_report(name, scope)
        require(audit["assessment"] in PASS, "current Runtime Audit assessment requires a return decision")
        require(acceptance.get("audit_id") == audit["audit_id"] and acceptance.get("scope_hash") == audit["scope_hash"]
                and scope["scope_hash"] == audit["scope_hash"], "Runtime Audit acceptance scope mismatch")
        require(acceptance.get("accepted_limitations") == audit["limitations"], "audit limitations require explicit acceptance")
        user_message = text(acceptance.get("user_message_ref"), "user acceptance message reference")
        require_fresh_batch_message_ref(self.state, execution_scope_id(self.data), user_message,
                                        "Runtime Audit acceptance")
        require(all(user_message != item.get("acceptance", {}).get("user_message_ref")
                    for item in [*self.data["audits"].values(), *self.data["archived_audits"]]),
                "each Runtime Audit requires its own user decision")
        require(all(user_message != run.data["audits"][node]["acceptance"]["user_message_ref"]
                    for node, run in self.previous_nodes.items()),
                "each Runtime Audit requires its own user decision")
        require(timestamp(acceptance.get("accepted_at")) > timestamp(audit["registered_at"]),
                "Runtime Audit acceptance must be after formal report registration")
        verify_audit(audit)
        record = {**acceptance, "receipt": receipt}
        if self.runtime_root is not None and name != "final_chain":
            self.publish(audit, scope, record)
        else:
            audit["acceptance"] = record
            self.save("runtime-accept")
        return {"audit_id": audit["audit_id"], "scope_hash": audit["scope_hash"], "audit_user_decision": "accepted"}

    def published_path(self, logical, version):
        output = output_name(logical)
        require(re.fullmatch(re.escape(self.run_id) + r"(?:-r[0-9]{2,})?", version), "invalid Runtime result version")
        return canonically_inside(self.root.joinpath(*output.parts[:2], version, *output.parts[2:]),
                                  self.root / "results")

    def version_owned(self, version, known_paths):
        for category in RESULT_CATEGORIES:
            directory = self.root / "results" / category / version
            canonically_inside(directory, self.root / "results")
            if directory.exists() and not directory.is_dir():
                return False
            for path in directory.rglob("*"):
                if path.resolve() != path or (not path.is_dir() and str(path).casefold() not in known_paths):
                    return False
        return True

    def publish(self, audit, scope, acceptance):
        published = self.data["published"]
        owned = {entry["result"]["path"].casefold() for outputs in published.values() for entry in outputs.values()}
        candidates = {items[-1]["facts"]["step_run_hash"]: items[-1]["facts"] for items in scope["steps"].values()}
        fresh = {key: value for key, value in candidates.items() if key not in published}
        logical_names = [logical for facts in fresh.values() for logical in facts["outputs"]]
        filename = f"publication-{audit['audit_id']}.json"
        intent = self.runtime_file(str(self.runtime_root / "evidence" / filename), "evidence")
        interrupted = intent.exists()
        prior = read_json(str(intent))[0] if interrupted else None
        version = self.run_id

        def destinations(target_version):
            return {str(self.published_path(logical, target_version)).casefold() for logical in logical_names}

        if interrupted and fresh:
            versions = {entry["version"] for key in fresh for entry in prior["outputs"][key].values()}
            require(len(versions) == 1, "pending Runtime publication has conflicting versions")
            version = versions.pop()
        elif destinations(version) & owned:
            revision = 2
            while True:
                version = f"{self.run_id}-r{revision:02d}"
                if not (destinations(version) & owned) and self.version_owned(version, owned):
                    break
                revision += 1
        known_paths = owned | (destinations(version) if interrupted else set())
        require(not (destinations(version) & owned) and self.version_owned(version, known_paths),
                f"published Runtime run version already exists or contains foreign results: {version}")

        additions = {}
        for attempt_hash, facts in fresh.items():
            additions[attempt_hash] = {
                logical: {"step_id": facts["step_id"], "version": version, "candidate": candidate,
                          "result": {**candidate, "path": str(self.published_path(logical, version))}}
                for logical, candidate in facts["outputs"].items()
            }
        record = {"audit_id": audit["audit_id"], "outputs": {key: (published | additions)[key] for key in candidates}}
        if interrupted:
            require(prior == record, "pending Runtime publication intent differs from audited outputs")

        links = []
        for outputs in additions.values():
            for entry in outputs.values():
                candidate = entry["candidate"]
                verify_file(candidate)
                source = Path(candidate["path"])
                target = Path(entry["result"]["path"])
                if target.exists():
                    require(interrupted and target.is_file() and target.samefile(source),
                            f"published Runtime result already exists: {target}")
                require(not any(parent.exists() and not parent.is_dir()
                                for parent in target.parents if parent.is_relative_to(self.root)),
                        f"published Runtime result parent is blocked: {target}")
                links.append((source, target, entry["result"]))

        if not interrupted:
            intent.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=intent.parent, delete=False) as handle:
                temporary = Path(handle.name)
                try:
                    json.dump(record, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                except BaseException:
                    handle.close()
                    temporary.unlink()
                    raise
            try:
                os.link(temporary, intent)
            finally:
                temporary.unlink()

        created = []
        try:
            for source, target, binding in links:
                target.parent.mkdir(parents=True, exist_ok=True)
                canonically_inside(target, self.root / "results")
                if not target.exists() or not interrupted:
                    os.link(source, target)
                created.append((source, target))
                require(target.samefile(source), f"Runtime publication target changed: {target}")
                verify_file(binding)
            audit["publication"] = fingerprint(intent)
            audit["acceptance"] = acceptance
            published.update(additions)
            self.save("runtime-accept")
        except BaseException:
            persisted = read_json(str(self.state_path))[0].get("runtime", {}).get("audits", {}).get(scope["node_id"], {})
            if persisted.get("acceptance") != acceptance:
                audit.pop("publication", None)
                audit.pop("acceptance", None)
                for key in additions:
                    published.pop(key, None)
                for source, target in reversed(created):
                    if target.exists() and target.samefile(source):
                        target.unlink()
                if not interrupted:
                    intent.unlink()
            raise

    def invalidation_closure(self, selected):
        affected = set(selected)
        for step in self.data["step_order"]:
            if affected.intersection(self.steps[step]["needs"]):
                affected.add(step)
        invalidated_nodes = {self.steps[step]["node"] for step in affected}
        for node in self.data["node_order"]:
            if invalidated_nodes.intersection(self.nodes[node]["needs"]):
                invalidated_nodes.add(node)
        return affected, {"final_chain", *invalidated_nodes}

    def reopen_steps(self, name, decision, receipt, *, report=None):
        changes = names(decision.get("changes"), "Runtime-only repair changes", nonempty=True)
        require(set(changes) <= RETRY_CONDITIONS, "repair changes require an upstream stage or user decision")
        selected = set(names(decision.get("steps"), "repair steps", nonempty=True))
        immediate = selected & {step for step, spec in self.steps.items()
                                if name == "final_chain" or spec["node"] == name}
        recover_loss = bool(self.requested_losses)
        require(recover_loss or selected == immediate, "repair steps exceed the Runtime Audit scope")
        affected, invalidated = self.invalidation_closure(selected)
        audits = self.data["audits"]
        if recover_loss:
            require(all(audit.get("acceptance") or scope in invalidated for scope, audit in audits.items()),
                    "formal Runtime Audit gate is outside the artifact loss scope")
        if report or recover_loss:
            require(all(len(self.data["steps"][step]) <= 5 for step in affected),
                    "five repair rounds exhausted; user decision required")
        if report is None:
            require(decision.get("rerun_authorized") is True, "formal Runtime return requires explicit scoped rerun authorization")
        recorded_at = now()
        for step in affected:
            self.data["reopen"][step] = {
                "decision": decision, "receipt": receipt, "report": report, "recorded_at": recorded_at,
                "is_user_authorized": report is None and step in immediate,
                "requires_fresh_authorization": report is None and step not in immediate,
            }
        for scope in sorted(invalidated & audits.keys()):
            self.data["archived_audits"].append(audits.pop(scope))
        return {"affected_steps": sorted(affected), "invalidated_scopes": sorted(invalidated)}

    def audit_repair(self, args):
        name = args.value
        require(name not in self.data["audits"], "formal Runtime Audit already registered; user return decision required")
        require(name not in self.data["audit_repairs"], "one consolidated pre-audit repair already recorded")
        scope = self.scope(name)
        if name != "final_chain":
            self.node_report(name, scope)
        decision, receipt = self.read_attachment(args.evidence)
        require(decision.get("scope_hash") == scope["scope_hash"] and decision.get("route") == "Runtime",
                "draft repair must bind the current scope and remain in Runtime")
        reviewer = text(decision.get("auditor"), "independent draft auditor").strip().casefold()
        relevant = scope.get("steps", self.data["steps"])
        if name == "final_chain":
            relevant = {**{step: run.data["steps"][step] for step, run in self.previous_steps.items()}, **relevant}
        require(all(reviewer != attempt["start"]["actor"].strip().casefold()
                    for attempts in relevant.values() for attempt in attempts),
                "draft Runtime Audit must be independent of executors")
        text(decision.get("reason"), "draft repair reason")
        report = (self.runtime_file(decision.get("report"), "reviews") if self.runtime_root
                  else inside(self.root, decision.get("report"), ".tmp/runtime"))
        require(scope["scope_hash"] in report.read_text(encoding="utf-8"), "draft repair report scope mismatch")
        report_record = fingerprint(report)
        execution_records = [attempt["facts"]["report"] for attempts in relevant.values() for attempt in attempts]
        distinct_file(report_record, execution_records, "draft Runtime Audit")
        result = self.reopen_steps(name, decision, receipt, report=report_record)
        self.data["audit_repairs"][name] = {"decision": decision, "receipt": receipt, "report": report_record, **result}
        self.save("runtime-audit-repair")
        return result

    def bind_artifact_loss(self, name, decision):
        if decision["route"] == "Runtime":
            require(decision.get("rerun_authorized") is True,
                    "artifact loss recovery requires explicit scoped rerun authorization")
        require(not self.data.get("finish"), "finished Runtime cannot invalidate audited output")
        verify_code(self.root, self.contract["code_commit"])
        selected = set(names(decision.get("steps"), "repair steps", nonempty=True))
        require(selected <= self.steps.keys(), "artifact loss selects an unknown step")
        anchor_steps = {step for step in selected if name == "final_chain" or self.steps[step]["node"] == name}
        require(anchor_steps, "artifact loss must select a producing step in the current Runtime Audit scope")
        _, invalidated = self.invalidation_closure(anchor_steps)
        losses = decision["artifact_loss"]
        require(isinstance(losses, list) and losses, "artifact loss requires a nonempty bound output list")
        for loss in losses:
            require(isinstance(loss, dict) and loss.keys() == {"step_id", "step_run_hash", "output"},
                    "artifact loss must identify the step, attempt hash and logical output")
            step = matches(loss["step_id"], ID, "artifact loss step")
            attempt_hash = matches(loss["step_run_hash"], SHA256, "artifact loss attempt hash")
            output = text(loss["output"], "artifact loss output")
            require(step in selected, "artifact loss exceeds selected steps")
            if step not in anchor_steps:
                node = self.steps[step]["node"]
                require(node in invalidated, "artifact loss exceeds the Runtime Audit invalidation closure")
                audit = self.data["audits"].get(node)
                require(audit, "downstream artifact loss requires a current Runtime Audit")
                acceptance = audit.get("acceptance")
                gate_at = acceptance["accepted_at"] if acceptance else audit["registered_at"]
                decided_at = timestamp(decision["decided_at"])
                require(decided_at > timestamp(gate_at),
                        "artifact loss decision must follow the downstream Runtime Audit gate")
                require(not acceptance or decision["user_message_ref"] != acceptance["user_message_ref"],
                        "artifact loss recovery requires a separate user decision")
            facts = next((item.get("facts", {}) for item in self.data["steps"][step]
                          if item.get("facts", {}).get("step_run_hash") == attempt_hash), None)
            require(facts and output in facts["outputs"], "artifact loss does not bind an existing attempt output")
            key = (step, attempt_hash, output)
            require(key not in self.requested_losses and key not in self.retired_losses,
                    "duplicate or previously invalidated artifact loss")
            self.requested_losses.add(key)
        require(selected == {step for step, _, _ in self.requested_losses},
                "artifact loss recovery must select exactly the steps with lost outputs")

    def verify_artifact_loss_scopes(self):
        for scope, audit in self.data["audits"].items():
            verify_audit(audit)
            require(self.scope(scope)["scope_hash"] == audit["scope_hash"],
                    f"artifact loss recovery Runtime Audit scope changed: {scope}")

    def return_stage(self, args):
        name = args.value
        decision, receipt = self.read_attachment(args.evidence)
        route = decision.get("route")
        require(route in ROUTES, "invalid return route")
        text(decision.get("reason"), "return reason")
        user_message = text(decision.get("user_message_ref"), "separate user decision message reference")
        require_fresh_batch_message_ref(self.state, execution_scope_id(self.data), user_message,
                                        "Runtime return decision")
        require(all(user_message != item["decision"]["user_message_ref"] for item in self.data["return_decisions"]),
                "Runtime return user message already recorded")
        decided_at = timestamp(decision.get("decided_at"))
        recover_loss = "artifact_loss" in decision
        resolving_hold = self.data.get("return_stage") == "Decision"
        if resolving_hold:
            held = self.data["return_decisions"][-1]
            require(name == held["scope"] and route in {"Building", "Proposal"},
                    "resolve the held Runtime scope with a Building or Proposal decision")
            require(all(held["decision"].get(key) == decision.get(key)
                        for key in ("step_run_hash", "audit_id", "scope_hash")),
                    "resolution must bind the held Runtime evidence")
            verify_file(held["receipt"])
            require(decided_at > timestamp(held["decision"]["decided_at"]), "resolution must follow the held decision")
            if recover_loss:
                require(decision["artifact_loss"] == held["decision"].get("artifact_loss"),
                        "resolution must bind the held artifact loss")
        if name in self.steps:
            require(not recover_loss, "artifact loss recovery requires a registered Runtime Audit")
            attempts = self.data["steps"][name]
            require(attempts and attempts[-1].get("review", {}).get("verdict") in FAIL,
                    "step return requires a failed Runtime Task Review")
            attempt = attempts[-1]
            facts = self.check_attempt(attempt, outputs=False)
            verify_review(attempt["review"])
            require(facts["step_run_hash"] == decision.get("step_run_hash"), "return attempt hash mismatch")
            limit = len(attempts) > 5 and attempt["review"]["route"] == "Runtime"
            require(route in {"Building", "Proposal", "Decision"} and
                    (route == attempt["review"]["route"] or limit or attempt["review"]["route"] == "Decision"),
                    "step return must follow the current review route or exhausted repair limit")
            require(decided_at > timestamp(facts["finished_at"]), "return decision must follow the current attempt")
        else:
            audit = self.data["audits"].get(name)
            require(audit and (recover_loss or resolving_hold or not audit.get("acceptance")),
                    "return requires a current unaccepted Runtime Audit")
            require(audit["audit_id"] == decision.get("audit_id") and audit["scope_hash"] == decision.get("scope_hash"),
                    "return decision audit scope mismatch")
            require(audit["route"] in {None, route, "Decision"} or route == "Decision" or resolving_hold,
                    "return decision must follow the current Runtime Audit route")
            require(decided_at > timestamp(audit["registered_at"]), "return decision must follow formal audit registration")
            verify_audit(audit)
            if recover_loss:
                if audit.get("acceptance"):
                    require(decided_at > timestamp(audit["acceptance"]["accepted_at"]),
                            "artifact loss decision must follow audit acceptance")
                    require(user_message != audit["acceptance"]["user_message_ref"],
                            "artifact loss recovery requires a separate user decision")
                self.bind_artifact_loss(name, decision)
                self.verify_artifact_loss_scopes()
            else:
                current_scope = self.scope(name)
                require(current_scope["scope_hash"] == audit["scope_hash"], "return decision audit scope mismatch")
            require(self.requested_losses == self.observed_losses.keys(),
                    "artifact loss output was outside the reverified Runtime Audit scope")
        result = self.reopen_steps(name, decision, receipt) if route == "Runtime" else {}
        if recover_loss:
            result["artifact_losses"] = [self.observed_losses[key] for key in sorted(self.observed_losses)]
        self.data["return_decisions"].append({"scope": name, "decision": decision, "receipt": receipt, **result})
        if route != "Runtime":
            self.data["return_stage"] = route
        self.save("runtime-return")
        return {"route": route, **result}

    def finish(self, args):
        audit = self.data["audits"].get("final_chain")
        require(audit and audit.get("acceptance"), "final Runtime Audit not accepted")
        require("finish" not in self.data, "Runtime Finish already recorded")
        scope = self.scope("final_chain")
        require(scope["scope_hash"] == audit["scope_hash"], "accepted Runtime chain changed")
        verify_audit(audit)
        report = inside(self.root, args.artifact, "reports")
        require(report.suffix.lower() == ".md", "Runtime Finish must be Markdown")
        content = report.read_text(encoding="utf-8")
        lines = list(markdown_lines_outside_code(content.splitlines()))
        headings = [(index, line.strip()) for index, line in enumerate(lines) if re.match(r" {0,3}#{1,6}[ \t]+", line)]
        if headings and headings[0][1].startswith("# "):
            headings = headings[1:]
        current_layout = [heading for _, heading in headings] == ["## 阶段性结果", "## 结果局限"]
        if self.runtime_root is not None or current_layout:
            require(current_layout, "Runtime Finish requires exactly the sections 阶段性结果 and 结果局限")
            first, second = [index for index, _ in headings]
            require(any(line.strip() for line in lines[first + 1:second]) and any(line.strip() for line in lines[second + 1:]),
                    "Runtime Finish sections require a result and its limitations")
        else:
            headings = ["## 当前状态与追溯", "## 结果概览", "## 已审结果清单", "## 关键发现与限制", "## 复现与交付核对"]
            require(all(heading in content for heading in headings), "Runtime Finish must follow the approved template")
            require(scope["scope_hash"] in content and audit["audit_id"] in content,
                    "Runtime Finish must identify the accepted chain_hash and runtime_audit_id")
            for identity in scope["nodes"]:
                require(identity["run_hash"] in content, "Runtime Finish must identify each accepted milestone run_hash")
        if self.runtime_root is None:
            delivery = "\n".join(lines) if current_layout else content
            require(audit["audit_id"] in delivery, "Runtime Finish must identify the accepted runtime_audit_id")
            for identity in scope["nodes"]:
                require(identity["audit_id"] in delivery, "Runtime Finish must identify each accepted milestone audit")
            for outputs in scope["outputs"].values():
                for output in outputs.values():
                    require(output["path"] in delivery or Path(output["path"]).as_posix() in delivery,
                            "Runtime Finish must link each audited output")
        result = {
            "run_id": self.run_id, "chain_hash": scope["scope_hash"], "final_audit_id": audit["audit_id"],
            "node_audits": scope["nodes"], "result_manifest": scope["outputs"],
            "limitations": {**{node: run.data["audits"][node]["limitations"] for node, run in self.previous_nodes.items()},
                            **{name: binding["limitations"] for name, binding in self.data["audits"].items()}},
        }
        self.data["finish"] = fingerprint(report)
        if self.runtime_root is not None:
            self.data["finish_results"] = result
        self.save("runtime-finish")
        return {"status": "runtime_finished", "report": self.data["finish"], **result}

    def status(self):
        return self.data


def dispatch(args, state, save, verify_report_layout, *, state_path=None):
    runtime = Runtime(state, save, verify_report_layout, state_path=state_path)
    try:
        if args.action != "runtime-status":
            runtime.verify_completed_batches()
        if args.action == "runtime-init":
            return runtime.initialize(args)
        require(runtime.data, "Runtime has not been initialized")
        require(args.action in {"runtime-status", "runtime-return"} or not runtime.data.get("return_stage"),
                "Runtime is on return-stage hold")
        handlers = {
            "runtime-authorize": runtime.authorize, "runtime-run": runtime.run, "runtime-review": runtime.review,
            "runtime-report": runtime.report,
            "runtime-scope": lambda args: runtime.scope(args.value), "runtime-audit": runtime.audit,
            "runtime-accept": runtime.accept, "runtime-audit-repair": runtime.audit_repair, "runtime-return": runtime.return_stage,
            "runtime-interrupt": runtime.interrupt,
            "runtime-next-batch": runtime.next_batch, "runtime-next-node": runtime.next_batch,
            "runtime-finish": runtime.finish, "runtime-status": lambda args: runtime.status(),
        }
        if args.action != "runtime-status":
            for record in (runtime.data["contract_ref"], runtime.data["building_audit"]["receipt"]):
                runtime.attachment_path(record["path"])
                verify_file(record)
            verify_building_gate(state.get("building_gate"), state, runtime.root, runtime.contract["code_commit"])
        pending = {name for name, audit in runtime.data["audits"].items() if not audit.get("acceptance")}
        if pending:
            accepted_scope = runtime.data["audits"].get(args.value, {}).get("acceptance")
            require(args.action in {"runtime-status", "runtime-scope"} or
                    (args.action in {"runtime-accept", "runtime-return"} and args.value in pending) or
                    (args.action == "runtime-return" and accepted_scope),
                    "formal Runtime Audit is at its Runtime Audit gate; user decision required")
        if args.action in {"runtime-authorize", "runtime-report", "runtime-scope", "runtime-audit", "runtime-accept",
                           "runtime-audit-repair", "runtime-finish", "runtime-next-batch", "runtime-next-node"}:
            verify_code(runtime.root, runtime.contract["code_commit"])
        return handlers[args.action](args)
    except subprocess.CalledProcessError as error:
        raise SystemExit("Git worktree verification failed: " + str(error.stderr).strip()) from None


def project(data):
    """Project the next coordinator stage from the independent step and audit records."""
    if data.get("finish"):
        return "runtime_finished"
    if data.get("return_stage"):
        return {"Building": "building_incomplete", "Proposal": "proposal",
                "Decision": "user_decision_pending"}[data["return_stage"]]
    audits = data["audits"]
    final = audits.get("final_chain")
    if final:
        return "runtime_finish_pending" if final.get("acceptance") else "final_chain_audit_gate"
    if all(audits.get(node, {}).get("acceptance") for node in data["node_order"]):
        if data.get("next_node"):
            return "node_complete_pending"
        return "batch_complete_pending" if data.get("next_batch") else "final_chain_audit_pending"
    if any(not audit.get("acceptance") for audit in audits.values()):
        return "milestone_audit_gate"
    attempts = data["steps"]
    contract = data["contract"]
    passed = {step for step, runs in attempts.items()
              if step not in data["reopen"] and runs and runs[-1].get("review", {}).get("verdict") == "PASS"}
    if any(not audits.get(node) and all(step in passed for step, spec in contract["steps"].items() if spec["node"] == node)
           for node in data["node_order"]):
        return "milestone_audit_pending"
    if any(runs and "review" not in runs[-1] for runs in attempts.values()):
        return "runtime_step_review_pending"
    if any(runs and runs[-1]["review"]["verdict"] != "PASS" for runs in attempts.values()):
        return "runtime_fix_pending"
    authorized = {step for step in attempts if permission_is_current(step_permission(data, step), data["reopen"].get(step))}
    if not any(step in authorized and step not in passed for step in attempts):
        return "runtime_authorization_pending"
    return "runtime_step_pending" if passed else "runtime_authorized"
