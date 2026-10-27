"""Proxmint credentials, gateway usernames and one fetch through the proxy.

Targeting rides in the proxy username: the login, then ``__``, then ``key.value``
parameters joined by ``;``, for example ``login__cr.us;city.newyork;sessid.ab12;sessttl.30``.
"""

from __future__ import annotations

import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

ACCOUNT_URL = "https://proxmint.com/api/v1/account"
PRODUCTS = ("residential", "premium-residential", "datacenter", "mobile")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# What the gateway puts in the status line when it refuses a request itself.
GATEWAY_ERRORS = {
    "SITE_PERMANENTLY_BLOCKED": "The site is on the network's blocked list: https://proxmint.com/docs/blocked-websites",
    "PORT_BLOCKED": "The destination port is closed. Web traffic works on 80, 443, 8080, 8443, 8888 and 8090.",
    "HOST_BLOCKED": "You blocked this host yourself under Blocked hosts on your product page.",
    "NO_USER": "The gateway doesn't recognise the login. Copy the credentials again from your dashboard.",
    "TRAFFIC_EXHAUSTED": "The product's bandwidth is used up. Add a pack at https://proxmint.com/pricing",
    "THREADS_EXHAUSTED": "Too many connections at once. Lower your concurrency.",
    "USER_BLOCKED": "The proxy user is blocked, usually after many wrong passwords. Contact support@proxmint.com",
    "NO_HOST_CONNECTION": "The exit IP couldn't reach the site. Retry: a new request gets a new IP.",
    "NO_RAY": "No IPs match your targeting. Drop the city, ZIP or ASN, or check the location spelling.",
}

_FOLD = str.maketrans(
    {"ł": "l", "ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ð": "d", "þ": "th", "ı": "i", "ħ": "h"}
)


class GatewayError(Exception):
    """The Proxmint gateway refused the request (bad login, no bandwidth, blocked site...)."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    host: str = "gw.proxmint.com"
    port: int = 823


def load_credentials(
    api_key: str | None = None,
    product: str = "residential",
    *,
    username: str | None = None,
    password: str | None = None,
    client: httpx.Client | None = None,
) -> Credentials:
    """Proxy login for one product.

    A username and password (arguments, else ``PROXMINT_USERNAME`` / ``PROXMINT_PASSWORD``)
    are used as they are. Otherwise the API key (argument, else ``PROXMINT_API_KEY``) reads
    them from the account, which also picks the right product.
    """
    if product not in PRODUCTS:
        raise ValueError(f"product must be one of {', '.join(PRODUCTS)}")
    if not api_key:
        username = username or os.getenv("PROXMINT_USERNAME")
        password = password or os.getenv("PROXMINT_PASSWORD")
        if username and password:
            return Credentials(username, password)
        api_key = os.getenv("PROXMINT_API_KEY")
    if not api_key:
        raise ValueError(
            "Set PROXMINT_API_KEY (create one under Settings at https://proxmint.com/dashboard) "
            "or PROXMINT_USERNAME and PROXMINT_PASSWORD."
        )

    get = client.get if client else httpx.get
    r = get(ACCOUNT_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    if r.status_code == 401:
        raise ValueError("Proxmint rejected the API key. Create a new one under Settings in the dashboard.")
    r.raise_for_status()
    for p in r.json()["products"]:
        if p["product"] != product:
            continue
        if p["status"] != "active":
            raise ValueError(f"Your {product} product is {p['status']}. Top it up at https://proxmint.com/dashboard")
        px = p["proxy"]
        return Credentials(px["username"], px["password"], px["host"], int(px["httpPort"]))
    raise ValueError(f"This account has no {product} product. Buy a pack at https://proxmint.com/pricing")


def _geo(value: str) -> str:
    """A place name in the gateway's form: "São Paulo" -> saopaulo, "Łódź" -> lodz."""
    s = unicodedata.normalize("NFKD", value.lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).translate(_FOLD)
    return re.sub(r"[^a-z0-9]", "", s)


def proxy_username(
    login: str,
    *,
    country: str | None = None,
    state: str | None = None,
    city: str | None = None,
    zip_code: str | None = None,
    asn: str | int | None = None,
    session_id: str | None = None,
    session_minutes: int | None = None,
) -> str:
    """The login with targeting and sticky-session parameters appended."""
    if (state or city or zip_code or asn) and not country:
        raise ValueError("state, city, zip_code and asn need a country as well.")
    params = []
    if country:
        params.append("cr." + re.sub(r"[^a-z]", "", country.lower())[:2])
    if city:
        params.append("city." + _geo(city))
    if state:
        params.append("state." + _geo(state))
    if zip_code:
        params.append("zip." + str(zip_code).strip())
    if asn:
        params.append("asn." + re.sub(r"\D", "", str(asn)))
    if session_id:
        params.append("sessid." + _geo(session_id))
    if session_minutes:
        params.append(f"sessttl.{max(1, min(120, round(session_minutes)))}")
    return f"{login}__{';'.join(params)}" if params else login


def new_session_id() -> str:
    return secrets.token_hex(6)


def client_for(creds: Credentials, username: str, *, timeout: float = 60.0, headers: dict | None = None) -> httpx.Client:
    """An HTTP client whose every request leaves through the gateway as ``username``."""
    proxy = httpx.Proxy(f"http://{creds.host}:{creds.port}", auth=(username, creds.password))
    return httpx.Client(
        proxy=proxy,
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": USER_AGENT, **(headers or {})},
    )


@dataclass(frozen=True)
class Page:
    url: str
    status: int
    content_type: str
    html: str
    title: str | None

    def text(self) -> str:
        return html_to_text(self.html) if "html" in self.content_type else self.html


def fetch(client: httpx.Client, url: str) -> Page:
    """GET one page. Gateway refusals raise GatewayError; the site's own answers return as a Page."""
    if not re.match(r"https?://", url):
        raise ValueError(f"Not an http(s) URL: {url}")
    try:
        r = client.get(url)
    except httpx.ProxyError as e:  # HTTPS: the refusal comes back on the CONNECT
        raise _gateway_error(str(e)) from e
    reason = r.reason_phrase.strip().upper()
    if r.status_code in (400, 403, 407, 500, 502, 503) and reason in GATEWAY_ERRORS:  # plain HTTP
        raise _gateway_error(f"{r.status_code} {reason}")
    ctype = r.headers.get("content-type", "")
    body = r.text
    title = _Text.parse(body).title if "html" in ctype else None
    return Page(str(r.url), r.status_code, ctype, body, title)


def _gateway_error(status_line: str) -> GatewayError:
    reason = status_line.split()[-1].upper() if status_line.split() else ""
    hint = GATEWAY_ERRORS.get(reason, "See https://proxmint.com/docs/errors")
    return GatewayError(f"Proxmint gateway: {status_line}. {hint}")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "footer",
        "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
        "section", "table", "td", "th", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._skip = 0
        self._in_title = False

    @classmethod
    def parse(cls, html: str) -> _Text:
        p = cls()
        p.feed(html)
        p.close()
        return p

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = self.title is None  # the page's own, not an <svg><title>
        if tag == "body":
            self._skip = 0  # </head> is optional in HTML
        elif tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title = ((self.title or "") + data).strip()
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Readable text of a page: no scripts or styles, one line per block, blank lines squeezed."""
    raw = "".join(_Text.parse(html).parts)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in raw.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
