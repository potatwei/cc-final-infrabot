import json
from unittest.mock import MagicMock, patch

import pytest

from infrapilot import publish


# ---------------------------------------------------------------------------
# bucket-name discovery
# ---------------------------------------------------------------------------

def test_find_bucket_in_state(tmp_path):
    state = {
        "resources": [{
            "type": "aws_s3_bucket",
            "instances": [{"attributes": {"bucket": "from-state-1234"}}],
        }],
    }
    (tmp_path / "terraform.tfstate").write_text(json.dumps(state))
    assert publish.find_bucket_name_in_run_dir(tmp_path) == "from-state-1234"


def test_find_bucket_in_tf_source(tmp_path):
    (tmp_path / "main.tf").write_text(
        'resource "aws_s3_bucket" "b" {\n  bucket = "from-source-name-99"\n}\n'
    )
    assert publish.find_bucket_name_in_run_dir(tmp_path) == "from-source-name-99"


def test_find_bucket_returns_none_when_absent(tmp_path):
    (tmp_path / "main.tf").write_text("# empty file")
    assert publish.find_bucket_name_in_run_dir(tmp_path) is None


def test_find_bucket_state_wins_over_source(tmp_path):
    (tmp_path / "main.tf").write_text('bucket = "from-source"')
    state = {"resources": [{"type": "aws_s3_bucket",
                            "instances": [{"attributes": {"bucket": "from-state"}}]}]}
    (tmp_path / "terraform.tfstate").write_text(json.dumps(state))
    assert publish.find_bucket_name_in_run_dir(tmp_path) == "from-state"


# ---------------------------------------------------------------------------
# git clone
# ---------------------------------------------------------------------------

def test_clone_repo_failure_raises(tmp_path):
    with patch("shutil.which", return_value="/usr/bin/git"), \
         patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=128, stderr="fatal: bad url\n", stdout="")
        with pytest.raises(publish.PublishError) as ei:
            publish.clone_repo("https://nope")
    assert "git clone failed" in str(ei.value)


def test_clone_repo_no_git_binary_raises():
    with patch("shutil.which", return_value=None):
        with pytest.raises(publish.PublishError) as ei:
            publish.clone_repo("https://github.com/x/y")
    assert "git is not on PATH" in str(ei.value)


def test_clone_repo_success_returns_path(tmp_path):
    # Pretend git succeeds. We don't really care about path contents here.
    with patch("shutil.which", return_value="/usr/bin/git"), \
         patch("subprocess.run") as run, \
         patch("tempfile.mkdtemp", return_value=str(tmp_path / "clone-x")):
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        # mkdtemp returned path; clone_repo will leave it as-is on success.
        out = publish.clone_repo("https://github.com/x/y", branch="dev")
    assert str(out) == str(tmp_path / "clone-x")
    cmd = run.call_args[0][0]
    assert cmd[:5] == ["git", "clone", "--depth", "1", "--branch"]
    assert cmd[-2] == "https://github.com/x/y"


# ---------------------------------------------------------------------------
# website endpoint URL
# ---------------------------------------------------------------------------

def test_website_endpoint_default_region():
    assert publish.website_endpoint("my-bucket") == \
        "http://my-bucket.s3-website.us-east-1.amazonaws.com"


def test_website_endpoint_custom_region():
    assert publish.website_endpoint("b", "eu-west-2") == \
        "http://b.s3-website.eu-west-2.amazonaws.com"


# ---------------------------------------------------------------------------
# sync_dir_to_bucket  (boto3 mocked)
# ---------------------------------------------------------------------------

def test_sync_dir_skips_dotfiles(tmp_path):
    (tmp_path / "index.html").write_text("<html>hi</html>")
    (tmp_path / ".env").write_text("SECRET")
    sub = tmp_path / "assets"
    sub.mkdir()
    (sub / "app.js").write_text("console.log(1)")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main")

    s3 = MagicMock()
    with patch("boto3.client", return_value=s3):
        n = publish.sync_dir_to_bucket(tmp_path, "bucket-x")
    assert n == 2  # index.html, assets/app.js (no .env, no .git/*)
    keys = sorted(call.kwargs["Key"] for call in s3.upload_file.call_args_list)
    assert keys == ["assets/app.js", "index.html"]
    # Content-Type set per file
    ctypes = {call.kwargs["Key"]: call.kwargs["ExtraArgs"]["ContentType"]
              for call in s3.upload_file.call_args_list}
    assert ctypes["index.html"] == "text/html"
    assert ctypes["assets/app.js"] in ("application/javascript", "text/javascript")


def test_sync_dir_empty_returns_zero(tmp_path):
    s3 = MagicMock()
    with patch("boto3.client", return_value=s3):
        assert publish.sync_dir_to_bucket(tmp_path, "bucket-x") == 0
    s3.upload_file.assert_not_called()


# ---------------------------------------------------------------------------
# enable_website
# ---------------------------------------------------------------------------

def test_enable_website_calls_three_apis():
    s3 = MagicMock()
    with patch("boto3.client", return_value=s3):
        publish.enable_website("b", region="us-west-2")
    s3.delete_public_access_block.assert_called_once_with(Bucket="b")
    s3.put_bucket_policy.assert_called_once()
    s3.put_bucket_website.assert_called_once()
    body = json.loads(s3.put_bucket_policy.call_args.kwargs["Policy"])
    stmt = body["Statement"][0]
    assert stmt["Effect"] == "Allow"
    assert stmt["Resource"] == "arn:aws:s3:::b/*"
    web_cfg = s3.put_bucket_website.call_args.kwargs["WebsiteConfiguration"]
    assert web_cfg["IndexDocument"]["Suffix"] == "index.html"
    assert web_cfg["ErrorDocument"]["Key"] == "error.html"


def test_enable_website_tolerates_no_existing_block():
    from botocore.exceptions import ClientError
    s3 = MagicMock()
    s3.delete_public_access_block.side_effect = ClientError(
        {"Error": {"Code": "NoSuchPublicAccessBlockConfiguration"}}, "DeletePublicAccessBlock"
    )
    with patch("boto3.client", return_value=s3):
        publish.enable_website("b")  # should not raise
    s3.put_bucket_policy.assert_called_once()
    s3.put_bucket_website.assert_called_once()
