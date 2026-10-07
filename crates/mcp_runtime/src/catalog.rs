// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0

//! Bounded MCP catalogs and Python-compatible authenticated cursors.

use super::*;
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use hkdf::Hkdf;

const DOMAIN: &[u8] = b"contextforge:mcp-list:v1";

pub(super) struct CursorCodec(Aes256Gcm);

impl CursorCodec {
    pub(super) fn new(secret: &[u8]) -> Result<Self, String> {
        let mut key = [0u8; 32];
        Hkdf::<Sha256>::new(Some(DOMAIN), secret)
            .expand(DOMAIN, &mut key)
            .map_err(|_| "MCP cursor key derivation failed")?;
        Ok(Self(Aes256Gcm::new((&key).into())))
    }

    fn encode(&self, scope: &str, expires: u64, after: &str) -> Result<String, String> {
        let nonce: [u8; 12] = rand::random();
        let payload = serde_json::to_vec(
            &json!({"v": 1, "scope": scope, "expires": expires, "after": after}),
        )
        .map_err(|_| "MCP cursor serialization failed")?;
        let encrypted = self
            .0
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &payload,
                    aad: DOMAIN,
                },
            )
            .map_err(|_| "MCP cursor encryption failed")?;
        let mut raw = nonce.to_vec();
        raw.extend(encrypted);
        Ok(URL_SAFE_NO_PAD.encode(raw))
    }

    fn decode(&self, cursor: &Value, scope: &str, now: u64) -> Result<(String, u64), &'static str> {
        let invalid = "Invalid or expired MCP list cursor";
        let cursor = cursor
            .as_str()
            .filter(|cursor| !cursor.is_empty() && cursor.len() <= 8192)
            .ok_or(invalid)?;
        let raw = URL_SAFE_NO_PAD.decode(cursor).map_err(|_| invalid)?;
        if raw.len() < 28 {
            return Err(invalid);
        }
        let payload = self
            .0
            .decrypt(
                Nonce::from_slice(&raw[..12]),
                Payload {
                    msg: &raw[12..],
                    aad: DOMAIN,
                },
            )
            .map_err(|_| invalid)?;
        let payload: Value = serde_json::from_slice(&payload).map_err(|_| invalid)?;
        if payload.get("v").and_then(Value::as_u64) != Some(1)
            || payload.get("scope").and_then(Value::as_str) != Some(scope)
        {
            return Err(invalid);
        }
        let expires = payload
            .get("expires")
            .and_then(Value::as_u64)
            .filter(|expires| *expires > now)
            .ok_or(invalid)?;
        let after = payload
            .get("after")
            .and_then(Value::as_str)
            .filter(|after| !after.is_empty() && after.len() <= 36)
            .ok_or(invalid)?;
        Ok((after.to_string(), expires))
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub(super) struct Visibility {
    email: Option<String>,
    teams: Option<Vec<String>>,
    admin: bool,
}

fn scope_fingerprint(
    method: &str,
    server_id: &str,
    visibility: &Visibility,
    headers: &HeaderMap,
) -> String {
    let teams = visibility.teams.as_ref().map(|teams| {
        let mut teams = teams.clone();
        teams.sort();
        teams.dedup();
        teams
    });
    let session_id = headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok());
    let encoded = serde_json::to_vec(&json!([
        method,
        server_id,
        visibility.email,
        teams,
        session_id
    ]))
    .expect("scope JSON");
    format!("{:x}", Sha256::digest(encoded))
}

async fn fallback(
    state: &AppState,
    headers: HeaderMap,
    id: Option<Value>,
    body: Bytes,
    method: &str,
) -> Response {
    match method {
        "tools/list" => forward_server_tools_list_to_backend(state, headers, id, body).await,
        "resources/list" => forward_resources_list_to_backend(state, headers, body, id).await,
        "prompts/list" => forward_prompts_list_to_backend(state, headers, body, id).await,
        _ => forward_resource_templates_list_to_backend(state, headers, body, id).await,
    }
}

fn protocol_error(id: Option<Value>, code: i32, message: &str) -> Response {
    json_response(
        StatusCode::OK,
        json!({"jsonrpc": JSONRPC_VERSION, "id": id, "error": {"code": code, "message": message}}),
    )
}

