"""Validate the structured Proposal and its Git-scoped Building evidence."""

from pathlib import Path, PurePosixPath
import re

from runtime_harness import graph_order, markdown_lines_outside_code, plan_ids
import sdd_unit_git as unit_git


MARKER = "- path_schema: 1"
ENTRY_HEADER = "| 任务 ID | 主入口路径 | 变更（新增／既有／迁移） |"
RESULT_HEADER = "| 输出 ID | 输出名称 | 逻辑路径 | 内容与用途 | 生成阶段 | 验收依据 |"
TASK_HEADER = "| 任务 ID | Task MD | 目的与边界 | 前置任务／产物 | 相关 AC |"
AC_HEADER = "| AC ID（完整任务 ID + -ACNN） | 验收目标 | 可观察的成功条件 | 验证方式 | 验证阶段 | 当前状态 |"
STEPS_HEADER = "| 运行步骤 ID | 对应任务 | 前置步骤或节点 | 输入与输出 | 可并行步骤／互斥条件 | 完成检查 |"
NODES_HEADER = "| 节点 ID | 节点目的 | 包含的运行步骤 | 前置节点 | 阶段性成果与验收条件 | 用户授权范围 |"
BATCH_NODES_HEADER = ("| 节点 ID | 节点目的 | 建设批次 | 前置建设要求 | 包含的运行步骤 | "
                      "Runtime 前置节点 | 阶段性成果与验收条件 |")
SCOPED_NODES_HEADER = ("| 节点 ID | 节点目的 | 前置建设要求 | 包含的 Task | "
                       "包含的运行步骤 | 阶段性成果与验收条件 |")
AUDIT_HEADER = "| 任务 ID | 任务目的 | AC ID | 成功条件 | 完成情况与验证范围 |"
TASK_ID = r"T\d+(?:-EXT\d+)?"
SCRIPT_SUFFIXES = {
    ".awk", ".bash", ".bat", ".cmd", ".jl", ".m", ".ps1", ".py", ".pyw", ".r", ".rmd",
    ".sbatch", ".sh", ".sql", ".zsh", ".ipynb", ".pl", ".rb", ".js", ".ts",
    ".ado", ".c", ".cpp", ".do", ".f90", ".go", ".groovy", ".rs", ".sas", ".scala", ".sps",
}
ANCILLARY = {"config", "pytest", "smoke_test", "logs"}
RESERVED = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", re.IGNORECASE)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def document_lines(content):
    return list(markdown_lines_outside_code(content.splitlines(), preserve_hidden_boundaries=True))


def section(content, heading):
    lines = document_lines(content)
    positions = [index for index, line in enumerate(lines) if line.strip() == heading]
    require(len(positions) == 1, f"expected one Markdown section {heading}")
    start = positions[0] + 1
    level = len(heading.split()[0])
    end = next((index for index in range(start, len(lines))
                if re.match(r" {0,3}#{1," + str(level) + r"}[ \t]", lines[index])), len(lines))
    return lines[start:end]


def structured_plan(content):
    markers = [line.strip() for line in document_lines(content)
               if re.match(r"^\s*-\s+path_schema\s*[:：]", line)]
    if not markers:
        return False
    require(markers == [MARKER] and MARKER in section(content, "## 项目目录结构"),
            "Build Plan requires one '- path_schema: 1' in 项目目录结构")
    return True


def split_row(line):
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip()[1:-1])]


def table(content, heading, header, *, label=None, allow_empty=False, require_block_break=False):
    lines = section(content, heading)
    positions = [index for index, line in enumerate(lines) if line.strip() == header]
    label = label or heading
    require(len(positions) == 1, f"expected one {label} table with the approved header")
    if require_block_break:
        require(positions[0] == 0 or not lines[positions[0] - 1].strip(),
                f"{label} table must follow a blank line or the section heading")
    start = positions[0] + 1
    columns = len(split_row(header))
    body = []
    for line in lines[start:]:
        if not line.strip().startswith("|"):
            break
        require(line.strip().endswith("|"), f"invalid {label} row: {line}")
        cells = split_row(line)
        require(len(cells) == columns, f"invalid {label} row: {line}")
        body.append(cells)
    require(body and all(re.fullmatch(r":?-{3,}:?", cell) for cell in body[0]),
            f"invalid {label} table separator")
    require(allow_empty or len(body) > 1, f"missing {label} rows")
    return body[1:]


