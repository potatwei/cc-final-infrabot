"""Plain-text rendering for backend payloads and results."""


def show_payload(payload: dict) -> None:
    """Render the task payload returned by POST /task."""
    meta = payload.get("metadata") or {}
    task_id = payload.get("task_id", "")
    explanation = payload.get("explanation", "")

    print()
    print("=== Task ===")
    print(f"  Intent:   {meta.get('intent', '?')}")
    print(f"  Provider: {meta.get('provider', '?')}")
    print(f"  Region:   {meta.get('region', '?')}")
    print(f"  Risk:     {meta.get('estimated_risk', '?')}")
    if task_id:
        print(f"  Task:     {task_id}")
    if explanation:
        print()
        print(explanation)

    infra = payload.get("infrastructure") or {}
    files = infra.get("files") or []
    commands = infra.get("commands") or []

    for f in files:
        path = f.get("path", "")
        ftype = f.get("type", "")
        content = f.get("content", "")
        print()
        print(f"--- {path} ({ftype}) ---")
        print(content)
        print(f"--- end {path} ---")

    if commands:
        print()
        print("Commands:")
        for c in commands:
            cmd_str = f"{c.get('binary', '')} {' '.join(c.get('args') or [])}".strip()
            critical = "critical" if c.get("critical", True) else "optional"
            print(f"  {c.get('step', '?'):>2}. {c.get('label', '')}")
            print(f"      $ {cmd_str}  [{critical}]")
    print()


def show_result(result: dict) -> None:
    """Render the response from POST /task/<id>/confirm."""
    status = result.get("status", "?")
    message = result.get("message", "")
    print()
    print(f"=== Result: {status.upper()} ===")
    if message:
        print(message)
    print()


def confirm(message: str = "Proceed?") -> bool:
    answer = input(f"{message} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def success(msg: str) -> None:
    print(f"[ok] {msg}")


def failure(msg: str) -> None:
    print(f"[error] {msg}")


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(f"[warn] {msg}")
