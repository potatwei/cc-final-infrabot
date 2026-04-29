# Future Improvements

This file tracks useful follow-up ideas that are intentionally out of scope for the current two-stage discovery + local CLI demo.

## CLI Commands

- `/use <task_id>`
  - Switch the active task inside chat without creating a new request.
- `/reset`
  - Clear the current discovery values and restart review for the active task.
- `/set key=value`
  - Deterministic single-field update command for users who do not want free-form review updates.

## Discovery And Validation

- Local S3 bucket-name format validation before AWS availability checks.
  - Avoids reporting malformed names like `e` as merely "unavailable."
- Review-time lookup prompts integrated into continuation flow.
  - Example: while an EC2 task is active, `/lookup instance_types` should guide the next update.
- More deterministic parsers for multi-field user input.
  - Better support for natural phrases beyond `field: value` and `field change to value`.
- Stronger distinction between:
  - missing values
  - invalid values
  - values overridden from defaults

## Task Lifecycle

- `/confirm` result callback should distinguish:
  - "generate final Terraform payload"
  - "local execution finished successfully"
  - "local execution failed"
- Add richer backend task states such as:
  - `execution_running`
  - `cancelled`
  - `superseded`

## CLI Execution

- Materialize returned `files` into a local temp directory.
- Run returned `commands` locally with streamed output.
- Send execution results back to backend after local Terraform/Docker runs.

## Backend And Deployment

- Replace `sys.path.append(...)` with proper package/import setup for Lambda deployment.
- Add deployment docs for:
  - API Gateway
  - Lambda
  - RDS PostgreSQL
  - Bedrock IAM permissions
- Improve task listing filters:
  - by status
  - by recent activity
  - by active session

## UX Polish

- Make `/show` optionally print full Terraform content.
- Add clearer prompts when a task is already `awaiting_confirmation`.
- Keep lookup results visible while returning to the active discovery task.
