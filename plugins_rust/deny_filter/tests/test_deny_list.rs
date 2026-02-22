mod test_py_deny_list;

use deny_filter::deny_list::DenyList;
use deny_filter::deny_list_rs::DenyListRs;

use deny_filter::build_error::build_error;
use deny_filter::pymodule::deny_filter as deny_filter_mod;
use pyo3::PyResult;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

const DENY_WORDS: &[&str] = &["ASDF", "JKL"];
const BLOCK_PROMPT: &str = "111  asdf 222";
const OK_PROMPT: &str = "111 222 333";

fn common_test_logic<T: deny_filter::matcher::Matcher>(deny_list: &T, py: Python) {
    assert!(deny_list.is_match("111  asdf  222"));
    assert!(deny_list.is_match("111  asdf  222 jkl"));
    assert!(!deny_list.is_match("111 222"));

    // test blocked prompts

    assert!(deny_list.scan_str(BLOCK_PROMPT));

    let list_data: Vec<String> = BLOCK_PROMPT
        .split(' ')
        .map(std::string::ToString::to_string)
        .collect();
    let list = PyList::new(py, list_data).unwrap();
    assert!(deny_list.scan_any(&list));

    let dict = PyDict::new(py);
    dict.set_item("user", BLOCK_PROMPT).unwrap();
    // should not scan non-string, improves test coverage
    dict.set_item("id", 1).unwrap();

    assert!(deny_list.scan(&dict));
    assert!(deny_list.scan_any(&dict));

    // test non blocked prompts
    assert!(!deny_list.scan_str(OK_PROMPT));

    dict.clear();
    dict.set_item("user", OK_PROMPT).unwrap();
    // should not scan non-string, improves test coverage
    dict.set_item("id", 1).unwrap();
    assert!(!deny_list.scan(&dict));
    assert!(!deny_list.scan_any(&dict));

    let list_data: Vec<String> = OK_PROMPT
        .split(' ')
        .map(std::string::ToString::to_string)
        .collect();
    let list = PyList::new(py, &list_data).unwrap();

    assert!(!deny_list.scan_any(&list));
}

#[test]
fn test_deny_lists() -> PyResult<()> {
    let words: Vec<String> = DENY_WORDS
        .iter()
        .map(std::string::ToString::to_string)
        .collect();
    let deny_list = DenyList::new(words.clone())?;
    let deny_list_rs = DenyListRs::new(words.clone())?;

    Python::initialize();
    Python::attach(|py| {
        common_test_logic(&deny_list, py);
        common_test_logic(&deny_list_rs, py);
        let module = PyModule::new(py, "modules").unwrap();
        deny_filter_mod(&module).unwrap();
    });

    let dummy_error = "mock error";
    let py_err = build_error(dummy_error);
    assert!(py_err.to_string().contains("mock error"));

    Ok(())
}
