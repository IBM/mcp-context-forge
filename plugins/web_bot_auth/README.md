# Web Bot Auth Signing Plugin

## Overview

Signs the gateway's outbound tool calls and A2A agent calls with
[Web Bot Auth](https://datatracker.ietf.org/doc/draft-ietf-webbotauth-httpsig-protocol/),
the IETF profile of RFC 9421 HTTP Message Signatures for automated clients.
An upstream server, or the CDN or bot-management layer in front of it, can then
verify that a request comes from this gateway instead of trusting its IP
address or User-Agent.

Each signed request carries three headers under the label `sig1`:

```
Signature-Agent: sig1="https://example.com/.well-known/http-message-signatures-directory"
Signature-Input: sig1=("@authority" "signature-agent";key="sig1");created=1735689600;keyid="<JWK thumbprint>";alg="ed25519";expires=1735689660;nonce="...";tag="web-bot-auth"
Signature: sig1=:<Ed25519 signature>:
```

The signature covers the destination authority and the `Signature-Agent` URL.
The verifier fetches the public key from that URL.

## What it signs

| Hook | Destination |
|------|-------------|
| `tool_pre_invoke` | `gateway.url` for MCP tools, the tool URL for REST tools |
| `agent_pre_invoke` | `a2a_agent.endpoint_url` |

The plugin signs a call only when the destination host matches `hosts` and the
scheme is https. Plain http is signed only for loopback hosts, and only with
`allow_insecure_loopback: true`. The plugin removes any `Signature`,
`Signature-Input` or `Signature-Agent` header already on the request, so the
upstream sees only the gateway's own signature. Calls out of scope pass
unchanged.

## Configuration

```yaml
- name: "WebBotAuthPlugin"
  kind: "plugins.web_bot_auth.web_bot_auth.WebBotAuthPlugin"
  hooks: ["tool_pre_invoke", "agent_pre_invoke"]
  mode: "sequential"
  priority: 900  # run after plugins that change outbound headers
  config:
    signature_agent: "https://example.com/.well-known/http-message-signatures-directory"
    private_key_env: "WEB_BOT_AUTH_PRIVATE_KEY"
    hosts: ["api.example.com", "*.partner.example"]
    expires_in: 60
```

| Field | Default | Meaning |
|-------|---------|---------|
| `signature_agent` | required | https URL of the key directory |
| `private_key_env` | `WEB_BOT_AUTH_PRIVATE_KEY` | Environment variable with the Ed25519 private key (PEM or private JWK JSON) |
| `private_key_file` | none | Path to the key file, used instead of the environment variable |
| `hosts` | `[]` | Exact hosts, `*.suffix` for subdomains, or `*`. Empty signs nothing |
| `expires_in` | `60` | Signature lifetime in seconds, 1 to 86400 |
| `legacy_signature_agent` | `false` | Send `Signature-Agent` as a bare string, the form of earlier drafts |
| `allow_insecure_loopback` | `false` | Also sign plain http to loopback hosts, for local tests |

An enabled plugin without a key fails at startup.

## Key setup

Generate an Ed25519 key and keep it out of `plugins/config.yaml`:

```bash
openssl genpkey -algorithm ed25519 -out wba.pem
export WEB_BOT_AUTH_PRIVATE_KEY="$(cat wba.pem)"
```

Print the public key directory and serve it at `signature_agent` with
`Content-Type: application/http-message-signatures-directory+json`:

```bash
python -m plugins.web_bot_auth.web_bot_auth https://example.com/.well-known/http-message-signatures-directory
```

The directory holds the public key only. Its `kid` is the RFC 7638 JWK
thumbprint, which is also the `keyid` in each signature.

## Notes

- Web Bot Auth identifies the gateway. It does not replace upstream
  authentication such as OAuth or bearer tokens.
- On the MCP path the gateway reuses one set of headers for the requests of
  one tool call. Keep `expires_in` short.
