use actson::feeder::SliceJsonFeeder;
use actson::{JsonEvent, JsonParser};
use jsonrpc_core::Id;
use tracing::error;

#[must_use]
pub fn parse_id_fast(json: &[u8]) -> Id {
    parse_field_fast(json, "id")
}
#[must_use]
pub fn parse_field_fast(json: &[u8], field_name: &str) -> Id {
    let feeder = SliceJsonFeeder::new(json);
    let mut parser = JsonParser::new(feeder);
    let mut depth = 0;

    while let Ok(Some(event)) = parser.next_event() {
        match event {
            JsonEvent::StartObject | JsonEvent::StartArray => {
                depth += 1;
                // If we are already deep, skip this whole container
                if depth > 1 {
                    skip_container(&mut parser);
                    depth -= 1; // Correct the depth after skipping
                }
            }
            JsonEvent::EndObject | JsonEvent::EndArray => {
                depth -= 1;
                if depth == 0 {
                    break;
                }
            }
            JsonEvent::FieldName => {
                if depth == 1 && parser.current_str().is_ok_and(|name| name == field_name) {
                    // Get the very next event (the value)
                    if let Ok(Some(val_event)) = parser.next_event() {
                        match parser.current_str() {
                            Ok(s) => return to_id(&val_event, s),
                            Err(e) => {
                                error!("Invalid string: {e}");
                            }
                        }
                    }
                }
            }
            _ => {}
        }
    }
    Id::Null
}

/// Skips a container entirely.
/// When this starts, we just consumed StartObject/StartArray.
fn skip_container(parser: &mut JsonParser<SliceJsonFeeder>) {
    let mut skip_depth = 1;
    while skip_depth > 0 {
        if let Ok(Some(sub_event)) = parser.next_event() {
            match sub_event {
                JsonEvent::StartObject | JsonEvent::StartArray => skip_depth += 1,
                JsonEvent::EndObject | JsonEvent::EndArray => skip_depth -= 1,
                _ => {}
            }
        } else {
            break;
        }
    }
}

pub fn to_id(event: &JsonEvent, value_str: &str) -> Id {
    match event {
        JsonEvent::ValueInt => value_str.parse::<u64>().map(Id::Num).unwrap_or(Id::Null),
        JsonEvent::ValueString => Id::Str(value_str.to_string()),
        //JsonEvent::ValueNull => Id::Null, clippy does not like this
        _ => Id::Null,
    }
}
