"""ProxmintTools: a Strands tool that reads web pages through Proxmint proxies."""

from __future__ import annotations

from typing import Literal

from strands import tool

from strands_proxmint._gateway import Credentials, client_for, fetch, load_credentials, new_session_id, proxy_username


class ProxmintTools:
    """Fetch web pages through Proxmint residential, datacenter or mobile proxies.

    Credentials: ``api_key`` (else ``PROXMINT_API_KEY``), or ``username`` and ``password``
    (else ``PROXMINT_USERNAME`` / ``PROXMINT_PASSWORD``). Give an agent ``tools.proxmint_fetch``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        product: Literal["residential", "premium-residential", "datacenter", "mobile"] = "residential",
        country: str | None = None,
        state: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        asn: str | None = None,
        session_minutes: int | None = None,
        output: Literal["text", "html"] = "text",
        max_chars: int = 50_000,
        timeout: float = 60.0,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.product = product
        self.country = country
        self.targeting = {"country": country, "state": state, "city": city, "zip_code": zip_code, "asn": asn}
        self.session_minutes = session_minutes
        self.output = output
        self.max_chars = max_chars
        self.timeout = timeout
        self.username = username
        self.password = password
        self._creds: Credentials | None = None
        self._session_id = new_session_id() if session_minutes else None

    def _credentials(self) -> Credentials:
        if self._creds is None:
            self._creds = load_credentials(self.api_key, self.product, username=self.username, password=self.password)
        return self._creds

    @tool
    def proxmint_fetch(self, url: str, country: str | None = None) -> str:
        """Read a web page through a proxy, so the request comes from a residential, datacenter or mobile IP,
        optionally in a chosen country. Returns the final URL, HTTP status, title and the page as readable text.
        Use it for pages that block cloud servers or show different content in different countries.

        Args:
            url: The http or https URL of the page to read.
            country: Two-letter country code for the exit IP, for example "us" or "de". Leave empty for any country.
        """
        creds = self._credentials()
        # A country named in the call replaces the default one, and the finer default targeting with it.
        targeting = (
            {"country": country} if country and country.lower() != (self.country or "").lower() else self.targeting
        )
        username = proxy_username(
            creds.username, **targeting, session_id=self._session_id, session_minutes=self.session_minutes
        )
        with client_for(creds, username, timeout=self.timeout) as client:
            page = fetch(client, url)

        body = page.html if self.output == "html" else page.text()
        if len(body) > self.max_chars:
            body = body[: self.max_chars] + f"\n\n[cut at {self.max_chars:,} characters]"
        head = [f"URL: {page.url}", f"Status: {page.status}"]
        if page.title:
            head.append(f"Title: {page.title}")
        return "\n".join(head) + "\n\n" + body


# Ready-made instance for `Agent(tools=[proxmint_fetch])`: residential, credentials from the environment.
proxmint_fetch = ProxmintTools().proxmint_fetch

__all__ = ["ProxmintTools", "proxmint_fetch"]
