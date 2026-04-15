pub(crate) fn save_generated_template(
    root: &Path,
    scenarios: &mut Vec<SuiteSummary>,
    generator: &GeneratorState,
) -> AppResult<PathBuf> {
    let file_stem = sanitize_file_stem(generator.get("file_stem"));
    let target = root
        .join("crates/contextforge_benchmark_runner/assets/scenarios")
        .join(format!("{file_stem}.toml"));
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&target, generate_template_toml(generator))?;
    *scenarios = discover_scenarios(root)?;
    Ok(target)
}

fn sanitize_file_stem(value: &str) -> String {
    let mut stem = value
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string();
    if stem.is_empty() {
        stem = "generated-scenario".to_string();
    }
    stem
}

pub(crate) fn parse_pipe_lines(value: &str) -> Vec<String> {
    value
        .split('|')
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn parse_csv_items(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(ToString::to_string)
        .collect()
}

pub(crate) fn quoted_csv(value: &str) -> String {
    parse_csv_items(value)
        .into_iter()
        .map(|item| format!("\"{}\"", escape_toml(&item)))
        .collect::<Vec<_>>()
        .join(", ")
}

pub(crate) fn push_string_line(lines: &mut Vec<String>, key: &str, value: &str) {
    lines.push(format!("{key} = \"{}\"", escape_toml(value)));
}

pub(crate) fn push_bool_line(lines: &mut Vec<String>, key: &str, value: &str) {
    lines.push(format!(
        "{key} = {}",
        if value == "true" { "true" } else { "false" }
    ));
}

pub(crate) fn push_scalar_line(lines: &mut Vec<String>, key: &str, value: &str) {
    lines.push(format!("{key} = {value}"));
}

pub(crate) fn push_optional_string_line(lines: &mut Vec<String>, key: &str, value: &str) {
    if !value.trim().is_empty() {
        push_string_line(lines, key, value.trim());
    }
}

pub(crate) fn push_optional_scalar_line(lines: &mut Vec<String>, key: &str, value: &str) {
    if !value.trim().is_empty() {
        push_scalar_line(lines, key, value.trim());
    }
}

pub(crate) fn push_optional_array_line(lines: &mut Vec<String>, key: &str, value: &str) {
    let items = quoted_csv(value);
    if !items.is_empty() {
        lines.push(format!("{key} = [{items}]"));
    }
}

pub(crate) fn append_optional_block(lines: &mut Vec<String>, title: &str, raw: &str) {
    let entries = parse_pipe_lines(raw);
    if !entries.is_empty() {
        lines.push(String::new());
        lines.push(title.to_string());
        lines.extend(entries);
    }
}

pub(crate) fn append_runtime_block_from_fields(
    lines: &mut Vec<String>,
    title: &str,
    fields: &[(&str, &str, &str)],
) {
    let mut block = Vec::new();
    for (key, value, kind) in fields {
        if value.trim().is_empty() {
            continue;
        }
        match *kind {
            "bool" => push_bool_line(&mut block, key, value),
            "string" => push_string_line(&mut block, key, value.trim()),
            _ => push_scalar_line(&mut block, key, value.trim()),
        }
    }
    if !block.is_empty() {
        lines.push(String::new());
        lines.push(title.to_string());
        lines.extend(block);
    }
}
use crate::main_parts::*;
use crate::*;
