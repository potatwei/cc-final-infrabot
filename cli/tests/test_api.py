from infrapilot.api import FakeClient, get_client


def test_fake_client_submit_returns_flat_shape():
    c = FakeClient()
    payload = c.submit("deploy my app on port 3000")

    assert payload["status"] == "success"
    assert payload["task_id"].startswith("fake-")
    for key in ("intent", "files", "commands", "requires_confirmation", "explanation"):
        assert key in payload, f"missing {key}"
    assert isinstance(payload["files"], list)
    assert isinstance(payload["commands"], list)
    assert all({"step_name", "description", "command"} <= set(c.keys()) for c in payload["commands"])


def test_fake_client_intent_dispatch():
    c = FakeClient()
    assert c.submit("set up my infrastructure")["intent"] == "setup_infra"
    assert c.submit("deploy my app")["intent"] == "deploy_service"
    assert c.submit("scale to 5")["intent"] == "scale_service"
    assert c.submit("tear it all down")["intent"] == "teardown_all"


def test_fake_client_confirm_approved():
    c = FakeClient()
    p = c.submit("set up infra")
    r = c.confirm(p["task_id"], approved=True)
    assert r["status"] == "executed"
    assert r["task_id"] == p["task_id"]


def test_fake_client_confirm_declined():
    c = FakeClient()
    p = c.submit("set up infra")
    r = c.confirm(p["task_id"], approved=False)
    assert r["status"] == "cancelled"


def test_fake_client_confirm_unknown_id():
    c = FakeClient()
    r = c.confirm("nope", approved=True)
    assert r["status"] == "error"


def test_get_client_defaults_to_fake():
    assert isinstance(get_client({}), FakeClient)