def unique(rows, label):
    mapping = {}
    for identifier, *values in rows:
        require(identifier and identifier not in mapping, f"empty or duplicate {label}: {identifier}")
        mapping[identifier] = values
    return mapping


def relative(value, label):
    path = PurePosixPath(value)
    require(path.as_posix() == value and path.parts and
            all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part)
                and not part.endswith(".") and not RESERVED.fullmatch(part) for part in path.parts),
            f"invalid {label}: {value}")
    return path


def in_build(path):
    return len(path.parts) >= 3 and path.parts[:2] == ("scripts", "build")


def no_path_collisions(paths, label):
    folded = [PurePosixPath(path.casefold()) for path in paths]
    path_set = set(folded)
    require(len(folded) == len(path_set) and not any(parent in path_set for path in folded for parent in path.parents),
            f"duplicate or overlapping {label}")


def field(lines, name):
    values = [match[1].strip() for line in lines if (match := re.fullmatch(
        r" {0,3}- " + re.escape(name) + r"：(.*)", line))]
    require(len(values) == 1 and values[0], f"Task MD must declare one nonempty {name}")
    return values[0]


def task_entry_paths(content):
    lines = section(content, "## 输入、脚本与输出")
    values = [match[1].strip() for line in lines if (match := re.fullmatch(r" {0,3}- 主入口路径：(.*)", line))]
    if values == ["无"]:
        return set()
    paths = []
    for value in values:
        match = re.fullmatch(r"\x60([^\x60]+)\x60", value)
        require(match, "Task MD main entry path must use backticks or declare 无")
        paths.append(relative(match[1], "main entry path").as_posix())
    require(paths, "Task MD requires a main entry path or 无")
    no_path_collisions(paths, "main entry path")
    return set(paths)


def task_spec_path(plan_path, link, unit):
    match = re.fullmatch(r"\[[^\[\]]+\]\(([^()]+)\)", link)
    require(match, f"expected a relative Task MD link: {link}")
    path = relative(match[1], "Task MD path")
    require(path.parts[0] == "tasks" and path.suffix == ".md", f"invalid Task MD path: {link}")
    task = plan_path.parent.joinpath(*path.parts)
    require(unit_git.inside(task, unit, "Task MD", unit_paths=True) == task and task.is_file(),
            f"Task MD must be an existing file without aliases: {task}")
    unit_git.reject_hardlink(task)
    return task


def accepted_prerequisites(preparation, node):
    if preparation in {"无", "—", "-", "none"}:
        return set()
    rule = re.fullmatch(r"(.+?)[ \t]*已验收(?:[。；;].*)?", preparation)
    require(rule, f"Building prerequisites for {node} must name accepted nodes")
    needs = plan_ids(rule[1])
    require(needs, f"Building prerequisites for {node} must name accepted nodes")
    return needs