pub(super) async fn serve(
    state: &AppState,
    headers: HeaderMap,
    id: Option<Value>,
    body: Bytes,
    method: &str,
) -> Response {
    let server_id = headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok());
    if server_id.is_none() || decode_internal_auth_context_from_headers(&headers).is_err() {
        return fallback(state, headers, id, body, method).await;
    }
    let server_id = server_id.expect("validated server scope");
    let authz_url = match method {
        "tools/list" => state.backend_tools_list_authz_url(),
        "resources/list" => state.backend_resources_list_authz_url(),
        "prompts/list" => state.backend_prompts_list_authz_url(),
        _ => state.backend_resource_templates_list_authz_url(),
    };
    let authorization =
        match authorize_server_method_via_backend(state, &headers, id.clone(), authz_url, method)
            .await
        {
            Ok(authorization) => authorization,
            Err(response) => return response,
        };
    let Some(visibility) = authorization.catalog_visibility else {
        return fallback(state, headers, id, body, method).await;
    };
    if (visibility.teams.is_none() && !visibility.admin)
        || !authorization.direct_execution_eligible
        || state.catalog_cursor.is_none()
        || state.db_pool().is_none()
        || headers.contains_key("x-context-forge-gateway-id")
    {
        return fallback(state, headers, id, body, method).await;
    }
    let codec = state.catalog_cursor.as_ref().expect("cursor codec");
    let request: Value = match serde_json::from_slice(&body) {
        Ok(request) => request,
        Err(_) => return protocol_error(id, -32700, "Parse error"),
    };
    let params = request.get("params");
    if params.is_some_and(|params| !params.is_object() && !params.is_null()) {
        return protocol_error(id, -32602, "Invalid list parameters");
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let scope = scope_fingerprint(method, server_id, &visibility, &headers);
    let (after, expires) = match params
        .and_then(|params| params.get("cursor"))
        .filter(|cursor| !cursor.is_null())
    {
        Some(cursor) => match codec.decode(cursor, &scope, now) {
            Ok((after, expires)) => (Some(after), expires),
            Err(message) => return protocol_error(id, -32602, message),
        },
        None => (None, now + state.catalog_cursor_ttl),
    };
    let operation = match method {
        "tools/list" => "tool.list",
        "prompts/list" => "prompt.list",
        _ => "resource.list",
    };
    let context = decode_internal_auth_context_from_headers_optional(&headers);
    let (span, _) = start_runtime_operation_span(operation, &headers, context.as_ref());
    let rows = query_page(state, server_id, &visibility, method, after)
        .instrument(span)
        .await;
    let mut rows = match rows {
        Ok(rows) => rows,
        Err(err) => {
            error!("Rust MCP catalog query failed; forwarding to Python: {err}");
            return fallback(state, headers, id, body, method).await;
        }
    };
    let more = rows.len() > state.catalog_page_size;
    rows.truncate(state.catalog_page_size);
    let key = match method {
        "tools/list" => "tools",
        "resources/list" => "resources",
        "prompts/list" => "prompts",
        _ => "resourceTemplates",
    };
    let next_cursor = if more {
        match codec.encode(&scope, expires, &rows.last().expect("nonempty page").0) {
            Ok(cursor) => Some(cursor),
            Err(message) => return protocol_error(id, -32603, &message),
        }
    } else {
        None
    };
    let mut result = json!({key: rows.into_iter().map(|(_, value)| value).collect::<Vec<_>>()});
    if let Some(cursor) = next_cursor {
        result["nextCursor"] = json!(cursor);
    }
    json_response(
        StatusCode::OK,
        json!({"jsonrpc": JSONRPC_VERSION, "id": id, "result": result}),
    )
}

