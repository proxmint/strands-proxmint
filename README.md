# strands-proxmint

[Strands Agents](https://strandsagents.com) tool for [Proxmint](https://proxmint.com) proxies: let an agent read
web pages from residential, datacenter or 4G/5G mobile IPs. Pick the exit country, state, city, ZIP or ASN, and
keep one IP for up to two hours when a site needs it.

The agent passes a URL and, optionally, a country, and gets back the final URL, HTTP status, title and the page
as readable text. Requests go straight from your machine to the Proxmint gateway (`gw.proxmint.com`). Nothing
else sits in between, and bandwidth comes out of your own Proxmint account.

## Install

```bash
pip install strands-proxmint
```

## Credentials

Create an API key under **Settings** in the [Proxmint dashboard](https://proxmint.com/dashboard) and export it:

```bash
export PROXMINT_API_KEY="pmk_..."
```

The key reads the proxy login for the product you choose (`residential` by default). You can pass the proxy
login instead, with `PROXMINT_USERNAME` and `PROXMINT_PASSWORD` or the `username` / `password` arguments.

## Use it in an agent

```python
from strands import Agent
from strands_proxmint import proxmint_fetch

agent = Agent(tools=[proxmint_fetch])
agent("What does the front page of example.com say when visited from Germany?")
```

`proxmint_fetch` uses the residential product and reads the credentials from the environment. For other
settings, create a `ProxmintTools` and pass its `proxmint_fetch`:

```python
from strands import Agent
from strands_proxmint import ProxmintTools

proxmint = ProxmintTools(product="mobile", country="us", city="New York", session_minutes=30)
agent = Agent(tools=[proxmint.proxmint_fetch])
```

Options on `ProxmintTools`:

| Option | Default | What it does |
| --- | --- | --- |
| `api_key` | `PROXMINT_API_KEY` | Proxmint API key |
| `product` | `"residential"` | `residential`, `premium-residential`, `datacenter` or `mobile` |
| `country` | any | Default exit country (two-letter code) when a call doesn't name one |
| `state`, `city`, `zip_code`, `asn` | none | Finer targeting; needs `country`. A call that names another country drops it |
| `session_minutes` | none | Keep one exit IP across calls for 1 to 120 minutes. Default: a new IP on every call |
| `output` | `"text"` | `"text"` for readable text, `"html"` for the raw page |
| `max_chars` | `50000` | Cut longer pages |
| `timeout` | `60` | Seconds per request |

You can also call the tool yourself: `agent.tool.proxmint_fetch(url="https://example.com", country="de")`.

Gateway refusals (no bandwidth left, no IP matching the targeting, a blocked site) come back to the agent as an
error result with a short message saying what to change.

## Good to know

- Web traffic works on destination ports 80, 443, 8080, 8443, 8888 and 8090 ([port access](https://proxmint.com/docs/ports)).
- A short list of sites, mostly banking and government, is refused by the network ([blocked websites](https://proxmint.com/docs/blocked-websites)).
- City, state, ZIP and ASN targeting meter at 2x on residential, datacenter and mobile ([targeting](https://proxmint.com/docs/targeting)).
- The tool does not run JavaScript. It reads what the server sends.

Full guide: [proxmint.com/docs/strands](https://proxmint.com/docs/strands). Pricing: [proxmint.com/pricing](https://proxmint.com/pricing).
Bandwidth is billed per GB and never expires.

## Development

```bash
uv run --group test pytest
```

The tests run offline against a stand-in for the gateway.

## License

MIT