def node_plan(rows, steps, task_rows):
    nodes, scopes, task_nodes, step_nodes = {}, {}, {}, {}
    for node, (_, preparation, task_cell, members, _) in rows.items():
        require(re.fullmatch(r"N[0-9]{2,}", node) and int(node[1:]) > 0, f"invalid Runtime node: {node}")
        needs = accepted_prerequisites(preparation, node)
        tasks, member_steps = plan_ids(task_cell), plan_ids(members)
        require(tasks and tasks <= task_rows.keys(), f"unknown or empty Task scope for {node}")
        require(member_steps and member_steps <= steps.keys(), f"unknown or empty Runtime steps for {node}")
        for task in tasks:
            require(task not in task_nodes, f"duplicate Task {task} in node scope")
            task_nodes[task] = node
        for step in member_steps:
            require(step not in step_nodes, f"duplicate Runtime step {step} in node scope")
            require(steps[step]["task"] in tasks, f"Runtime step {step} requires its Task in {node}")
            step_nodes[step] = node
        nodes[node] = {"batch": node, "build_needs": needs, "needs": needs, "steps": member_steps}
        scopes[node] = {"tasks": tasks, "nodes": {node}, "steps": member_steps, "needs": needs}
    ordered = sorted(nodes, key=lambda node: int(node[1:]))
    ranks = {node: int(node[1:]) for node in ordered}
    require(len(set(ranks.values())) == len(ranks), "duplicate Runtime node number")
    require(task_nodes.keys() == task_rows.keys(), "each Build Task must belong to exactly one node")
    require(step_nodes.keys() == steps.keys(), "each Runtime step must belong to exactly one node")
    for node, info in nodes.items():
        for prior in info["needs"]:
            require(prior in ranks and ranks[prior] < ranks[node],
                    f"prerequisite node {prior} must be earlier than {node}")

    def require_prerequisite(node, prior, source):
        require(prior in nodes, f"unknown prerequisite node {prior} for {source}")
        require(prior == node or prior in nodes[node]["needs"],
                f"{source} has undeclared prerequisite node {prior}")

    for task, values in task_rows.items():
        for prior in plan_ids(values[2]) & task_nodes.keys():
            require_prerequisite(task_nodes[task], task_nodes[prior], f"Task {task}")
    for step, spec in steps.items():
        for prior in spec["needs"]:
            require_prerequisite(step_nodes[step], step_nodes.get(prior, prior), f"Runtime step {step}")
    return {"scope_key": "node_id", "node_header": SCOPED_NODES_HEADER, "nodes": nodes,
            "steps": steps, "batches": {node: scopes[node] for node in ordered}}


