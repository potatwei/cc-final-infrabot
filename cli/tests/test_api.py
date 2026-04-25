from infrapilot.api import FakeClient, get_client


def test_fake_client_submit_returns_person_a_shape():
    c = FakeClient()
    payload = c.submit("deploy my app on port 3000")

    assert payload["status"] == "success"
    assert payload["task_id"].startswith("fake-")
    assert "metadata" in payload and "infrastructure" in payload and "explanation" in payload
    meta = payload["metadata"]
    for key in ("intent", "provider", "region", "requires_confirmation", "estimated_risk"):
        assert key in meta, f"metadata missing {key}"
    infra = payload["infrastructure"]
    assert isinstance(infra["files"], list)
    assert isinstance(infra["commands"], list)
    assert all({"step", "label", "binary", "args", "critical"} <= set(c.keys()) for c in infra["commands"])


def test_fake_client_intent_dispatch():
    c = FakeClient()
    assert c.submit("set up my infrastructure")["metadata"]["intent"] == "setup_infra"
    assert c.submit("deploy my app")["metadata"]["intent"] == "deploy_service"
    assert c.submit("scale to 5")["metadata"]["intent"] == "scale_service"
    assert c.submit("tear it all down")["metadata"]["intent"] == "teardown_all"


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
    assert isinstance(get_client({"api_url": "x", "api_key": "y"}), FakeClient)  # Part 1 behavior
