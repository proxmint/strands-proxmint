import httpx
import pytest
from strands import Agent

import strands_proxmint.tools as tools_mod
from strands_proxmint import ProxmintTools, proxmint_fetch

HTML = "<html><head><title>Hi</title></head><body><p>Hello there</p></body></html>"


@pytest.fixture
def gateway(monkeypatch):
    """Stand-in for the gateway: records the proxy username of each request and answers with `reply`."""
    seen = {"usernames": [], "reply": (200, b"OK", HTML)}

    def fake_client_for(creds, username, *, timeout=60.0, headers=None):
        seen["usernames"].append(username)
        status, reason, body = seen["reply"]

        def handler(req):
            return httpx.Response(
                status, headers={"content-type": "text/html"}, text=body, extensions={"reason_phrase": reason}
            )

        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(tools_mod, "client_for", fake_client_for)
    return seen


def test_tool_spec():
    spec = ProxmintTools(username="u", password="p").proxmint_fetch.tool_spec
    assert spec["name"] == "proxmint_fetch"
    schema = spec["inputSchema"]["json"]
    assert set(schema["properties"]) == {"url", "country"}
    assert schema["required"] == ["url"]
    assert spec["description"].startswith("Read a web page through a proxy")
    assert proxmint_fetch.tool_name == "proxmint_fetch"


def test_fetch_and_targeting(gateway):
    t = ProxmintTools(username="u", password="p", country="us", city="New York", session_minutes=30)
    out = t.proxmint_fetch(url="https://example.com/")
    assert out == "URL: https://example.com/\nStatus: 200\nTitle: Hi\n\nHello there"
    sid = t._session_id
    # The same country keeps the city; another country drops it; the session holds across calls.
    t.proxmint_fetch(url="https://example.com/", country="US")
    t.proxmint_fetch(url="https://example.com/", country="de")
    assert gateway["usernames"] == [
        f"u__cr.us;city.newyork;sessid.{sid};sessttl.30",
        f"u__cr.us;city.newyork;sessid.{sid};sessttl.30",
        f"u__cr.de;sessid.{sid};sessttl.30",
    ]


def test_html_output_and_cut(gateway):
    out = ProxmintTools(username="u", password="p", output="html", max_chars=20).proxmint_fetch(url="http://a.example/")
    assert out.endswith("\n\n<html><head><title>H\n\n[cut at 20 characters]")


def test_agent_gets_gateway_refusal_as_error_result(gateway):
    gateway["reply"] = (503, b"NO_RAY", "")
    agent = Agent(tools=[ProxmintTools(username="u", password="p").proxmint_fetch], callback_handler=None)
    result = agent.tool.proxmint_fetch(url="http://example.com/", record_direct_tool_call=False)
    assert result["status"] == "error"
    assert "No IPs match your targeting" in result["content"][0]["text"]

    gateway["reply"] = (200, b"OK", HTML)
    result = agent.tool.proxmint_fetch(url="http://example.com/", record_direct_tool_call=False)
    assert result["status"] == "success"
    assert result["content"][0]["text"].endswith("Hello there")
