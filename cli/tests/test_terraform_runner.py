from unittest.mock import MagicMock, patch

from infrapilot import terraform_runner


def test_check_binary_missing():
    with patch("shutil.which", return_value=None):
        assert terraform_runner.check_binary() is None


def test_check_binary_present():
    with patch("shutil.which", return_value="/usr/local/bin/terraform"), \
         patch("subprocess.run") as run:
        run.return_value = MagicMock(stdout="Terraform v1.7.4\n+ provider...\n")
        assert terraform_runner.check_binary() == "Terraform v1.7.4"


def test_plan_parses_summary(tmp_path):
    captured_text = (
        "Terraform used the selected providers...\n"
        "Plan: 4 to add, 0 to change, 1 to destroy.\n"
        "Saved the plan to: tfplan\n"
    )
    with patch.object(terraform_runner, "_stream", return_value=(0, captured_text)):
        rc, summary = terraform_runner.plan(tmp_path, {})
    assert rc == 0
    assert summary == "Plan: 4 to add, 0 to change, 1 to destroy."


def test_plan_no_changes(tmp_path):
    captured_text = (
        "No changes. Your infrastructure matches the configuration.\n"
        "Saved the plan to: tfplan\n"
    )
    with patch.object(terraform_runner, "_stream", return_value=(0, captured_text)):
        rc, summary = terraform_runner.plan(tmp_path, {})
    assert rc == 0
    assert "No changes" in summary


def test_plan_failure_returns_empty_summary(tmp_path):
    with patch.object(terraform_runner, "_stream", return_value=(1, "boom\n")):
        rc, summary = terraform_runner.plan(tmp_path, {})
    assert rc == 1
    assert summary == ""


def test_outputs_parses_json(tmp_path):
    raw = '{"bucket": {"value": "demo"}, "id": {"value": "i-abc"}}'
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=raw)
        out = terraform_runner.outputs(tmp_path, {})
    assert out == {"bucket": "demo", "id": "i-abc"}


def test_outputs_returns_empty_on_failure(tmp_path):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="")
        assert terraform_runner.outputs(tmp_path, {}) == {}


def test_init_apply_destroy_call_stream(tmp_path):
    with patch.object(terraform_runner, "_stream", return_value=(0, "")) as s:
        terraform_runner.init(tmp_path, {})
        terraform_runner.apply(tmp_path, {})
        terraform_runner.destroy(tmp_path, {})
    assert s.call_count == 3
    init_cmd = s.call_args_list[0][0][0]
    apply_cmd = s.call_args_list[1][0][0]
    destroy_cmd = s.call_args_list[2][0][0]
    assert init_cmd[:2] == ["terraform", "init"]
    assert apply_cmd[:2] == ["terraform", "apply"]
    assert "tfplan" in apply_cmd
    assert destroy_cmd[:2] == ["terraform", "destroy"]
    assert "-auto-approve" in destroy_cmd
