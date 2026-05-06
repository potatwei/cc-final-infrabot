# InfraPilot CLI

Natural-language DevOps chat client for AWS ECS on Fargate.

The CLI is a thin frontend: it sends user input to the backend, displays the
returned plan (intent, explanation, file previews, command list), asks for
confirmation, and forwards the yes/no answer. All Terraform authoring and
execution happens on the backend — no AWS, Docker, or Terraform tooling is
required locally.

## Install

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Usage

```
infrapilot config --api-url <URL> --api-key <KEY>
infrapilot chat
```

Type a request, review the plan, answer y/n.

## Test

```
pytest tests/ -q
```

Scripted smoke test against the fake backend:

```
printf 'set up infrastructure\ny\nscale to 3\nn\nexit\n' | infrapilot chat
```
