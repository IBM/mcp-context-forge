use crate::CompiledValidator;
use crate::matcher::{ValidationFailure, validate_string};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::fmt;

const MAX_JSON_DEPTH: usize = 1024;
const FAILURE_PREFIX: &str = "__validation_failure__:";
const DEPTH_PREFIX: &str = "__validation_depth__";

enum StreamStop {
    Failure(String, String),
    MaxDepth,
    InvalidJson(String),
}

fn stream_stop_error<E>(stop: StreamStop) -> E
where
    E: de::Error,
{
    match stop {
        StreamStop::Failure(key, error_type) => {
            E::custom(format!("{FAILURE_PREFIX}{key}:{error_type}"))
        }
        StreamStop::MaxDepth => E::custom(DEPTH_PREFIX),
        StreamStop::InvalidJson(message) => E::custom(message),
    }
}

fn parse_stream_stop(error: serde_json::Error) -> StreamStop {
    let message = error.to_string();
    if let Some(rest) = message.strip_prefix(FAILURE_PREFIX) {
        if let Some((key, error_type)) = rest.rsplit_once(':') {
            let normalized_error_type = error_type
                .split(" at line ")
                .next()
                .unwrap_or(error_type)
                .to_owned();
            return StreamStop::Failure(key.to_owned(), normalized_error_type);
        }
    }
    if message.starts_with(DEPTH_PREFIX) {
        return StreamStop::MaxDepth;
    }
    StreamStop::InvalidJson(message)
}

struct ValueSeed<'a> {
    validator: &'a CompiledValidator,
    depth: usize,
    key_context: Option<&'a str>,
    list_item_context: bool,
}

struct ValueVisitor<'a> {
    seed: ValueSeed<'a>,
}

impl<'de, 'a> DeserializeSeed<'de> for ValueSeed<'a> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: de::Deserializer<'de>,
    {
        if self.depth > MAX_JSON_DEPTH {
            return Err(stream_stop_error(StreamStop::MaxDepth));
        }

        deserializer.deserialize_any(ValueVisitor { seed: self })
    }
}

impl<'de, 'a> Visitor<'de> for ValueVisitor<'a> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value")
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_i64<E>(self, _value: i64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_u64<E>(self, _value: u64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        if let Some(result) = validate_string(value, self.seed.validator) {
            let key = if self.seed.list_item_context {
                "list_item".to_owned()
            } else {
                self.seed.key_context.unwrap_or("payload").to_owned()
            };
            let error_type = match result {
                ValidationFailure::MaxLength => "max_length".to_owned(),
                ValidationFailure::DangerousPattern => "dangerous_pattern".to_owned(),
            };
            return Err(stream_stop_error(StreamStop::Failure(key, error_type)));
        }

        Ok(())
    }

    fn visit_borrowed_str<E>(self, value: &'de str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        self.visit_str(value)
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        self.visit_str(&value)
    }

    fn visit_seq<A>(self, mut seq: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let child_seed = ValueSeed {
            validator: self.seed.validator,
            depth: self.seed.depth + 1,
            key_context: None,
            list_item_context: true,
        };

        while seq.next_element_seed(child_seed.reborrow())?.is_some() {}
        Ok(())
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        while let Some(key) = map.next_key::<String>()? {
            map.next_value_seed(ValueSeed {
                validator: self.seed.validator,
                depth: self.seed.depth + 1,
                key_context: Some(key.as_str()),
                list_item_context: false,
            })?;
        }
        Ok(())
    }
}

impl<'a> ValueSeed<'a> {
    fn reborrow<'b>(&'b self) -> ValueSeed<'b> {
        ValueSeed {
            validator: self.validator,
            depth: self.depth,
            key_context: self.key_context,
            list_item_context: self.list_item_context,
        }
    }
}

pub(crate) fn validate_json_bytes_streaming(
    raw_body: &[u8],
    validator: &CompiledValidator,
) -> PyResult<Option<(String, String)>> {
    let mut deserializer = serde_json::Deserializer::from_slice(raw_body);
    deserializer.disable_recursion_limit();
    let streaming_result = {
        let deserializer = serde_stacker::Deserializer::new(&mut deserializer);

        (ValueSeed {
            validator,
            depth: 0,
            key_context: None,
            list_item_context: false,
        })
        .deserialize(deserializer)
    };

    match streaming_result {
        Ok(()) => match deserializer.end() {
            Ok(()) => Ok(None),
            Err(error) => match parse_stream_stop(error) {
                StreamStop::Failure(key, error_type) => Ok(Some((key, error_type))),
                StreamStop::MaxDepth => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                    "JSON payload exceeds maximum supported nesting depth",
                )),
                StreamStop::InvalidJson(message) => {
                    Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "Request body contains invalid JSON: {message}"
                    )))
                }
            },
        },
        Err(error) => match parse_stream_stop(error) {
            StreamStop::Failure(key, error_type) => Ok(Some((key, error_type))),
            StreamStop::MaxDepth => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "JSON payload exceeds maximum supported nesting depth",
            )),
            StreamStop::InvalidJson(message) => {
                Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Request body contains invalid JSON: {message}"
                )))
            }
        },
    }
}

pub(crate) fn walk_json_like(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    validator: &CompiledValidator,
) -> PyResult<Option<(String, String)>> {
    let mut stack = vec![(data.clone().unbind(), 0usize)];

    while let Some((item, depth)) = stack.pop() {
        if depth > MAX_JSON_DEPTH {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "JSON payload exceeds maximum supported nesting depth",
            ));
        }

        let bound_item = item.bind(py);

        if let Ok(dict) = bound_item.cast::<PyDict>() {
            for (key, value) in dict.iter() {
                if let Ok(value_string) = value.cast::<PyString>() {
                    if let Some(result) = validate_string(value_string.to_str()?, validator) {
                        let key_string = key.str()?.to_string_lossy().into_owned();
                        let error_type = match result {
                            ValidationFailure::MaxLength => "max_length",
                            ValidationFailure::DangerousPattern => "dangerous_pattern",
                        };
                        return Ok(Some((key_string, error_type.to_owned())));
                    }
                } else if value.is_instance_of::<PyDict>() || value.is_instance_of::<PyList>() {
                    stack.push((value.unbind(), depth + 1));
                }
            }
            continue;
        }

        if let Ok(list) = bound_item.cast::<PyList>() {
            for child in list.iter().rev() {
                if child.is_instance_of::<PyDict>() || child.is_instance_of::<PyList>() {
                    stack.push((child.unbind(), depth + 1));
                } else if let Ok(value_string) = child.cast::<PyString>() {
                    if let Some(result) = validate_string(value_string.to_str()?, validator) {
                        let error_type = match result {
                            ValidationFailure::MaxLength => "max_length",
                            ValidationFailure::DangerousPattern => "dangerous_pattern",
                        };
                        return Ok(Some(("list_item".to_owned(), error_type.to_owned())));
                    }
                }
            }
        }
    }

    Ok(None)
}
