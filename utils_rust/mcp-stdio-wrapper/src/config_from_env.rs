use crate::config::Config;
/// implements config init
impl Config {
    /// loads config from env vars
    #[allow(dead_code)]
    pub fn from_env() -> Self {
        dotenvy::dotenv().ok();
        envy::from_env().expect("Failed to load config.")
    }
}
