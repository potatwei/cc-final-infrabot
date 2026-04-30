"""Plain-text rendering for backend payloads and results."""

import shutil
import textwrap


# Built-in hints for common AWS / Fargate inputs. Backend may not ship these,
# so we keep a small lookup table to surface options at the prompt.
INPUT_HINTS = {
    "region":                  "e.g. us-east-1, us-west-2, eu-west-1",
    "aws_region":              "e.g. us-east-1, us-west-2, eu-west-1",
    "project_name":            "alphanumeric, e.g. my-project",
    "instance_type":           "e.g. t3.micro, t3.small, t3.medium, m5.large",
    "vpc_id":                  "vpc-xxxxxxxx (from setup_infra outputs)",
    "subnet_id":               "subnet-xxxxxxxx",
    "subnet_ids":              "comma-separated, e.g. subnet-aaa,subnet-bbb",
    "private_subnet_ids":      "comma-separated subnet ids",
    "public_subnet_ids":       "comma-separated subnet ids",
    "cluster_name":            "your ECS cluster name",
    "ecs_cluster_name":        "your ECS cluster name",
    "cluster_arn":             "arn:aws:ecs:...:cluster/...",
    "service_name":            "name of the ECS service",
    "container_name":          "container in the task definition",
    "container_port":          "port the app listens on, e.g. 3000",
    "port":                    "port number, e.g. 3000, 8080, 80",
    "image_uri":               "ECR URI, e.g. <acct>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag>",
    "image":                   "ECR URI or docker image, e.g. nginx:latest",
    "ecr_url":                 "ECR repository URL",
    "ecr_repository_url":      "ECR repository URL",
    "alb_listener_arn":        "arn:aws:elasticloadbalancing:...:listener/...",
    "alb_security_group_id":   "sg-xxxxxxxx",
    "ecs_task_security_group_id": "sg-xxxxxxxx",
    "ecs_task_sg_id":          "sg-xxxxxxxx",
    "cpu":                     "Fargate CPU units: 256, 512, 1024, 2048, 4096",
    "memory":                  "Fargate memory MiB: 512, 1024, 2048, 4096, 8192",
    "replicas":                "desired task count, e.g. 1-10",
    "desired_count":           "desired task count, e.g. 1-10",
    "health_check_path":       "HTTP path, e.g. /health",
    "ecs_task_execution_role_arn": "arn:aws:iam::...:role/...",
    "domain":                  "fully-qualified domain, e.g. app.example.com",
    "ami_id":                  "ami-xxxxxxxx",
    "key_name":                "EC2 key pair name",
}


def hint_for(name: str) -> str | None:
    """Return a short, human-readable hint for the named input, or None."""
    if not name:
        return None
    return INPUT_HINTS.get(name) or INPUT_HINTS.get(name.lower())


def build_prompt_label(name: str, classification: str | None,
                       default) -> str:
    """Return the indented prompt label, with classification, default, and hint."""
    bits = []
    if classification:
        bits.append(classification)
    if default is not None and default != "":
        bits.append(f"default: {default}")
    hint = hint_for(name)
    if hint:
        bits.append(hint)
    label = f"    {name}"
    if bits:
        label += "  (" + "; ".join(bits) + ")"
    return label


def _term_width(default: int = 80) -> int:
    try:
        return min(shutil.get_terminal_size((default, 20)).columns, 100)
    except OSError:
        return default


def _hr(char: str = "-", indent: int = 0) -> str:
    return " " * indent + char * (_term_width() - indent)


def _section(title: str) -> str:
    bar = "-" * 4
    return f"\n  {bar} {title} {bar * max(1, (_term_width() - 8 - len(title)) // 1)}"[: _term_width()]


def _wrap(text: str, indent: int = 2) -> str:
    width = _term_width() - indent
    pad = " " * indent
    paragraphs = text.splitlines() or [text]
    out = []
    for p in paragraphs:
        if not p.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(p, width=width, initial_indent=pad, subsequent_indent=pad)
                   or [pad + p])
    return "\n".join(out)


def _render_input_list(title: str, names: list, defaults: dict, provided: dict) -> None:
    if not names:
        return
    print()
    print(f"  {title}:")
    for inp in names:
        given = provided.get(inp)
        default = defaults.get(inp)
        if given is not None:
            suffix = f" = {given}"
        elif default is not None:
            suffix = f"  (default: {default})"
        else:
            suffix = ""
        print(f"    - {inp}{suffix}")


