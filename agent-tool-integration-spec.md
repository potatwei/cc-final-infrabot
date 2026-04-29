# Agent + Tool Integration Spec

This document describes how CLI, backend, or execution callers should use the
`cc-final-infrabot` agent.

## Overview

The agent returns **planning output**, not execution results.

Responsibilities are split as follows:

- **Agent repo**
  - interprets user requests
  - selects workflow tools
  - forwards structured state into workflow-core
  - returns machine-readable plans

- **workflow-core**
  - validates workflow input
  - builds deterministic plans
  - renders Terraform files
  - emits deploy shell command payloads

- **CLI/backend/executor**
  - provides real project state
  - displays plan output
  - writes files
  - executes commands and Terraform
  - persists updated state

## Default Agent Surface

The default `build_graph()` agent is currently scoped to one-shot resource
planning that maps cleanly onto the project progress report:

- `check_s3_name_availability`
- `deploy_s3_bucket`
- `deploy_ec2_instance`
- `deploy_vpc_network`

These tools are the default registry exposed to the LangGraph agent and the
FastAPI backend.

## Advanced Workflow Surface

The repo also retains an advanced ECS/Fargate workflow family backed by
`infrapilot-workflow-core`, but these tools are intentionally isolated from the
default agent registry:

- `setup_infra`
- `deploy_service`
- `scale_service`
- `stop_service`
- `teardown_service`
- `teardown_infra`

## Caller Input

Advanced workflow requests should provide:

- `project_name`
- `region`

The caller should also provide real project state when available:

- `infrastructure`
- `services`

### Infrastructure state

Service-related intents depend on infrastructure state. The caller should be
prepared to provide:

```json
{
  "cluster_arn": "arn:aws:ecs:us-east-1:123456789012:cluster/demo",
  "vpc_id": "vpc-123",
  "private_subnet_ids": ["subnet-123", "subnet-456"],
  "alb_listener_arn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/demo/1/2",
  "ecs_task_security_group_id": "sg-123",
  "ecs_task_execution_role_arn": "arn:aws:iam::123456789012:role/demo-project-ecs-task-execution-role",
  "ecr_url": "123456789012.dkr.ecr.us-east-1.amazonaws.com/demo"
}
```

### Service state

Existing-service intents depend on stored service state. The caller should be
prepared to provide:

```json
{
  "api": {
    "port": 3000,
    "cpu": 256,
    "memory": 512,
    "replicas": 2,
    "image_tag": "v1",
    "environment_variables": {
      "NODE_ENV": "production"
    }
  }
}
```

## Tool Usage

### `generate_s3_terraform`

Input:

```json
{
  "bucket_name": "demo-bucket"
}
```

Result:

- returns `main.tf`
- returns Terraform init/apply command payloads

### `generate_ec2_terraform`

Input:

```json
{
  "instance_type": "t3.micro",
  "region": "us-east-1",
  "instance_name": "demo-ec2"
}
```

Result:

- returns `main.tf`
- returns Terraform init/apply command payloads

### `generate_vpc_terraform`

Input:

```json
{
  "region": "us-east-1",
  "vpc_cidr": "10.0.0.0/16",
  "vpc_name": "demo-vpc"
}
```

Result:

- returns `main.tf`
- returns Terraform init/apply command payloads

### Advanced workflow tools

### `setup_infra`

Input:

```json
{
  "project_name": "demo-project",
  "region": "us-east-1"
}
```

Result:

- returns `infra/main.tf`

### `deploy_service`

Input:

```json
{
  "project_name": "demo-project",
  "region": "us-east-1",
  "service_name": "api",
  "port": 3000,
  "cpu": 256,
  "memory": 512,
  "replicas": 2,
  "image_tag": "v1",
  "environment_variables": {
    "NODE_ENV": "production"
  },
  "infrastructure": {
    "...": "..."
  }
}
```

Result:

- returns `service/<service_name>/main.tf`
- currently returns placeholder shell steps for image build/auth/push
- may return top-level deploy command payloads later when workflow-core provides executable shell command metadata
- returns `needs_input` if infrastructure is missing

### `scale_service`

Input:

```json
{
  "project_name": "demo-project",
  "region": "us-east-1",
  "service_name": "api",
  "replicas": 4,
  "infrastructure": {
    "...": "..."
  },
  "services": {
    "...": "..."
  }
}
```

Result:

- returns a service Terraform update
- returns `needs_input` if infrastructure or service state is missing

### `stop_service`

Input:

```json
{
  "project_name": "demo-project",
  "region": "us-east-1",
  "service_name": "api",
  "infrastructure": {
    "...": "..."
  },
  "services": {
    "...": "..."
  }
}
```

Result:

- returns a service Terraform update with replicas forced to zero
- returns `needs_input` if `service_name`, infrastructure, or service state is missing

### `teardown_service`

Input:

```json
{
  "project_name": "demo-project",
  "region": "us-east-1",
  "service_name": "api",
  "infrastructure": {
    "...": "..."
  },
  "services": {
    "...": "..."
  }
}
```

Result:

- returns a destroy-oriented service Terraform plan
- returns `needs_input` if `service_name`, infrastructure, or service state is missing

### `teardown_infra`

Input:

```json
{
  "project_name": "demo-project",
  "region": "us-east-1",
  "services": {}
}
```

Result:

- returns an infrastructure destroy plan
- should be called only after services are already removed

## Final Payload

The agent returns this shape:

```json
{
  "status": "success | needs_input | error",
  "task_id": "uuid",
  "intent": "setup_infra | deploy_service | scale_service | stop_service | teardown_service | teardown_infra",
  "files": [],
  "commands": [],
  "notes": [],
  "requires_confirmation": true,
  "steps": [],
  "error": null,
  "missing_parameters": [],
  "explanation": "human-readable summary"
}
```

### `status`

- `success`: planning completed
- `needs_input`: caller must provide more state or user input
- `error`: internal planning/orchestration failure

### `files`

Flattened generated files from workflow-core steps.

### `commands`

Top-level mirror of deploy `shell_command` steps.

Each command entry may include:

- `step_name`
- `description`
- `command`
  - `binary`
  - `args`
  - optional `env`
  - optional `working_directory`
- optional `stdin_source`

### `steps`

Full workflow-core step list, preserved for backend/debug visibility.

### `missing_parameters`

Structured list of missing inputs. Typical values:

- `infrastructure`
- `services`
- `service_name`
- `replicas`

## Caller Responsibilities

After `success`, the caller should:

1. display the plan
2. write returned files
3. execute `commands` when present
4. run Terraform apply/destroy
5. collect outputs
6. persist updated `infrastructure` and `services` state

After `needs_input`, the caller should:

1. inspect `missing_parameters`
2. gather the missing state or user input
3. retry the same intent with complete state

After `error`, the caller should:

1. stop execution
2. surface `error` and `explanation`
3. ignore files or commands from that failed response

Suggested persisted state:

```json
{
  "infrastructure": {
    "...": "..."
  },
  "services": {
    "api": {
      "...": "..."
    }
  }
}
```
