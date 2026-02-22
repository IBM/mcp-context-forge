use deny_filter::deny_list::DenyList;
use deny_filter::deny_list_rs::DenyListRs;
use pyo3::prelude::*;

macro_rules! test_matcher_variant {
    ($struct_name:ident, $test_fn_name:ident) => {
        #[test]
        fn $test_fn_name() {
            Python::initialize();
            Python::attach(|py| {
                let words = vec!["BADWORD".to_string()];
                let matcher = $struct_name::new(words).unwrap();

                assert!(matcher.is_match("badword"));
                assert!(matcher.scan_str("badword"));

                let dict = pyo3::types::PyDict::new(py);
                dict.set_item("key", "badword").unwrap();
                assert!(matcher.scan(&dict));

                let list = pyo3::types::PyList::new(py, vec!["badword"]).unwrap();
                assert!(matcher.scan_any(list.as_any()));
            });
        }
    };
}

test_matcher_variant!(DenyList, test_denylist_coverage);
test_matcher_variant!(DenyListRs, test_denylist_rs_coverage);
