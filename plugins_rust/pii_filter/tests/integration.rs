// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Integration tests for Rust PII filter with PyO3 bindings

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use std::env;
use std::path::PathBuf;

fn add_extension_module_path(py: Python<'_>) -> PyResult<()> {
    let target_root = env::var("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target"));

    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    let profile_dir = target_root.join(profile);

    let mut candidates = vec![profile_dir.clone(), profile_dir.join("deps")];

    // If the build directory differs (e.g., release artifacts while tests run in debug), include both.
    let alternate_profile = if profile == "debug" {
        "release"
    } else {
        "debug"
    };
    let alternate_dir = target_root.join(alternate_profile);
    candidates.push(alternate_dir.clone());
    candidates.push(alternate_dir.join("deps"));

    let sys = py.import("sys")?;
    let sys_path = sys.getattr("path")?.cast::<PyList>()?;

    for path in candidates {
        if !path.exists() {
            continue;
        }
        let path_str = path.to_string_lossy();
        let py_path = PyString::new(py, &path_str);
        if !sys_path.contains(py_path)? {
            sys_path.append(py_path)?;
        }
    }

    Ok(())
}

fn import_rust_detector(py: Python<'_>) -> PyResult<&PyAny> {
    add_extension_module_path(py)?;
    let module = py.import("plugins_rust")?;
    module.getattr("PIIDetectorRust")
}

fn build_detector(py: Python<'_>, config: &PyDict) -> PyResult<PyObject> {
    let detector_class = import_rust_detector(py)?;
    Ok(detector_class.call1((config,))?.into())
}

/// Helper to create a Python config dict
fn create_test_config(py: Python<'_>) -> &PyDict {
    let config = PyDict::new(py);

    // Enable all detectors
    config.set_item("detect_ssn", true).unwrap();
    config.set_item("detect_credit_card", true).unwrap();
    config.set_item("detect_email", true).unwrap();
    config.set_item("detect_phone", true).unwrap();
    config.set_item("detect_ip_address", true).unwrap();
    config.set_item("detect_date_of_birth", true).unwrap();
    config.set_item("detect_passport", true).unwrap();
    config.set_item("detect_driver_license", true).unwrap();
    config.set_item("detect_bank_account", true).unwrap();
    config.set_item("detect_medical_record", true).unwrap();
    config.set_item("detect_aws_key", true).unwrap();
    config.set_item("detect_api_key", true).unwrap();

    // Masking configuration
    config.set_item("default_mask_strategy", "partial").unwrap();
    config.set_item("redaction_text", "[REDACTED]").unwrap();
    config
        .set_item("custom_patterns", Vec::<String>::new())
        .unwrap();
    config
        .set_item("whitelist_patterns", Vec::<String>::new())
        .unwrap();

    config
}

#[test]
fn test_detector_initialization() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).expect("Failed to create detector");
        assert!(detector.as_ref(py).is_instance_of::<PyAny>());
    });
}

#[test]
fn test_ssn_detection() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        // Test SSN detection
        let text = "My SSN is 123-45-6789";
        let result = detector
            .call_method1(py, "detect", (text,))
            .expect("detect() failed");

        // Check that SSN was detected
        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("ssn").unwrap());

        let ssn_list = detections
            .get_item("ssn")
            .unwrap()
            .unwrap()
            .cast::<PyList>()
            .unwrap();
        assert_eq!(ssn_list.len(), 1);

        let detection = ssn_list.get_item(0).unwrap().cast::<PyDict>().unwrap();
        assert_eq!(
            detection
                .get_item("value")
                .unwrap()
                .unwrap()
                .extract::<String>()
                .unwrap(),
            "123-45-6789"
        );
    });
}

#[test]
fn test_email_detection() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "Contact me at john.doe@example.com";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("email").unwrap());

        let email_list = detections
            .get_item("email")
            .unwrap()
            .unwrap()
            .cast::<PyList>()
            .unwrap();
        assert_eq!(email_list.len(), 1);
    });
}

#[test]
fn test_credit_card_detection() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "Credit card: 4111-1111-1111-1111";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("credit_card").unwrap());
    });
}

#[test]
fn test_phone_detection() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "Call me at (555) 123-4567";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("phone").unwrap());
    });
}

#[test]
fn test_masking() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "SSN: 123-45-6789";
        let detections = detector.call_method1(py, "detect", (text,)).unwrap();
        let masked = detector
            .call_method1(py, "mask", (text, detections))
            .unwrap();

        let masked_str = masked.as_ref(py).extract::<String>().unwrap();
        assert!(masked_str.contains("***-**-6789"));
        assert!(!masked_str.contains("123-45-6789"));
    });
}

#[test]
fn test_multiple_pii_types() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "SSN: 123-45-6789, Email: john@example.com, Phone: 555-1234";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("ssn").unwrap());
        assert!(detections.contains("email").unwrap());
        assert!(detections.contains("phone").unwrap());
    });
}

