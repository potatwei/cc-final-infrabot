from infrapilot import lookups


def test_defaults_for_uses_backend_when_present():
    payload = {
        "intent": "launch_ec2",
        "selected_tool": "generate_ec2_terraform",
        "defaults": {"region": "eu-west-1", "instance_name": "from-backend"},
    }
    out = lookups.defaults_for(payload)
    assert out["region"] == "eu-west-1"
    assert out["instance_name"] == "from-backend"
    # Fallback fields filled in for keys backend didn't override
    assert out["vpc_cidr"] == "10.50.0.0/16"


def test_defaults_for_falls_back_to_tool_when_backend_empty():
    payload = {
        "intent": "launch_ec2",
        "selected_tool": "generate_ec2_terraform",
        "defaults": {},
    }
    out = lookups.defaults_for(payload)
    assert out == lookups.TOOL_DEFAULTS["generate_ec2_terraform"]


def test_defaults_for_uses_intent_when_selected_tool_null():
    payload = {
        "intent": "deploy_s3_bucket",
        "selected_tool": None,
        "defaults": None,
    }
    out = lookups.defaults_for(payload)
    assert out == {"region": "us-east-1"}


def test_defaults_for_unknown_intent_returns_empty():
    payload = {"intent": "make_me_a_sandwich", "defaults": {}}
    assert lookups.defaults_for(payload) == {}


def test_defaults_for_setup_infra_routes_to_vpc():
    payload = {"intent": "setup_infra"}
    out = lookups.defaults_for(payload)
    assert out["vpc_cidr"] == "10.0.0.0/16"
    assert out["vpc_name"] == "infrapilot-vpc"
