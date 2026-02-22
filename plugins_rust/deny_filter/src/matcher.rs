use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

pub trait Matcher {
    fn is_match(&self, s: &str) -> bool;

    /// Shared logic: Scans a string and returns true if match found
    fn scan_str(&self, txt: &str) -> bool {
        self.is_match(txt)
    }

    /// Shared logic: Scans single level dictionary
    fn scan(&self, args: &Bound<'_, PyDict>) -> bool {
        for value in args.values() {
            if let Ok(value_str) = value.extract::<&str>()
                && self.is_match(value_str)
            {
                return true;
            }
        }
        false
    }

    /// Shared logic: The recursive engine for any Python object
    /// # Errors
    /// * too deep dictionaries, too long patterns probably
    fn scan_any(&self, value: &Bound<'_, PyAny>) -> bool {
        // 1. Check for String
        if let Ok(s) = value.extract::<&str>() {
            if self.is_match(s) {
                return true;
            }
        }
        // 2. Check for Dictionary (using downcast for speed)
        else if let Ok(dict) = value.cast::<PyDict>() {
            for item_value in dict.values() {
                if self.scan_any(&item_value) {
                    return true;
                }
            }
        }
        // 3. Check for List
        else if let Ok(list) = value.cast::<PyList>() {
            for item in list {
                if self.scan_any(&item) {
                    return true;
                }
            }
        }
        false
    }
}
