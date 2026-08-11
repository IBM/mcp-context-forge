use std::collections::{BTreeMap, btree_map::Entry};

use crate::error::LauncherError;

const BLOCK: usize = 512;
const MAX_EXTRACTED_BYTES: usize = 64 * 1024 * 1024;
const MAX_REGULAR_FILES: usize = 64;
const MAX_PATH_BYTES: usize = 240;

pub(super) fn parse_entries(archive: &[u8]) -> Result<BTreeMap<String, Vec<u8>>, LauncherError> {
    validate_framing(archive)?;
    let mut entries = BTreeMap::new();
    let mut extracted = 0usize;
    let mut offset = 0usize;
    let mut prior_path: Option<String> = None;
    while offset < archive.len() - BLOCK * 2 {
        if entries.len() == MAX_REGULAR_FILES {
            return Err(LauncherError::LocalStore("archive contains too many files"));
        }
        let header = &archive[offset..offset + BLOCK];
        let path = header_path(header)?;
        validate_path(&path)?;
        let size = canonical_octal(&header[124..136], 11)?;
        let start = offset
            .checked_add(BLOCK)
            .ok_or(LauncherError::LocalStore("archive offset overflow"))?;
        let end = start
            .checked_add(size)
            .ok_or(LauncherError::LocalStore("archive size overflow"))?;
        if end > archive.len() - BLOCK * 2 {
            return Err(LauncherError::ArtifactTruncated);
        }
        extracted = extracted
            .checked_add(size)
            .ok_or(LauncherError::LocalStore("extracted size overflow"))?;
        if extracted > MAX_EXTRACTED_BYTES {
            return Err(LauncherError::LocalStore("extracted content exceeds limit"));
        }
        let content = &archive[start..end];
        if content.is_empty() || std::str::from_utf8(content).is_err() {
            return Err(LauncherError::LocalStore(
                "archive document is not valid UTF-8",
            ));
        }
        if canonical_header(&path, content)? != header {
            return Err(LauncherError::LocalStore("archive member is noncanonical"));
        }
        match entries.entry(path) {
            Entry::Occupied(_) => {
                return Err(LauncherError::LocalStore(
                    "archive contains duplicate paths",
                ));
            }
            Entry::Vacant(entry) => {
                if prior_path
                    .as_deref()
                    .is_some_and(|prior| entry.key().as_str() <= prior)
                {
                    return Err(LauncherError::LocalStore(
                        "archive paths are not strictly sorted",
                    ));
                }
                prior_path = Some(entry.key().clone());
                entry.insert(content.to_vec());
            }
        }
        let padded = size.div_ceil(BLOCK) * BLOCK;
        if archive[end..start + padded].iter().any(|byte| *byte != 0) {
            return Err(LauncherError::LocalStore("archive padding is noncanonical"));
        }
        offset = start + padded;
    }
    if offset != archive.len() - BLOCK * 2 {
        return Err(LauncherError::LocalStore("archive framing is noncanonical"));
    }
    Ok(entries)
}

pub(super) fn validate_path(path: &str) -> Result<(), LauncherError> {
    if path.is_empty()
        || path.len() > MAX_PATH_BYTES
        || path.starts_with('/')
        || path.contains(['\\', '\0'])
        || path
            .split('/')
            .any(|part| part.is_empty() || matches!(part, "." | ".."))
    {
        return Err(LauncherError::LocalStore("archive path is not canonical"));
    }
    Ok(())
}

fn validate_framing(archive: &[u8]) -> Result<(), LauncherError> {
    if archive.len() > crate::artifact::MAX_ARTIFACT_BYTES
        || archive.len() < BLOCK * 3
        || archive.len() % BLOCK != 0
        || archive[archive.len() - BLOCK * 2..]
            .iter()
            .any(|byte| *byte != 0)
        || archive[archive.len() - BLOCK * 3..archive.len() - BLOCK * 2]
            .iter()
            .all(|byte| *byte == 0)
    {
        return Err(LauncherError::LocalStore("archive framing is noncanonical"));
    }
    Ok(())
}

fn header_path(header: &[u8]) -> Result<String, LauncherError> {
    let name = nul_field(&header[..100])?;
    let prefix = nul_field(&header[345..500])?;
    if prefix.is_empty() {
        Ok(name.to_owned())
    } else {
        Ok(format!("{prefix}/{name}"))
    }
}

fn nul_field(field: &[u8]) -> Result<&str, LauncherError> {
    let end = field
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(field.len());
    if field[end..].iter().any(|byte| *byte != 0) {
        return Err(LauncherError::LocalStore(
            "archive header text is noncanonical",
        ));
    }
    std::str::from_utf8(&field[..end])
        .map_err(|_| LauncherError::LocalStore("archive header text is invalid"))
}

fn canonical_octal(field: &[u8], digits: usize) -> Result<usize, LauncherError> {
    if field.len() != digits + 1
        || field[digits] != 0
        || !field[..digits].iter().all(u8::is_ascii_digit)
    {
        return Err(LauncherError::LocalStore(
            "archive numeric field is noncanonical",
        ));
    }
    usize::from_str_radix(std::str::from_utf8(&field[..digits]).unwrap_or(""), 8)
        .map_err(|_| LauncherError::LocalStore("archive numeric field is invalid"))
}

fn canonical_header(path: &str, content: &[u8]) -> Result<[u8; BLOCK], LauncherError> {
    let (prefix, name) = split_ustar_path(path)?;
    let mut header = [0u8; BLOCK];
    header[..name.len()].copy_from_slice(name.as_bytes());
    header[100..108].copy_from_slice(b"0000600\0");
    header[108..116].copy_from_slice(b"0000000\0");
    header[116..124].copy_from_slice(b"0000000\0");
    header[124..136].copy_from_slice(format!("{:011o}\0", content.len()).as_bytes());
    header[136..148].copy_from_slice(b"00000000000\0");
    header[148..156].fill(b' ');
    header[156] = b'0';
    header[257..263].copy_from_slice(b"ustar\0");
    header[263..265].copy_from_slice(b"00");
    header[345..345 + prefix.len()].copy_from_slice(prefix.as_bytes());
    let checksum: u32 = header.iter().map(|byte| u32::from(*byte)).sum();
    header[148..156].copy_from_slice(format!("{checksum:06o}\0 ").as_bytes());
    Ok(header)
}

fn split_ustar_path(path: &str) -> Result<(&str, &str), LauncherError> {
    if path.len() <= 100 {
        return Ok(("", path));
    }
    path.char_indices()
        .rev()
        .find_map(|(index, character)| {
            (character == '/' && index <= 155 && path.len() - index - 1 <= 100)
                .then_some((&path[..index], &path[index + 1..]))
        })
        .ok_or(LauncherError::LocalStore(
            "archive path is not representable as ustar",
        ))
}