def batch_plan(content):
    heading = "## 阶段性验收节点"
    headers = {line.strip() for line in section(content, heading)}
    require(len(headers & {SCOPED_NODES_HEADER, BATCH_NODES_HEADER, NODES_HEADER}) <= 1,
            "Build Plan must use only one acceptance node table format")
    scoped_nodes = SCOPED_NODES_HEADER in headers
    header = SCOPED_NODES_HEADER if scoped_nodes else BATCH_NODES_HEADER
    if header not in headers:
        return None
    rows = unique(table(content, heading, header), "Runtime node ID")
    step_rows = unique(table(content, "## Runtime 执行图", STEPS_HEADER), "Runtime step ID")
    task_rows = unique(table(content, "## 任务清单", TASK_HEADER), "task ID")
    steps = {key: {"task": task, "needs": plan_ids(needs)}
             for key, (task, needs, *_rest) in step_rows.items()}
    if scoped_nodes:
        return node_plan(rows, steps, task_rows)
    nodes = {}
    batches = {}
    for node, (_, batch, preparation, members, needs, _) in rows.items():
        batch = batch.strip("`")
        require(re.fullmatch(r"B[0-9]{2,}", batch) and int(batch[1:]) > 0,
                f"invalid Building batch ID for {node}: {batch}")
        build_needs = accepted_prerequisites(preparation, node)
        nodes[node] = {"batch": batch, "build_needs": build_needs,
                       "needs": plan_ids(needs), "steps": plan_ids(members)}
        scope = batches.setdefault(batch, {"tasks": set(), "nodes": set(), "steps": set(), "needs": set()})
        scope["nodes"].add(node)
        scope["steps"].update(nodes[node]["steps"])
        scope["needs"].update(build_needs)
    batch_order = sorted(batches, key=lambda key: int(key[1:]))
    require(len({int(key[1:]) for key in batches}) == len(batches), "duplicate Building batch number")
    rank = {key: index for index, key in enumerate(batch_order)}
    step_nodes = {}
    for node, info in nodes.items():
        for step in info["steps"]:
            require(step in steps and step not in step_nodes, f"invalid or duplicate Runtime step {step}")
            step_nodes[step] = node
        for key, relation in (("build_needs", "<"), ("needs", "<=")):
            for prior in info[key]:
                require(prior in nodes, f"unknown prerequisite node {prior} for {node}")
                earlier = rank[nodes[prior]["batch"]]
                current = rank[info["batch"]]
                require(earlier < current or (relation == "<=" and earlier == current),
                        f"prerequisite node {prior} is not in an eligible batch for {node}")
    require(step_nodes.keys() == steps.keys(), "each Runtime step must belong to exactly one node")
    for step, info in steps.items():
        current = rank[nodes[step_nodes[step]]["batch"]]
        for key in info["needs"]:
            prior = step_nodes.get(key, key)
            require(prior in nodes and rank[nodes[prior]["batch"]] <= current,
                    f"Runtime step {step} depends on a later or unknown node: {key}")

    dependencies = {task: plan_ids(values[2]) & task_rows.keys() for task, values in task_rows.items()}
    graph_order({task: {"needs": sorted(needed)} for task, needed in dependencies.items()}, "task")
    assigned = set()
    for batch in batch_order:
        scope = batches[batch]
        owned = {steps[step]["task"] for step in scope["steps"]}
        require(owned <= task_rows.keys(), f"unknown Build Task in batch {batch}")
        require(not owned & assigned,
                f"Runtime steps owned by the same Build Task must share a Building batch: {batch}")
        pending = list(owned)
        while pending:
            task = pending.pop()
            if task not in assigned and task not in scope["tasks"]:
                scope["tasks"].add(task)
                pending.extend(dependencies[task])
        assigned.update(scope["tasks"])
    if len(batches) == 1:
        batches[batch_order[0]]["tasks"].update(task_rows)
    else:
        require(assigned == task_rows.keys(), "every Build Task must be linked to a Runtime step or task dependency")
    return {"scope_key": "batch_id", "node_header": BATCH_NODES_HEADER,
            "nodes": nodes, "steps": steps, "batches": {key: batches[key] for key in batch_order}}


def verify_graph(content, tasks):
    steps = unique(table(content, "## Runtime 执行图", STEPS_HEADER), "Runtime step ID")
    layout = batch_plan(content)
    if layout is None:
        nodes = unique(table(content, "## 阶段性验收节点", NODES_HEADER), "Runtime node ID")
    else:
        nodes = {key: ("", "、".join(sorted(value["steps"])), "、".join(sorted(value["needs"])))
                 for key, value in layout["nodes"].items()}
    require(not steps.keys() & nodes.keys(), "Runtime step and node IDs must be disjoint")
    links = {}
    handled = set()
    for node, (_, members, needs, *_rest) in nodes.items():
        member_ids = plan_ids(members)
        dependencies = plan_ids(needs)
        require(re.fullmatch(r"N\d+", node) and member_ids and member_ids <= steps.keys()
                and not member_ids & handled and dependencies <= nodes.keys(), f"invalid Runtime node: {node}")
        handled.update(member_ids)
        links[node] = {"needs": sorted(member_ids | dependencies)}
    require(handled == steps.keys(), "each Runtime step must belong to exactly one node")
    for step, (task, needs, *_rest) in steps.items():
        dependencies = plan_ids(needs)
        require(task in tasks and dependencies <= steps.keys() | nodes.keys(), f"invalid Runtime step: {step}")
        links[step] = {"needs": sorted(dependencies)}
    graph_order(links, "Runtime")


def _logical_results(content):
    outputs = unique(table(content, "### 拟得到的输出", RESULT_HEADER, allow_empty=True), "output ID")
    output_paths = {}
    for output_id, (_, raw_path, *_) in outputs.items():
        path = relative(raw_path.strip("\x60"), "logical result path")
        require(len(path.parts) >= 3 and path.parts[0] == "results"
                and path.parts[1] in {"data", "plot", "smoke_test"}, f"invalid logical result path: {raw_path}")
        output_paths[output_id] = path.as_posix()
    no_path_collisions(list(output_paths.values()), "logical result path")
    return output_paths


