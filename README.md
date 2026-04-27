# cc-final-infrabot

InfraPilot agent/orchestration repo. This repo owns tool registration,
agent orchestration, and agent-facing output shaping. It does not own the
deterministic workflow planner.

## Workflow-Core Boundary

This repo integrates with
[`infrapilot-workflow-core`](https://github.com/maxtaitw/infrapilot-workflow-core.git)
as the source of truth for:

- workflow schemas
- input validation
- deterministic planning
- Terraform rendering

This repo remains responsible for:

- natural-language interpretation in the agent loop
- deciding which tool to call
- translating agent-friendly arguments into workflow-core input
- returning machine-readable tool output to downstream callers

The adapter boundary is intentionally thin:

```python
from infrapilot_workflow import (
    ProjectState,
    WorkflowInput,
    build_execution_plan,
)
```

## Available Workflow Tools

All workflow tools live in [tools/workflow_tools.py](</Users/maxtai/Cloud Computing/cc-final-infrabot/tools/workflow_tools.py>)
and are registered through [tools/__init__.py](</Users/maxtai/Cloud Computing/cc-final-infrabot/tools/__init__.py>).

| Tool | Workflow intent | What it plans | Required state |
| --- | --- | --- | --- |
| `plan_setup_infra` | `setup_infra` | Shared ECS/Fargate platform creation | `project_name` |
| `plan_deploy_service` | `deploy_service` | Service deployment + service Terraform | `project_name`, infra metadata |
| `plan_scale_service` | `scale_service` | Replica count change for an existing service | `project_name`, infra metadata, stored service state, `replicas` |
| `plan_stop_service` | `stop_service` | Scale an existing service down to zero | `project_name`, infra metadata, stored service state, explicit `service_name` |
| `plan_teardown_service` | `teardown_service` | Destroy one service while leaving shared infra intact | `project_name`, infra metadata, stored service state, explicit `service_name` |
| `plan_teardown_infra` | `teardown_infra` | Destroy the shared ECS/Fargate platform | `project_name` |

Each tool returns a machine-readable payload with at least:

- `intent`
- `files`
- `commands`
- `notes`
- `requires_confirmation`
- `steps`
- `status`
- `error`

Implementation notes:

- `files` is flattened from workflow-core `step.generated_files`
- `steps` preserves the original workflow-core plan steps for backend/debug visibility
- `commands` is currently an empty list because workflow-core does not yet emit executable command payloads
- `ValueError` from workflow-core validation is converted into structured tool output instead of crashing the agent

## Local Setup

This repo now expects Python 3.10+ because workflow-core requires it.
The checked path uses Python 3.13.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Local Verification

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
.venv/bin/python -m compileall tools agents run_agent.py tests
```

## Design Intent

Do not move planner logic into this repo.
Do not copy workflow-core implementation here.
Add new agent tools here only as thin adapters that:

1. accept agent-friendly structured arguments
2. build `ProjectState` and `WorkflowInput`
3. call `build_execution_plan(...)`
4. normalize the result into the agent-facing payload shape
