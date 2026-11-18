# AWS SigV4 Gateway Authentication

## Overview

Some upstream MCP servers sit behind AWS IAM authentication. Examples are a Lambda function URL with `AWS_IAM` auth and an API Gateway endpoint with IAM authorization. These endpoints reject bearer tokens and static headers. They accept only requests signed with [AWS Signature Version 4](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-signing.html).

ContextForge supports this with `auth_type: "sigv4"` on a gateway. The gateway stores AWS credentials and signs every request it sends to the upstream server.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`
    - Dev server (`make dev`): `http://localhost:8000`

## How it works

A SigV4 signature covers the HTTP method, path, query string, selected headers, and a SHA-256 hash of the exact request body. It also carries a timestamp, and AWS accepts a signature for only about 15 minutes. A signature therefore cannot live in a stored header the way a bearer token does.

ContextForge attaches a signer to the HTTP client that talks to the upstream server. The signer runs once for every outgoing request and computes a new signature each time. This covers:

- the `initialize` call and tool, resource, and prompt discovery at registration
- tool calls, resource reads, prompt fetches, and completions
- requests on pooled upstream sessions that stay open for a long time
- gateway health checks

A long-lived session never reuses an expired signature.

## Prerequisites

- An upstream MCP server behind AWS IAM authentication, reachable over `SSE` or `STREAMABLEHTTP`.
- An IAM identity with permission to call that endpoint. Use a dedicated identity with the minimum policy.
- The access key ID, secret access key, AWS region, and AWS service name of the endpoint.
- A ContextForge API token with permission to create gateways.
- `AUTH_ENCRYPTION_SECRET` set on the gateway. It encrypts the stored secret. SigV4 adds no other environment variable.

## Register a SigV4 gateway

Create an API token:

```bash
export GW=http://127.0.0.1:8000
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 10080 --secret "$JWT_SECRET_KEY")
```

`$JWT_SECRET_KEY` must match the value the running gateway uses.

Register the gateway with `POST /gateways`:

```bash
curl -sS -X POST "$GW/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "aws-lambda-sigv4",
    "url": "https://<id>.lambda-url.<region>.on.aws/mcp",
    "transport": "STREAMABLEHTTP",
    "visibility": "public",
    "auth_type": "sigv4",
    "sigv4_config": {
      "access_key_id": "<access-key-id>",
      "secret_access_key": "<secret-access-key>",
      "session_token": "<optional, temporary credentials only>",
      "region": "<region>",
      "service": "<service, for example lambda or execute-api>"
    }
  }'
```

!!! warning "Keep secrets out of shell history"
    Do not paste a real secret access key into a command line. Read it with `read -rs` and build the JSON with `jq`:

    ```bash
    read -rs "AWS_SK?Secret access key: "; echo
    jq -n --arg url "$FN_URL" --arg ak "$AWS_AK" --arg sk "$AWS_SK" --arg region "$AWS_REGION" '{
      name: "aws-lambda-sigv4", url: $url, transport: "STREAMABLEHTTP", visibility: "public", auth_type: "sigv4",
      sigv4_config: {access_key_id: $ak, secret_access_key: $sk, region: $region, service: "lambda"}
    }' | curl -sS -X POST "$GW/gateways" -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" -d @-
    unset AWS_SK
    ```

Use the API to register a SigV4 gateway and to change its credentials. The Admin UI edit form keeps the stored SigV4 settings when you save, but it cannot change them.

### `sigv4_config` fields

| Field | Required | Rule |
|-------|----------|------|
| `access_key_id` | yes | 16 to 128 letters or digits. |
| `secret_access_key` | yes | Encrypted at rest. Masked in API responses. |
| `session_token` | no | Use only with temporary STS credentials. Encrypted at rest. Masked in API responses. |
| `region` | yes | Lowercase letters, digits, and hyphens. Example: `eu-north-1`. |
| `service` | yes | Lowercase letters, digits, and hyphens. Examples: `lambda`, `execute-api`. |

