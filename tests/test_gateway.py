import httpx
import pytest

from strands_proxmint._gateway import GatewayError, fetch, html_to_text, load_credentials, proxy_username

ACCOUNT = {
    "balance": {"cents": 0, "usd": "0.00"},
    "products": [
        {
            "product": "residential",
            "status": "active",
            "proxy": {"host": "gw.proxmint.com", "httpPort": 823, "socks5Port": 824, "username": "u1", "password": "p1"},
        },
        {
            "product": "mobile",
            "status": "paused",
            "proxy": {"host": "gw.proxmint.com", "httpPort": 823, "socks5Port": 824, "username": "u2", "password": "p2"},
        },
    ],
}


def account_client(status=200, body=ACCOUNT):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer pmk_test"
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_username_targeting():
    assert proxy_username("u") == "u"
    assert proxy_username("u", country="US") == "u__cr.us"
    assert (
        proxy_username("u", country="br", city="São Paulo", session_id="ab12", session_minutes=30)
        == "u__cr.br;city.saopaulo;sessid.ab12;sessttl.30"
    )
    assert proxy_username("u", country="pl", city="Łódź") == "u__cr.pl;city.lodz"
    assert proxy_username("u", country="us", state="New York", zip_code=" 10001 ", asn="AS7922") == (
        "u__cr.us;state.newyork;zip.10001;asn.7922"
    )
    assert proxy_username("u", session_id="x", session_minutes=500).endswith("sessttl.120")


def test_fine_geo_needs_a_country():
    with pytest.raises(ValueError, match="need a country"):
        proxy_username("u", city="paris")


def test_credentials_from_env(monkeypatch):
    monkeypatch.delenv("PROXMINT_API_KEY", raising=False)
    monkeypatch.setenv("PROXMINT_USERNAME", "envuser")
    monkeypatch.setenv("PROXMINT_PASSWORD", "envpass")
    c = load_credentials()
    assert (c.username, c.password, c.host, c.port) == ("envuser", "envpass", "gw.proxmint.com", 823)


def test_credentials_from_api_key(monkeypatch):
    monkeypatch.delenv("PROXMINT_USERNAME", raising=False)
    c = load_credentials("pmk_test", client=account_client())
    assert (c.username, c.password) == ("u1", "p1")
    with pytest.raises(ValueError, match="mobile product is paused"):
        load_credentials("pmk_test", "mobile", client=account_client())
    with pytest.raises(ValueError, match="no datacenter product"):
        load_credentials("pmk_test", "datacenter", client=account_client())
    with pytest.raises(ValueError, match="rejected the API key"):
        load_credentials("pmk_test", client=account_client(401, {"error": "invalid"}))


def test_no_credentials(monkeypatch):
    for k in ("PROXMINT_API_KEY", "PROXMINT_USERNAME", "PROXMINT_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError, match="PROXMINT_API_KEY"):
        load_credentials()


def page_client(status=200, reason=b"OK", html="<html><head><title>Hi</title></head><body><p>x</p></body></html>"):
    def handler(req):
        return httpx.Response(
            status, headers={"content-type": "text/html; charset=utf-8"}, text=html, extensions={"reason_phrase": reason}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_page_and_gateway_refusal():
    page = fetch(page_client(), "https://example.com/")
    assert (page.status, page.title, page.text()) == (200, "Hi", "x")
    # The site's own 403 is content, not a gateway error.
    assert fetch(page_client(403, b"Forbidden"), "http://example.com/").status == 403
    with pytest.raises(GatewayError, match="No IPs match your targeting"):
        fetch(page_client(503, b"NO_RAY"), "http://example.com/")
    with pytest.raises(ValueError):
        fetch(page_client(), "ftp://example.com/")


def test_html_to_text():
    html = """<html><head><title>T</title><style>p{}</style></head>
    <body><script>var a=1</script><h1>Title</h1><p>One   two</p><p>Three&amp;four<br>five</p>
    <svg><title>icon</title></svg><ul><li>a</li><li>b</li></ul></body></html>"""
    assert html_to_text(html) == "Title\n\nOne two\n\nThree&four\nfive\n\na\n\nb"