def show_payload(payload: dict) -> None:
    """Render the task payload returned by POST /task."""
    task_id = payload.get("task_id", "")
    status = payload.get("status", "")
    intent = payload.get("intent") or "?"
    mode = payload.get("mode")
    selected_tool = payload.get("selected_tool")
    precheck_tool = payload.get("precheck_tool")
    ready_to_execute = payload.get("ready_to_execute")
    explanation = payload.get("explanation", "")
    error = payload.get("error")
    missing = (payload.get("missing_parameters")
               or payload.get("missing_inputs")
               or [])
    notes = payload.get("notes") or []
    files = payload.get("files") or []
    commands = payload.get("commands") or []
    required_inputs = payload.get("required_inputs") or []
    recommended_inputs = payload.get("recommended_inputs") or []
    optional_inputs = payload.get("optional_inputs") or []
    defaults = payload.get("defaults") or {}
    provided_inputs = payload.get("provided_inputs") or {}

    width = _term_width()
    print()
    print("=" * width)
    header = f"  TASK  {intent}"
    if status:
        right = f"[{status}]  "
        pad = max(2, width - len(header) - len(right))
        print(header + " " * pad + right)
    else:
        print(header)
    print("=" * width)
    if task_id:
        print(f"  id:       {task_id}")
    if mode:
        print(f"  mode:     {mode}")
    if selected_tool:
        print(f"  tool:     {selected_tool}")
    if precheck_tool:
        print(f"  precheck: {precheck_tool}")
    if ready_to_execute is not None:
        print(f"  ready:    {ready_to_execute}")

    if explanation:
        print()
        print(_wrap(explanation))

    if error:
        print(_section("error"))
        print()
        print(_wrap(error))

    if missing:
        print(_section("missing"))
        print()
        for m in missing:
            print(f"    - {m}")

    if required_inputs or recommended_inputs or optional_inputs or provided_inputs:
        print(_section("inputs"))
        _render_input_list("required",    required_inputs,    defaults, provided_inputs)
        _render_input_list("recommended", recommended_inputs, defaults, provided_inputs)
        _render_input_list("optional",    optional_inputs,    defaults, provided_inputs)
        listed = set(required_inputs) | set(recommended_inputs) | set(optional_inputs)
        extras = {k: v for k, v in provided_inputs.items() if k not in listed}
        if extras:
            print()
            print("  provided:")
            for k, v in extras.items():
                print(f"    - {k} = {v}")

    if notes:
        print(_section("notes"))
        print()
        for n in notes:
            print(_wrap(f"- {n}", indent=4))

    if files:
        print(_section(f"files ({len(files)})"))
        for f in files:
            path = f.get("path", "")
            ftype = f.get("type") or ""
            content = (f.get("content") or "").rstrip()
            label = f"{path}" + (f"  [{ftype}]" if ftype else "")
            print()
            print(f"  • {label}")
            print(_hr("·", indent=4))
            for line in content.splitlines() or [""]:
                print(f"    {line}")
            print(_hr("·", indent=4))

    if commands:
        print(_section(f"commands ({len(commands)})"))
        print()
        for i, c in enumerate(commands, 1):
            label = (c.get("description")
                     or c.get("step_name")
                     or c.get("label")
                     or "")
            cmd = c.get("command")
            if not cmd:
                binary = c.get("binary", "")
                args = " ".join(c.get("args") or [])
                cmd = f"{binary} {args}".strip()
            tag = ""
            if c.get("critical") is True:
                tag = "  (critical)"
            elif c.get("critical") is False:
                tag = "  (optional)"
            num = c.get("step", i)
            print(f"  [{num}] {label}{tag}".rstrip())
            if cmd:
                print(f"      $ {cmd}")
            if i < len(commands):
                print()

    print()
    print("=" * width)
    print()


def show_result(result: dict) -> None:
    """Render the response from POST /task/<id>/confirm."""
    status = (result.get("status") or "?").upper()
    message = result.get("message", "")
    width = _term_width()
    print()
    print("-" * width)
    print(f"  RESULT: {status}")
    print("-" * width)
    if message:
        print(_wrap(message))
        print()


def confirm(message: str = "Proceed?") -> bool:
    answer = input(f"  {message} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def success(msg: str) -> None:
    print(f"  [ok]    {msg}")


def failure(msg: str) -> None:
    print(f"  [error] {msg}")


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(f"  [warn]  {msg}")