def result_paths(content):
    return set(_logical_results(content).values())


def proposal_layout(plan_path, *, validate_task=None, task_ids=None):
    plan_path = Path(plan_path).resolve()
    content = plan_path.read_text(encoding="utf-8")
    require(structured_plan(content), "Build Plan requires '- path_schema: 1' for fresh Proposal")
    unit = unit_git.plan_root(plan_path)
    tasks = unique(table(content, "## 任务清单", TASK_HEADER), "task ID")
    entries = {task_id: {} for task_id in tasks}
    for task_id, raw_path, status in table(content, "## 项目目录结构", ENTRY_HEADER):
        require(task_id in tasks, f"main entry assigned to unknown task: {task_id}")
        require(status in {"新增", "既有", "迁移", "无"}, f"invalid main entry change: {status}")
        if raw_path == status == "无":
            require(not entries[task_id], f"duplicate main entry declaration for {task_id}")
            entries[task_id][raw_path] = status
            continue
        path = relative(raw_path.strip("\x60"), "main entry path")
        require(status != "无" and (status == "既有" or in_build(path)),
                f"new or migrated main entry path must be inside scripts/build/: {raw_path}")
        if status == "既有":
            existing = unit.joinpath(*path.parts)
            require(unit_git.inside(existing, unit, "existing main entry", unit_paths=True) == existing
                    and existing.is_file(),
                    f"existing main entry must be a regular file without aliases: {path}")
            unit_git.reject_hardlink(existing)
        require(path.as_posix() not in entries[task_id] and "无" not in entries[task_id],
                f"duplicate main entry declaration for {task_id}: {path}")
        entries[task_id][path.as_posix()] = status
    for task_id, paths in entries.items():
        require(paths, f"missing main entry declaration for {task_id}")
        paths.pop("无", None)
        no_path_collisions(list(paths), "main entry path")
    declarations = {}
    for paths in entries.values():
        for path, status in paths.items():
            require(declarations.setdefault(path, status) == status, f"conflicting main entry change for {path}")
    no_path_collisions(list(declarations), "main entry path")
    if task_ids is not None:
        require(set(task_ids) <= tasks.keys(), "Building scope contains an unknown task")
        declarations = {path: status for task_id in task_ids for path, status in entries[task_id].items()}

    outputs = _logical_results(content)

    expected = {}
    referenced_paths = set()
    for task_id, (link, _, needs, ac_ids) in tasks.items():
        require(re.fullmatch(TASK_ID, task_id), f"invalid task ID: {task_id}")
        path = task_spec_path(plan_path, link, unit)
        require(path not in referenced_paths, f"Task MD indexed more than once: {path}")
        referenced_paths.add(path)
        if validate_task is not None:
            validate_task(path)
        task_content = path.read_text(encoding="utf-8")
        details = document_lines(task_content)
        require(field(details, "任务 ID") == task_id
                and re.match(r"# Task " + re.escape(task_id) + r" · \S", task_content),
                f"Task MD identity differs from task index for {task_id}")
        require(task_entry_paths(task_content) == entries[task_id].keys(),
                f"main entry declaration differs between Build Plan and Task MD for {task_id}")
        criteria = unique(table(task_content, "## 验收与验证", AC_HEADER), "AC ID")
        require(all(re.fullmatch(re.escape(task_id) + r"-AC\d+", key) and values[1]
                    for key, values in criteria.items()) and plan_ids(ac_ids) == criteria.keys(),
                f"Build Plan AC index differs from Task MD for {task_id}")
        dependencies = plan_ids(needs)
        require(dependencies <= tasks.keys() | outputs.keys(), f"unknown task dependency for {task_id}")
        expected[task_id] = {"path": path, "purpose": field(details, "任务目的"),
                             "ac": {key: values[1] for key, values in criteria.items()}, "needs": dependencies & tasks.keys()}
        field(details, "任务边界与明确排除项")
    indexed_directory = plan_path.parent / "tasks"
    require(referenced_paths == set(indexed_directory.rglob("task-*.md")),
            "all Task MD files under specs/tasks must be indexed exactly once")
    graph_order({task: {"needs": sorted(spec["needs"])} for task, spec in expected.items()}, "task")
    verify_graph(content, tasks)
    return expected, declarations


