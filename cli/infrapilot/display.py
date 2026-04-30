"""Plain-text rendering for backend payloads and results."""

import shutil
import textwrap


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
