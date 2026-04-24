use crate::matcher::{ValidationFailure, validate_string};
use crate::{CompiledValidator, InvalidJsonError, JsonDepthError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::borrow::Cow;
use std::fmt;

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
    // serde_json only exposes visitor aborts through its Error type. Keep the
    // string sentinel isolated here and parse it back into StreamStop once.
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

struct ValueSeed<'a, 'k> {
    validator: &'a CompiledValidator,
    depth: usize,
    key_context: Option<Cow<'k, str>>,
    list_item_context: bool,
}

struct ValueVisitor<'a, 'k> {
    seed: ValueSeed<'a, 'k>,
}

impl<'de, 'a, 'k> DeserializeSeed<'de> for ValueSeed<'a, 'k> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: de::Deserializer<'de>,
    {
        deserializer.deserialize_any(ValueVisitor { seed: self })
    }
}

impl<'de, 'a, 'k> Visitor<'de> for ValueVisitor<'a, 'k> {
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
                self.seed
                    .key_context
                    .as_deref()
                    .unwrap_or("payload")
                    .to_owned()
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
        if self.seed.depth >= self.seed.validator.max_json_depth {
            return Err(stream_stop_error(StreamStop::MaxDepth));
        }

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
        if self.seed.depth >= self.seed.validator.max_json_depth {
            return Err(stream_stop_error(StreamStop::MaxDepth));
        }

        while let Some(key) = map.next_key::<Cow<'de, str>>()? {
            map.next_value_seed(ValueSeed {
                validator: self.seed.validator,
                depth: self.seed.depth + 1,
                key_context: Some(key),
                list_item_context: false,
            })?;
        }
        Ok(())
    }
}

impl<'a, 'k> ValueSeed<'a, 'k> {
    fn reborrow<'b>(&'b self) -> ValueSeed<'b, 'k> {
        ValueSeed {
            validator: self.validator,
            depth: self.depth,
            key_context: self.key_context.clone(),
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
                StreamStop::MaxDepth => Err(PyErr::new::<JsonDepthError, _>(
                    "JSON payload exceeds maximum supported nesting depth",
                )),
                StreamStop::InvalidJson(message) => Err(PyErr::new::<InvalidJsonError, _>(
                    format!("Request body contains invalid JSON: {message}"),
                )),
            },
        },
        Err(error) => match parse_stream_stop(error) {
            StreamStop::Failure(key, error_type) => Ok(Some((key, error_type))),
            StreamStop::MaxDepth => Err(PyErr::new::<JsonDepthError, _>(
                "JSON payload exceeds maximum supported nesting depth",
            )),
            StreamStop::InvalidJson(message) => Err(PyErr::new::<InvalidJsonError, _>(format!(
                "Request body contains invalid JSON: {message}"
            ))),
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
        let bound_item = item.bind(py);

        if let Ok(value_string) = bound_item.cast::<PyString>() {
            if let Some(result) = validate_string(value_string.to_str()?, validator) {
                return Ok(Some((
                    "payload".to_owned(),
                    validation_failure_type(result).to_owned(),
                )));
            }
            continue;
        }

        if let Ok(dict) = bound_item.cast::<PyDict>() {
            if depth >= validator.max_json_depth {
                return Err(PyErr::new::<JsonDepthError, _>(
                    "JSON payload exceeds maximum supported nesting depth",
                ));
            }

            for (key, value) in dict.iter() {
                if let Ok(value_string) = value.cast::<PyString>() {
                    if let Some(result) = validate_string(value_string.to_str()?, validator) {
                        let key_string = key.str()?.to_string_lossy().into_owned();
                        return Ok(Some((
                            key_string,
                            validation_failure_type(result).to_owned(),
                        )));
                    }
                } else if value.is_instance_of::<PyDict>() || value.is_instance_of::<PyList>() {
                    stack.push((value.unbind(), depth + 1));
                }
            }
            continue;
        }

        if let Ok(list) = bound_item.cast::<PyList>() {
            if depth >= validator.max_json_depth {
                return Err(PyErr::new::<JsonDepthError, _>(
                    "JSON payload exceeds maximum supported nesting depth",
                ));
            }

            for child in list.iter().rev() {
                if child.is_instance_of::<PyDict>() || child.is_instance_of::<PyList>() {
                    stack.push((child.unbind(), depth + 1));
                } else if let Ok(value_string) = child.cast::<PyString>() {
                    if let Some(result) = validate_string(value_string.to_str()?, validator) {
                        return Ok(Some((
                            "list_item".to_owned(),
                            validation_failure_type(result).to_owned(),
                        )));
                    }
                }
            }
        }
    }

    Ok(None)
}

fn validation_failure_type(failure: ValidationFailure) -> &'static str {
    match failure {
        ValidationFailure::MaxLength => "max_length",
        ValidationFailure::DangerousPattern => "dangerous_pattern",
    }
}
