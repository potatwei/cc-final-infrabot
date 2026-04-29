# cc-final-infrabot

InfraPilot agent/orchestration repo. This repo owns tool registration,
agent orchestration, and agent-facing output shaping.

The current default agent surface is intentionally small:

- core resource tools for one-shot AWS planning (`S3`, `EC2`)
- core resource tools for one-shot AWS planning (`S3`, `EC2`, `VPC`)
- advanced ECS/Fargate workflow tools kept in-repo but isolated from the
  default agent registry until the broader workflow story is ready

## Tool Surface

Default agent tools:

- `check_s3_name_availability`
- `generate_s3_terraform`
- `generate_ec2_terraform`
- `generate_vpc_terraform`

Advanced workflow tools currently remain available in code but are not
registered in the default agent tool list:

- `plan_setup_infra`
- `plan_deploy_service`
- `plan_scale_service`
- `plan_stop_service`
- `plan_teardown_service`
- `plan_teardown_infra`

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

All workflow tools live in [tools/workflow_tools.py](<tools/workflow_tools.py>)
and are exported through [tools/__init__.py](<tools/__init__.py>) as
advanced tools rather than default agent tools.

| Tool | Workflow intent | What it plans | Required state |
| --- | --- | --- | --- |
| `plan_setup_infra` | `setup_infra` | Shared ECS/Fargate platform creation | `project_name` |
| `plan_deploy_service` | `deploy_service` | Service deployment + service Terraform | `project_name`, infra metadata including `ecs_task_execution_role_arn` |
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
- `commands` is populated only when workflow-core includes executable shell command payloads; current advanced deploy workflow returns placeholder shell steps without top-level commands
- `ValueError` from workflow-core validation is converted into structured tool output instead of crashing the agent
- workflow-core still plans one intent at a time; this repo does not combine `setup_infra` and `deploy_service` into one plan
- `deploy_service` still requires existing infrastructure state, while `stop_service` and `teardown_service` still require explicit `service_name`
- `teardown_infra` now requires `project_state.services` to be empty

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

For the default resource-planning smoke path with Bedrock:

```bash
.venv/bin/python run_agent.py "create a t3.micro ec2 instance in us-east-1"
```

For direct advanced workflow smoke checks without Bedrock, point `PYTHONPATH`
at the local workflow-core checkout and run one of the built-in demos:

```bash
PYTHONPATH="/Users/maxtai/Cloud Computing/FinalProject/InfraPilot" \
  .venv/bin/python run_agent.py --demo deploy-success
PYTHONPATH="/Users/maxtai/Cloud Computing/FinalProject/InfraPilot" \
  .venv/bin/python run_agent.py --demo deploy-needs-infra
PYTHONPATH="/Users/maxtai/Cloud Computing/FinalProject/InfraPilot" \
  .venv/bin/python run_agent.py --demo stop-needs-service-name
```

## Design Intent

Do not move planner logic into this repo.
Do not copy workflow-core implementation here.
Add new agent tools here only as thin adapters that:

1. accept agent-friendly structured arguments
2. build `ProjectState` and `WorkflowInput`
3. call `build_execution_plan(...)`
4. normalize the result into the agent-facing payload shape without executing Terraform, Docker, or AWS commands
