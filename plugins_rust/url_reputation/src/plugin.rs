// use pyo3::prelude::*;
use url::{Url};
use anyhow::{Context, Result};

// assert!(issue_list_url.scheme() == "https");
// assert!(issue_list_url.username() == "");
// assert!(issue_list_url.password() == None);
// assert!(issue_list_url.host_str() == Some("github.com"));
// assert!(issue_list_url.host() == Some(Host::Domain("github.com")));
// assert!(issue_list_url.port() == None);
// assert!(issue_list_url.path() == "/rust-lang/rust/issues");
// assert!(issue_list_url.path_segments().map(|c| c.collect::<Vec<_>>()) ==
//         Some(vec!["rust-lang", "rust", "issues"]));
// assert!(issue_list_url.query() == Some("labels=E-easy&state=open"));
// assert!(&issue_list_url[Position::BeforePath..] == "/rust-lang/rust/issues?labels=E-easy&state=open");
// assert!(issue_list_url.fragment() == None);
// assert!(!issue_list_url.cannot_be_a_base());




pub fn is_valid(url: &str) -> Result<bool> {
    let _parse_url = Url::parse(&url.trim().to_lowercase()).with_context(|| format!("Could not process url: {}", url))?;
    
    Ok(true)
}