async fn query_page(
    state: &AppState,
    server_id: &str,
    visibility: &Visibility,
    method: &str,
    after: Option<String>,
) -> Result<Vec<(String, Value)>, RuntimeError> {
    let (table, association, association_key, fields, extra) = match method {
        "tools/list" => (
            "tools",
            "server_tool_association",
            "tool_id",
            "c.name, c.title, c.description, c.input_schema, c.output_schema, c.annotations",
            "",
        ),
        "prompts/list" => (
            "prompts",
            "server_prompt_association",
            "prompt_id",
            "c.name, c.title, c.description, c.argument_schema",
            "",
        ),
        "resources/list" => (
            "resources",
            "server_resource_association",
            "resource_id",
            "c.uri, c.name, c.title, c.description, c.mime_type, c.size",
            "AND c.uri_template IS NULL",
        ),
        _ => (
            "resources",
            "server_resource_association",
            "resource_id",
            "c.uri_template, c.name, c.title, c.description, c.mime_type",
            "AND c.uri_template IS NOT NULL",
        ),
    };
    let query = format!(
        "SELECT c.id, {fields} FROM {table} c JOIN {association} a ON c.id = a.{association_key} \
         WHERE a.server_id = $1 AND c.enabled = TRUE {extra} AND ($2::text IS NULL OR c.id > $2) \
         AND (($3::bool AND c.visibility <> 'private') OR c.visibility = 'public' \
              OR ($4::bool AND c.owner_email = $5) \
              OR (c.team_id = ANY($6::text[]) AND c.visibility IN ('team', 'public'))) \
         ORDER BY c.id ASC LIMIT $7"
    );
    let teams = visibility.teams.clone().unwrap_or_default();
    let owner_access = visibility
        .teams
        .as_ref()
        .is_none_or(|teams| !teams.is_empty())
        && visibility.email.is_some();
    let limit = i64::try_from(state.catalog_page_size + 1).expect("bounded page size");
    let client = state
        .db_pool()
        .expect("database pool")
        .get()
        .await
        .map_err(|err| RuntimeError::Config(err.to_string()))?;
    let rows = client
        .query(
            &query,
            &[
                &server_id,
                &after,
                &visibility.admin,
                &owner_access,
                &visibility.email,
                &teams,
                &limit,
            ],
        )
        .await?;
    Ok(rows
        .into_iter()
        .map(|row| {
            let mut value = match method {
                "tools/list" => serde_json::to_value(McpToolDefinition {
                    name: row.get("name"),
                    description: row.get("description"),
                    input_schema: normalize_tool_input_schema(row.get("input_schema")),
                    output_schema: row.get("output_schema"),
                    annotations: row
                        .get::<_, Option<Value>>("annotations")
                        .unwrap_or_else(|| json!({})),
                })
                .expect("tool definition JSON"),
                "resources/list" => resource_row_to_value(&row),
                "prompts/list" => prompt_row_to_value(&row),
                _ => resource_template_row_to_value(&row),
            };
            if let Some(title) = row.get::<_, Option<String>>("title") {
                value["title"] = json!(title);
            }
            if method == "resources/templates/list" {
                value.as_object_mut().expect("template object").remove("id");
            }
            (row.get("id"), value)
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SECRET: &[u8] = b"catalog-interoperability-test-passphrase";
    const SCOPE: &str = "67905f44c8b1d8fb644f39ee8240af91fffe444f0d728060eef93d39d5b50379";
    const PYTHON_CURSOR: &str = "AAECAwQFBgcICQoLutexFwpyh0lu8oBYycZkvhCS1wszGPqr9p73_K_qbTARxdzIGpgaKknqjMRY2rHRqD86Y41Q0pvzjjckJtSviBTDgatoeqCo7sIVVVOykEufWO1PwRNnUzBkUWqo2fAp2BAhl-yTKcM_1W3XrL4c9RgT2zj-IjEKhCCteeCvkRmWMAwlR3zZJSnnWW-lXDGYVZaQs0u2WTU10ph9yFKFxmmp";

    #[test]
    fn scope_matches_python_with_normalized_teams() {
        let visibility = Visibility {
            email: Some("user@example.com".into()),
            teams: Some(vec!["t2".into(), "t1".into(), "t1".into()]),
            admin: false,
        };
        let mut headers = HeaderMap::new();
        headers.insert("mcp-session-id", HeaderValue::from_static("session-a"));
        assert_eq!(
            scope_fingerprint("tools/list", "server-a", &visibility, &headers),
            SCOPE
        );
    }

    #[test]
    fn accepts_python_cursor_and_rejects_scope_expiry_and_tampering() {
        let codec = CursorCodec::new(SECRET).unwrap();
        let cursor = json!(PYTHON_CURSOR);
        assert_eq!(
            codec.decode(&cursor, SCOPE, 0).unwrap(),
            ("00000000000000000000000000000003".into(), 4102444800)
        );
        assert!(codec.decode(&cursor, "other-scope", 0).is_err());
        assert!(codec.decode(&cursor, SCOPE, 4102444800).is_err());
        for invalid in [
            json!(""),
            json!(42),
            json!(true),
            json!("invalid"),
            json!(format!("{PYTHON_CURSOR}=")),
            json!(format!("x{}", &PYTHON_CURSOR[1..])),
        ] {
            assert!(codec.decode(&invalid, SCOPE, 0).is_err());
        }
        assert!(
            CursorCodec::new(b"different-secret")
                .unwrap()
                .decode(&cursor, SCOPE, 0)
                .is_err()
        );
    }

    #[test]
    fn native_cursor_roundtrip() {
        let codec = CursorCodec::new(SECRET).unwrap();
        let cursor = codec.encode(SCOPE, 4102444800, "item-a").unwrap();
        assert_eq!(
            codec.decode(&json!(cursor), SCOPE, 0).unwrap(),
            ("item-a".into(), 4102444800)
        );
    }
}
