pub enum AuthConfig {
    Bearer(String),
    ApiKey {
        header: String,
        value: String,
    },
    OAuth {
        token_url: String,
        client_id: String,
        client_secret: String,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_auth_config_bearer() {
        let _ = AuthConfig::Bearer("token123".to_string());
    }

    #[test]
    fn test_auth_config_api_key() {
        let _ = AuthConfig::ApiKey {
            header: "X-API-Key".to_string(),
            value: "secret".to_string(),
        };
    }

    #[test]
    fn test_auth_config_oauth() {
        let _ = AuthConfig::OAuth {
            token_url: "https://auth.example.com/token".to_string(),
            client_id: "client".to_string(),
            client_secret: "secret".to_string(),
        };
    }
}
