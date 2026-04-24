use crate::CompiledValidator;
use pyo3::prelude::*;
use std::path::{Component, Path, PathBuf};

fn has_uri_scheme(path: &str) -> bool {
    let Some((scheme, _rest)) = path.split_once("://") else {
        return false;
    };
    let mut chars = scheme.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_ascii_alphabetic() {
        return false;
    }
    chars.all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '+' | '-' | '.'))
}

pub(crate) fn normalize_absolute_path(absolute: PathBuf) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::Prefix(prefix) => normalized.push(prefix.as_os_str()),
            Component::RootDir => normalized.push(Path::new("/")),
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::Normal(part) => normalized.push(part),
        }
    }

    normalize_windows_verbatim_prefix(normalized)
}

#[cfg(windows)]
fn normalize_windows_verbatim_prefix(path: PathBuf) -> PathBuf {
    let path_string = path.to_string_lossy();

    if let Some(rest) = path_string.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{rest}"));
    }

    if let Some(rest) = path_string.strip_prefix(r"\\?\") {
        return PathBuf::from(rest);
    }

    path
}

#[cfg(not(windows))]
fn normalize_windows_verbatim_prefix(path: PathBuf) -> PathBuf {
    path
}

fn normalize_path(path: &str) -> Result<PathBuf, std::io::Error> {
    let candidate = Path::new(path);
    let absolute = if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        std::env::current_dir()?.join(candidate)
    };

    Ok(normalize_absolute_path(absolute))
}

fn resolve_absolute_path(path: PathBuf, symlink_depth: usize) -> Result<PathBuf, std::io::Error> {
    if symlink_depth > 40 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "too many symlink expansions",
        ));
    }

    let normalized = normalize_absolute_path(path);
    let mut resolved = PathBuf::new();

    for component in normalized.components() {
        match component {
            Component::Prefix(prefix) => resolved.push(prefix.as_os_str()),
            Component::RootDir => resolved.push(Path::new("/")),
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::Normal(part) => {
                let candidate = resolved.join(part);
                match std::fs::symlink_metadata(&candidate) {
                    Ok(metadata) if metadata.file_type().is_symlink() => {
                        let target = std::fs::read_link(&candidate)?;
                        let target_path = if target.is_absolute() {
                            target
                        } else {
                            resolved.join(target)
                        };
                        resolved = resolve_absolute_path(target_path, symlink_depth + 1)?;
                    }
                    Ok(_) => resolved.push(part),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                        resolved.push(part);
                    }
                    Err(error) => return Err(error),
                }
            }
        }
    }

    Ok(normalize_absolute_path(resolved))
}

fn resolve_path(path: &str) -> Result<PathBuf, std::io::Error> {
    resolve_absolute_path(normalize_path(path)?, 0)
}

pub(crate) fn validate_resource_path_impl(
    path: &str,
    validator: &CompiledValidator,
) -> PyResult<String> {
    if has_uri_scheme(path) {
        return Ok(path.to_owned());
    }

    if path.contains('\0') {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Invalid path",
        ));
    }

    if path.contains("..") || path.contains("//") {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Path traversal detected",
        ));
    }

    let resolved_path = resolve_path(path).map_err(|_| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>("invalid_path: Invalid path")
    })?;

    if resolved_path.components().count() > validator.max_path_depth {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Path too deep",
        ));
    }

    if !validator.allowed_roots.is_empty()
        && !validator
            .allowed_roots
            .iter()
            .any(|root| resolved_path.starts_with(root))
    {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Path outside allowed roots",
        ));
    }

    Ok(resolved_path.to_string_lossy().into_owned())
}
