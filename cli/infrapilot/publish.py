"""Static-website hosting helpers.

After ``terraform apply`` creates an S3 bucket, this module:
  1. Clones a user-supplied GitHub repo to a temp dir.
  2. Configures the bucket for public static-website hosting via boto3:
     - removes the public-access block
     - puts a public-read bucket policy
     - sets the website index/error documents
  3. Uploads every file from the clone into the bucket with a sane Content-Type.

The bucket is configured locally rather than via Terraform so the team's
backend does not have to be changed; the trade-off is that destroying the
bucket later is up to ``infrapilot destroy`` (terraform handles it because
the bucket is the same Terraform resource — only its website-config metadata
was set out-of-band).
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path


class PublishError(Exception):
    """Anything that prevents a successful publish."""


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def clone_repo(repo_url: str, branch: str | None = None) -> Path:
    """Shallow-clone ``repo_url`` to a fresh temp dir and return the path.

    Caller is responsible for cleanup via :func:`cleanup`.
    """
    if shutil.which("git") is None:
        raise PublishError("git is not on PATH; install git to publish a repo.")

    dest = Path(tempfile.mkdtemp(prefix="infrapilot-clone-"))
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, str(dest)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise PublishError(f"git clone failed to launch: {e}") from e

    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise PublishError("git clone failed:\n  " + "\n  ".join(msg))
    return dest


def cleanup(path: Path) -> None:
    """Remove a tempdir created by :func:`clone_repo`."""
    if path and path.exists():
        shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# S3 website configuration
# ---------------------------------------------------------------------------

def enable_website(bucket_name: str, region: str | None = None,
                   index_document: str = "index.html",
                   error_document: str = "error.html") -> None:
    """Configure ``bucket_name`` for public static website hosting.

    Drops the public-access block, puts a permissive bucket policy, and sets
    the website index/error documents. Idempotent — safe to call repeatedly.
    """
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")

    # 1. Drop the public-access block (S3 default is to block public ACLs/policies).
    try:
        s3.delete_public_access_block(Bucket=bucket_name)
    except ClientError as e:
        # NoSuchPublicAccessBlockConfiguration is fine — already absent.
        if e.response.get("Error", {}).get("Code") != "NoSuchPublicAccessBlockConfiguration":
            raise PublishError(f"delete_public_access_block failed: {e}") from e

    # 2. Put a public-read bucket policy.
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadForWebsite",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject"],
            "Resource": f"arn:aws:s3:::{bucket_name}/*",
        }],
    }
    try:
        s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))
    except ClientError as e:
        raise PublishError(f"put_bucket_policy failed: {e}") from e

    # 3. Set website index/error documents.
    try:
        s3.put_bucket_website(
            Bucket=bucket_name,
            WebsiteConfiguration={
                "IndexDocument": {"Suffix": index_document},
                "ErrorDocument": {"Key": error_document},
            },
        )
    except ClientError as e:
        raise PublishError(f"put_bucket_website failed: {e}") from e


def website_endpoint(bucket_name: str, region: str | None = None) -> str:
    """Return the standard S3 static-website endpoint URL.

    See https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html
    Two URL formats exist depending on region; we use the dot-region form,
    which is correct for every commercial region except us-east-1 (where the
    dash form also works). The dot form also works for us-east-1 in practice.
    """
    region = region or "us-east-1"
    return f"http://{bucket_name}.s3-website.{region}.amazonaws.com"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

# Small extension list so common static-site files get the right Content-Type
# when boto3's mimetypes guess fails.
_EXT_FALLBACK = {
    ".js":   "application/javascript",
    ".mjs":  "application/javascript",
    ".css":  "text/css",
    ".html": "text/html",
    ".htm":  "text/html",
    ".json": "application/json",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map":  "application/json",
    ".txt":  "text/plain",
    ".md":   "text/markdown",
    ".webp": "image/webp",
    ".webmanifest": "application/manifest+json",
}


def _content_type_for(path: Path) -> str:
    guess, _ = mimetypes.guess_type(str(path))
    if guess:
        return guess
    return _EXT_FALLBACK.get(path.suffix.lower(), "application/octet-stream")


def sync_dir_to_bucket(local_dir: Path, bucket_name: str,
                       region: str | None = None,
                       skip_dotfiles: bool = True) -> int:
    """Upload every regular file under ``local_dir`` to ``bucket_name``.

    Returns the number of files uploaded. ``.git/`` and other dotfiles/dirs
    are skipped by default. Each upload sets a guessed Content-Type so a
    browser opens .html/.css/.js correctly.
    """
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    count = 0

    for path in local_dir.rglob("*"):
        if not path.is_file():
            continue
        if skip_dotfiles and any(part.startswith(".") for part in path.relative_to(local_dir).parts):
            continue
        key = str(path.relative_to(local_dir)).replace("\\", "/")
        ctype = _content_type_for(path)
        try:
            s3.upload_file(
                Filename=str(path),
                Bucket=bucket_name,
                Key=key,
                ExtraArgs={"ContentType": ctype},
            )
        except ClientError as e:
            raise PublishError(f"upload failed at {key}: {e}") from e
        count += 1
    return count


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_bucket_name_in_run_dir(run_dir: Path) -> str | None:
    """Best-effort: read the bucket name out of the run dir.

    Looks at terraform's state file first (authoritative), then any .tf file
    for a literal ``bucket = "..."`` line. Returns None when neither yields
    anything.
    """
    state_files = list(run_dir.glob("**/terraform.tfstate"))
    for sf in state_files:
        try:
            data = json.loads(sf.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for resource in data.get("resources") or []:
            if resource.get("type") != "aws_s3_bucket":
                continue
            for inst in resource.get("instances") or []:
                attrs = inst.get("attributes") or {}
                name = attrs.get("bucket")
                if name:
                    return str(name)

    # Fall back to scanning .tf source for a literal bucket = "...".
    import re
    pat = re.compile(r'\bbucket\s*=\s*"([^"]+)"')
    for tf in run_dir.rglob("*.tf"):
        try:
            text = tf.read_text(encoding="utf-8")
        except OSError:
            continue
        m = pat.search(text)
        if m:
            return m.group(1)
    return None
