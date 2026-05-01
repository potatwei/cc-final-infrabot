"""AWS identity verification for the local Terraform deployment phase.

The CLI doesn't manage AWS credentials itself — it relies entirely on boto3's
default credential chain (env vars → ~/.aws/credentials → SSO → IMDS). This
module just probes that chain via STS GetCallerIdentity and surfaces the result
so the user can confirm they're hitting the intended account before any
`terraform apply` runs.
"""

from __future__ import annotations

import os


class AwsAuthError(Exception):
    """Raised when AWS identity cannot be resolved."""


def resolve_identity() -> dict:
    """Return ``{account, arn, user_id}`` from STS, or raise AwsAuthError.

    Lazy-imports boto3 so users on FakeClient-only paths don't pay the cost.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError as e:
        raise AwsAuthError(
            "boto3 is not installed. Run `pip install boto3` (or reinstall the CLI)."
        ) from e

    try:
        sts = boto3.client("sts")
        resp = sts.get_caller_identity()
    except NoCredentialsError as e:
        raise AwsAuthError(
            "No AWS credentials found. Run `aws configure` or `aws sso login`, "
            "or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars."
        ) from e
    except (ClientError, BotoCoreError) as e:
        raise AwsAuthError(f"AWS STS call failed: {e}") from e

    return {
        "account": resp.get("Account", ""),
        "arn": resp.get("Arn", ""),
        "user_id": resp.get("UserId", ""),
    }


def verify_account(expected: str | None) -> tuple[bool, dict]:
    """Resolve identity and check it matches ``expected`` if provided.

    Returns ``(ok, identity)``. ``ok`` is True when no expectation is set OR
    the resolved account matches. Raises AwsAuthError if identity can't be
    resolved at all.
    """
    identity = resolve_identity()
    if not expected:
        return True, identity
    return identity["account"] == str(expected), identity


def terraform_env(region: str | None = None) -> dict[str, str]:
    """Return an env dict suitable for ``subprocess.Popen``.

    Forwards the parent process env (so AWS_PROFILE, AWS_ACCESS_KEY_ID, the
    SSO cache path, etc. all propagate) and optionally pins ``AWS_REGION`` so
    the Terraform AWS provider doesn't fall back to a different default.
    """
    env = dict(os.environ)
    if region:
        env["AWS_REGION"] = region
        env["AWS_DEFAULT_REGION"] = region
    return env
