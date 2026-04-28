# Agent + Workflow Input Test Findings

Date: 2026-04-27

This note captures the current behavior of the `cc-final-infrabot` agent loop
when paired with the latest local `infrapilot-workflow-core` checkout at:

- `/Users/maxtai/Cloud Computing/FinalProject/InfraPilot`

It separates agent-side problems from workflow-core follow-up items so the
workflow-core items can be handled later in the other repo.

## Test Inputs Run

Local demo path:

- `run_agent.py --demo deploy-success`
- `run_agent.py --demo deploy-needs-infra`
- `run_agent.py --demo stop-needs-service-name`

Real Bedrock agent loop:

- `Set up the shared ECS infrastructure for project demo in us-east-1`
- `deploy an api service named demo in us-east-1`
- `Stop the service for demo-project`
- `Tear down the service for demo-project`
- `Stop service api for demo-project`
- `Tear down service api for demo-project`

## What Works

- The adapter-level demo path is healthy.
- `deploy-success` returns one Terraform file plus three structured command payloads.
- `deploy-needs-infra` correctly returns `status="needs_input"`.
- `stop-needs-service-name` correctly returns `status="needs_input"`.
- `setup_infra` tool selection works well in the Bedrock loop.

## Agent Repo Problems

### 1. `deploy` wrongly triggers `setup_infra` automatically

Observed with:

- `deploy an api service named demo in us-east-1`

Behavior:

- The model immediately called `plan_setup_infra` instead of first calling
  `plan_deploy_service`.

Why this is a problem:

- Current design is single-intent planning.
- The agent should not turn a deploy request into an implicit setup+deploy flow.
- Missing infrastructure should stop deploy planning and surface a next step,
  not start a hidden orchestration sequence.

### 2. The agent fabricates infrastructure state from Terraform output names

Observed with:

- `deploy an api service named demo in us-east-1`

Behavior:

- After `plan_deploy_service` failed due to missing infrastructure, the model
  retried by inventing values such as:
  - `output_vpc_id`
  - `output_private_subnet_ids`
  - `output_ecr_url`

Why this is a problem:

- `plan_setup_infra` only returns Terraform code; it does not return real
  infrastructure state.
- Terraform output labels are not actual values.
- The agent is currently free to treat placeholders as if they were resolved
  backend state.

### 3. The final payload can mix a real `needs_input` failure with a fake success

Observed with:

- `deploy an api service named demo in us-east-1`

Behavior:

- Earlier tool result was `needs_input`.
- Later tool result looked like success only because invented infrastructure was
  accepted by the workflow-core type contract.
- Final payload ended with:
  - `status="needs_input"`
  - three files
  - three commands
  - an explanation that claims deploy planning succeeded

Why this is a problem:

- Downstream consumers cannot trust the final payload.
- The status and explanation disagree with the generated artifacts.

### 4. The agent sometimes asks the user instead of calling a tool that would return structured `needs_input`

Observed with:

- `Stop the service for demo-project`
- `Tear down the service for demo-project`

Behavior:

- The model did not call `plan_stop_service` or `plan_teardown_service`.
- It asked for the explicit service name in free text.
- Final payload became generic `status="error"` because no tool ran.

Why this is a problem:

- We already have structured tool outputs for missing required fields.
- If the model bypasses the tool, formatter loses `intent`, `missing_parameters`,
  and structured error semantics.

### 5. Tool signatures for `stop_service` and `teardown_service` are too hard for the LLM to satisfy from natural language

Observed with:

- `Stop service api for demo-project`
- `Tear down service api for demo-project`

Behavior:

- For `stop_service`, the model called the tool but omitted `services`, causing
  a LangChain/Pydantic argument validation error before workflow-core ran.
- For `teardown_service`, the model avoided calling the tool and instead asked
  the user for `infrastructure`, `region`, and other details.

Why this is a problem:

- The agent cannot rely on workflow-core validation if the tool schema itself is
  too strict for the LLM to populate.
- Required `infrastructure` and `services` arguments are not naturally available
  from user utterances alone.

## Workflow-Core Follow-Ups

These are not the primary cause of the failures above, but they are worth
hardening later in `infrapilot-workflow-core`.

### 1. Validate infrastructure value shapes, not only presence

Observed with:

- fake values like `output_private_subnet_ids`

Problem:

- Placeholder strings pass the current presence-based checks.
- This allowed the deploy plan to render nonsense data into the template.

Suggested workflow-core hardening:

- Require `private_subnet_ids` to be `list[str]`
- Require `public_subnet_ids` to be `list[str]` where relevant
- Keep basic type validation for fields like `cluster_arn`, `vpc_id`,
  `alb_listener_arn`, `ecr_url`, `ecs_task_execution_role_arn`

### 2. Reject obvious placeholder output tokens if they appear as infrastructure values

Observed with:

- `output_vpc_id`
- `output_private_subnet_ids`
- `output_ecr_url`

Suggested workflow-core hardening:

- Add a light validation rule rejecting values that clearly look like unresolved
  Terraform output labels rather than concrete state.

### 3. Ensure list-valued infrastructure fields cannot degrade into character lists during rendering

Observed with:

- rendered subnet list becoming:
  - `"o", "u", "t", ...`

Suggested workflow-core hardening:

- Fail before rendering if `private_subnet_ids` is not a list.
- Treat this as invalid input rather than letting Jinja render bad Terraform.

## Recommended Agent Repo Plan

### Priority 1: stop fabricated setup->deploy chaining

- Update the system prompt so `deploy_service` does not trigger `setup_infra`
  automatically.
- If `plan_deploy_service` returns missing infrastructure, the agent must stop
  and tell the user or caller to plan/apply infrastructure first.
- Do not allow the model to synthesize infrastructure values from Terraform
  output names.

### Priority 2: force structured tool use for missing service name cases

- Push the model toward calling `plan_stop_service` / `plan_teardown_service`
  even when `service_name` is missing, so the tool can return structured
  `needs_input`.
- Consider lightweight wrapper tools or a simpler tool schema if required state
  (`services`, `infrastructure`) is not realistically available from the prompt.

### Priority 3: make formatter reject contradictory mixed outcomes

- If a run contains a real `needs_input` for deploy due to missing infrastructure,
  do not present later generated artifacts as valid success output unless the run
  also received real state from outside the LLM.
- Prefer the earliest blocking prerequisite failure when later tool calls are
  clearly based on invented placeholders.

### Priority 4: improve local state injection story

- Decide where `infrastructure` and `services` come from during agent execution:
  backend state, prior confirmed tool result, or explicit caller input.
- Do not expect the LLM to infer these structures from natural language alone.

## Recommended Workflow-Core Plan

Implement later in the workflow-core repo:

1. Add type/shape validation for infrastructure fields used by service intents.
2. Reject obvious unresolved placeholder output names as infrastructure state.
3. Fail fast on malformed subnet/security-group state before rendering service Terraform.