def task_expectations(plan_path):
    return proposal_layout(plan_path)[0]


def verify_acceptance_index(audit_text, plan_path, *, task_ids=None):
    tasks = task_expectations(plan_path)
    if task_ids is not None:
        tasks = {key: tasks[key] for key in task_ids}
    expected = {(task_id, ac_id): (task["purpose"], criterion)
                for task_id, task in tasks.items() for ac_id, criterion in task["ac"].items()}
    rows = table(audit_text, "## 6. 任务验收索引", AUDIT_HEADER, label="acceptance index", require_block_break=True)
    seen = set()
    for task_id, purpose, ac_id, criterion, status in rows:
        identity = (task_id, ac_id)
        require(identity in expected and identity not in seen and (purpose, criterion) == expected[identity]
                and status and status not in {"无", "—", "-", "待填写"},
                f"invalid acceptance index row: {task_id} / {ac_id}")
        seen.add(identity)
    require(seen == expected.keys(), "Building Audit acceptance index must cover every approved task and AC")


def git_tree(root, revision):
    tree = unit_git.git(root, "ls-tree", "-r", "-z", revision).stdout
    files = {}
    for value in tree.split("\0"):
        if value:
            metadata, path = value.split("\t", 1)
            mode, kind, object_id = metadata.split()
            files[path] = (mode, kind, object_id)
    return files


def looks_like_script(root, path, record):
    mode, kind, _ = record
    if kind != "blob":
        return False
    if PurePosixPath(path).suffix.casefold() in SCRIPT_SUFFIXES or mode == "100755":
        return True
    # Inspect only the opening bytes of extensionless files for a shebang.
    if PurePosixPath(path).suffix or mode != "100644":
        return False
    # The Building gate has already checked that the audited worktree is clean.
    with (Path(root) / path).open("rb") as stream:
        return stream.read(2) == b"#!"


def verify_building_paths(root, plan_path, bases, head, *, task_ids=None):
    """Check the audited tree against the original scope of all completed tasks."""
    _, declarations = proposal_layout(plan_path, task_ids=task_ids)
    base_list = [bases] if isinstance(bases, str) else sorted(set(bases))
    require(base_list, "Building paths require an audited Git baseline")
    base = base_list[0] if len(base_list) == 1 else unit_git.git(root, "merge-base", "--octopus", *base_list).stdout.strip()
    prior = git_tree(root, base)
    current = git_tree(root, head)
    if task_ids is not None:
        _, all_entries = proposal_layout(plan_path)
        for path in all_entries.keys() - declarations.keys():
            require(prior.get(path) == current.get(path),
                    f"main entry changed outside the current Building batch: {path}")
    for path, status in declarations.items():
        require(path in current and current[path][0] in {"100644", "100755"},
                f"approved main entry missing or not a regular file at audited HEAD: {path}")
        require((path in prior) == (status == "既有"),
                f"approved main entry change differs from Building Git scope: {path}")
        if status == "既有":
            require(prior[path][0] in {"100644", "100755"},
                    f"existing main entry must be a regular file at the Building baseline: {path}")
            require(in_build(PurePosixPath(path)) or prior[path] == current[path],
                    f"legacy main entry must remain unchanged outside scripts/build/: {path}")
    for path in current.keys() - prior.keys():
        if looks_like_script(root, path, current[path]):
            parts = PurePosixPath(path).parts
            require(len(parts) >= 3 and parts[0] == "scripts" and parts[1] in {"build", *ANCILLARY},
                    f"new analysis scripts belong in scripts/build/: {path}")
