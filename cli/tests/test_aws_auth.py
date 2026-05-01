import os
from unittest.mock import MagicMock, patch

import pytest

from infrapilot import aws_auth


def _stub_sts(account="123456789012", arn="arn:aws:iam::123456789012:user/u",
              user_id="AID-USER"):
    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Account": account, "Arn": arn, "UserId": user_id,
    }
    return sts


def test_resolve_identity_success():
    with patch("boto3.client", return_value=_stub_sts()):
        identity = aws_auth.resolve_identity()
    assert identity == {
        "account": "123456789012",
        "arn": "arn:aws:iam::123456789012:user/u",
        "user_id": "AID-USER",
    }


def test_resolve_identity_no_creds_raises():
    from botocore.exceptions import NoCredentialsError
    sts = MagicMock()
    sts.get_caller_identity.side_effect = NoCredentialsError()
    with patch("boto3.client", return_value=sts):
        with pytest.raises(aws_auth.AwsAuthError) as ei:
            aws_auth.resolve_identity()
    assert "credentials" in str(ei.value).lower()


def test_verify_account_match():
    with patch("boto3.client", return_value=_stub_sts(account="111122223333")):
        ok, identity = aws_auth.verify_account("111122223333")
    assert ok is True
    assert identity["account"] == "111122223333"


def test_verify_account_mismatch():
    with patch("boto3.client", return_value=_stub_sts(account="111122223333")):
        ok, identity = aws_auth.verify_account("000000000000")
    assert ok is False
    assert identity["account"] == "111122223333"


def test_verify_account_no_expectation_passes():
    with patch("boto3.client", return_value=_stub_sts()):
        ok, _ = aws_auth.verify_account(None)
    assert ok is True


def test_terraform_env_pins_region():
    env = aws_auth.terraform_env("eu-west-1")
    assert env["AWS_REGION"] == "eu-west-1"
    assert env["AWS_DEFAULT_REGION"] == "eu-west-1"
    # parent env preserved
    assert env.get("PATH") == os.environ.get("PATH")


def test_terraform_env_no_region_passthrough():
    env = aws_auth.terraform_env(None)
    assert "AWS_REGION" not in env or env["AWS_REGION"] == os.environ.get("AWS_REGION", "")