#[test]
fn test_nested_data_processing() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        // Create nested structure
        let inner_dict = PyDict::new(py);
        inner_dict.set_item("ssn", "123-45-6789").unwrap();
        inner_dict.set_item("name", "John Doe").unwrap();

        let outer_dict = PyDict::new(py);
        outer_dict.set_item("user", inner_dict).unwrap();

        // Process nested data
        let result = detector
            .call_method1(py, "process_nested", (outer_dict, ""))
            .expect("process_nested failed");

        // Result is tuple: (modified, new_data, detections)
        let result_tuple = result.cast::<pyo3::types::PyTuple>(py).unwrap();
        assert_eq!(result_tuple.len(), 3);

        let modified = result_tuple.get_item(0).unwrap().extract::<bool>().unwrap();
        assert!(modified, "Should have detected and masked PII");

        let new_data = result_tuple.get_item(1).unwrap();
        let new_outer = new_data.cast::<PyDict>().unwrap();
        let new_inner = new_outer
            .get_item("user")
            .unwrap()
            .unwrap()
            .cast::<PyDict>()
            .unwrap();

        let masked_ssn = new_inner
            .get_item("ssn")
            .unwrap()
            .unwrap()
            .extract::<String>()
            .unwrap();

        assert!(masked_ssn.contains("***-**-6789"));
        assert!(!masked_ssn.contains("123-45-6789"));
    });
}

#[test]
fn test_nested_list_processing() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        // Create list with PII
        let list = PyList::new(
            py,
            ["SSN: 123-45-6789", "No PII here", "Email: test@example.com"],
        );

        let result = detector
            .call_method1(py, "process_nested", (list, ""))
            .expect("process_nested failed");

        let result_tuple = result.cast::<pyo3::types::PyTuple>(py).unwrap();
        let modified = result_tuple.get_item(0).unwrap().extract::<bool>().unwrap();
        assert!(modified);

        let new_list = result_tuple.get_item(1).unwrap().cast::<PyList>().unwrap();
        let first_item = new_list.get_item(0).unwrap().extract::<String>().unwrap();
        assert!(first_item.contains("***-**-6789"));
    });
}

#[test]
fn test_aws_key_detection() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "AWS Key: AKIAIOSFODNN7EXAMPLE";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("aws_key").unwrap());
    });
}

#[test]
fn test_no_detection_when_disabled() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = PyDict::new(py);
        config.set_item("detect_ssn", false).unwrap();
        config.set_item("detect_credit_card", false).unwrap();
        config.set_item("detect_email", false).unwrap();
        config.set_item("detect_phone", false).unwrap();
        config.set_item("detect_ip_address", false).unwrap();
        config.set_item("detect_date_of_birth", false).unwrap();
        config.set_item("detect_passport", false).unwrap();
        config.set_item("detect_driver_license", false).unwrap();
        config.set_item("detect_bank_account", false).unwrap();
        config.set_item("detect_medical_record", false).unwrap();
        config.set_item("detect_aws_key", false).unwrap();
        config.set_item("detect_api_key", false).unwrap();
        config.set_item("default_mask_strategy", "partial").unwrap();
        config.set_item("redaction_text", "[REDACTED]").unwrap();
        config
            .set_item("custom_patterns", Vec::<String>::new())
            .unwrap();
        config
            .set_item("whitelist_patterns", Vec::<String>::new())
            .unwrap();

        let detector = build_detector(py, config).unwrap();

        let text = "SSN: 123-45-6789, Email: test@example.com";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert_eq!(
            detections.len(),
            0,
            "Should not detect any PII when all disabled"
        );
    });
}

#[test]
fn test_whitelist_patterns() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);

        // Add whitelist pattern
        let whitelist = PyList::new(py, ["test@example\\.com"]);
        config.set_item("whitelist_patterns", whitelist).unwrap();

        let detector = build_detector(py, config).unwrap();

        let text = "Email: test@example.com, Other: john@test.com";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();

        if detections.contains("email").unwrap() {
            let email_list = detections
                .get_item("email")
                .unwrap()
                .unwrap()
                .cast::<PyList>()
                .unwrap();

            // Should only detect john@test.com, not test@example.com (whitelisted)
            for i in 0..email_list.len() {
                let detection = email_list.get_item(i).unwrap().cast::<PyDict>().unwrap();
                let value = detection
                    .get_item("value")
                    .unwrap()
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                assert_ne!(
                    value, "test@example.com",
                    "Whitelisted email should not be detected"
                );
            }
        }
    });
}

#[test]
fn test_empty_string() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        let text = "";
        let result = detector.call_method1(py, "detect", (text,)).unwrap();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert_eq!(detections.len(), 0);
    });
}

#[test]
fn test_large_text_performance() {
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|py| {
        let config = create_test_config(py);
        let detector = build_detector(py, config).unwrap();

        // Create large text with multiple PII instances
        let mut text = String::new();
        for i in 0..1000 {
            text.push_str(&format!(
                "User {}: SSN 123-45-{:04}, Email user{}@example.com\n",
                i, i, i
            ));
        }

        let start = std::time::Instant::now();
        let result = detector
            .call_method1(py, "detect", (text.as_str(),))
            .unwrap();
        let duration = start.elapsed();

        let detections = result.cast::<PyDict>(py).unwrap();
        assert!(detections.contains("ssn").unwrap());
        assert!(detections.contains("email").unwrap());

        println!("Processed {} bytes in {:?}", text.len(), duration);
        assert!(
            duration.as_millis() < 1000,
            "Should process 1000 PII instances in under 1 second"
        );
    });
}