`sigv4_config` rejects any other key. It is valid only when `auth_type` is `sigv4`.

`transport` is `STREAMABLEHTTP` or `SSE`.

### What registration does

1. ContextForge validates the request and encrypts `secret_access_key` and `session_token`.
2. It signs the `initialize` call and tool discovery, and sends them to the upstream server.
3. If the upstream server accepts the signature, ContextForge saves the gateway and its tools.
4. If the upstream server answers 401 or 403, registration fails with a message that the upstream server rejected the SigV4 credentials. ContextForge saves no gateway.

| Result | Meaning |
|--------|---------|
| `200` or `201` | The gateway is registered. The response shows the secret and token masked. |
| `422` | The `sigv4_config` shape is wrong, for example a missing field or a bad region. |
| Credential error from the upstream server | The access key, secret, region, or service does not match the endpoint. |
| `401` or `403` from ContextForge | The API token lacks permission to create gateways. |

## Check the gateway

List the tools that discovery found:

```bash
curl -sS "$GW/tools?limit=0" -H "Authorization: Bearer $TOKEN" | jq '.[].name'
```

Confirm that reads never return the secret:

```bash
curl -sS "$GW/gateways" -H "Authorization: Bearer $TOKEN" | grep -c "<your-secret-access-key>"
```

The expected output is `0`.

## Rotate credentials

Send a new `sigv4_config` with `PUT /gateways/{id}`:

```bash
curl -sS -X PUT "$GW/gateways/<gateway-id>" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "auth_type": "sigv4",
    "sigv4_config": {
      "access_key_id": "<access-key-id>",
      "secret_access_key": "<new-secret-access-key>",
      "region": "<region>",
      "service": "<service>"
    }
  }'
```

- A change to `sigv4_config` closes the pooled upstream sessions of that gateway. The next call uses the new credentials.
- Send the masked value as `secret_access_key` or `session_token` to keep the stored value. A client can send back a gateway it just read without overwriting the secret.
- Change `auth_type` to another value to drop SigV4. ContextForge then clears `sigv4_config`.

## Security properties

- The secret access key and session token are encrypted at rest with `AUTH_ENCRYPTION_SECRET`. API reads return them masked. No API or log output shows the plaintext.
- An `Authorization` header sent by a client never replaces the signature. SigV4 gateways ignore it.
- Export skips SigV4 gateways, so signing credentials never reach an export file.
- Two SigV4 gateways collide only when `access_key_id`, `region`, and `service` all match. A SigV4 gateway never collides with a gateway of another auth type.
- A stored secret that ContextForge cannot decrypt fails closed. The call returns an error and sends no unsigned request.

## Limits

- ContextForge stores static credentials. It does not refresh an expired STS session token. Update `sigv4_config` before the token expires.
- The Admin UI cannot change SigV4 credentials. Saving the edit form keeps the stored settings. Use the API to change them.
- The modern listener skips SigV4 gateways, because a standing stream cannot sign each request. SigV4 gateways get no list-changed push events.
- SigV4 applies to `SSE` and `STREAMABLEHTTP` gateways.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Registration fails with "upstream rejected the SigV4 credentials" | Wrong access key, secret, region, or service. The region and service must match the endpoint. An expired session token also causes it. |
| `422` on registration | Missing field, unknown key, or malformed region, service, or access key ID. |
| Registration works, then health checks fail | The IAM identity lost its permission, or the key was rotated or disabled in AWS. |
| Calls fail after the session token expires | STS tokens expire. Update `sigv4_config` with a new token. |
| `no such column: sigv4_config` | The database lacks migration `e5a7c2d9b4f1`. Restart the gateway or run `alembic upgrade head`. |
| An unsigned `curl` to the upstream URL returns `200` | The endpoint is public. Set its auth type to `AWS_IAM` or the equivalent. |
