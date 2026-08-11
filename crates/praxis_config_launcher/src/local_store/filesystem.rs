use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, DirBuilder, File, OpenOptions};
use std::io::Write as _;
use std::os::unix::fs::{DirBuilderExt as _, OpenOptionsExt as _, PermissionsExt as _};
use std::path::{Path, PathBuf};

use crate::error::LauncherError;

use super::archive::{self, MANIFEST_PATH, ParsedArchive};
use super::{FaultPoint, LocalGeneration, io_error};

pub(super) fn publish(
    root: &Path,
    archive: &ParsedArchive,
    fault: Option<FaultPoint>,
) -> Result<LocalGeneration, LauncherError> {
    let final_path = root.join(&archive.generation_id);
    let temporary = root.join(format!("{}.tmp", archive.generation_id));
    if final_path.exists() || temporary.exists() {
        return Err(LauncherError::LocalStore(
            "generation already exists or has partial staging state",
        ));
    }
    create_directory(&temporary)?;
    inject(fault, FaultPoint::TemporaryDirectoryCreated)?;

    let mut directories = BTreeSet::new();
    for document in &archive.documents {
        if let Some(parent) = Path::new(&document.path)
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
        {
            create_relative_directories(&temporary, parent, &mut directories)?;
        }
    }
    inject(fault, FaultPoint::DocumentDirectoryCreated)?;
    for document in &archive.documents {
        let path = temporary.join(&document.path);
        inject(fault, FaultPoint::BeforeDocumentWrite)?;
        write_file(&path, &document.content)?;
        inject(fault, FaultPoint::DocumentWritten)?;
    }
    sync_directories(&temporary, &directories)?;
    inject(fault, FaultPoint::DocumentsSynced)?;

    let manifest_path = temporary.join(MANIFEST_PATH);
    write_file(&manifest_path, &archive.manifest_bytes)?;
    inject(fault, FaultPoint::ManifestWritten)?;
    File::open(&temporary)
        .and_then(|directory| directory.sync_all())
        .map_err(|source| io_error("sync generation directory", &temporary, source))?;
    inject(fault, FaultPoint::GenerationSynced)?;
    inject(fault, FaultPoint::BeforePublish)?;
    fs::rename(&temporary, &final_path)
        .map_err(|source| io_error("publish generation", &final_path, source))?;
    File::open(root)
        .and_then(|directory| directory.sync_all())
        .map_err(|source| io_error("sync store root", root, source))?;
    Ok(LocalGeneration { path: final_path })
}

pub(super) fn verify_published(path: &Path) -> Result<(), LauncherError> {
    validate_mode(path, true)?;
    let mut entries = BTreeMap::new();
    collect_files(path, path, &mut entries)?;
    let manifest = entries
        .get(MANIFEST_PATH)
        .ok_or(LauncherError::LocalStore("published manifest is missing"))?;
    let generation_id = archive::validate_published(manifest, &entries)?;
    if path.file_name().and_then(|name| name.to_str()) != Some(generation_id.as_str()) {
        return Err(LauncherError::LocalStore(
            "published generation directory identity is invalid",
        ));
    }
    Ok(())
}

fn create_directory(path: &Path) -> Result<(), LauncherError> {
    let mut builder = DirBuilder::new();
    builder.mode(0o700).recursive(false);
    builder
        .create(path)
        .map_err(|source| io_error("create generation directory", path, source))?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
        .map_err(|source| io_error("secure generation directory", path, source))
}

fn create_relative_directories(
    root: &Path,
    relative: &Path,
    created: &mut BTreeSet<PathBuf>,
) -> Result<(), LauncherError> {
    let mut current = PathBuf::new();
    for component in relative.components() {
        current.push(component);
        if created.insert(current.clone()) {
            create_directory(&root.join(&current))?;
        }
    }
    Ok(())
}

fn write_file(path: &Path, content: &[u8]) -> Result<(), LauncherError> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|source| io_error("create generation file", path, source))?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))
        .map_err(|source| io_error("secure generation file", path, source))?;
    file.write_all(content)
        .map_err(|source| io_error("write generation file", path, source))?;
    file.sync_all()
        .map_err(|source| io_error("sync generation file", path, source))
}

fn sync_directories(root: &Path, directories: &BTreeSet<PathBuf>) -> Result<(), LauncherError> {
    for relative in directories.iter().rev() {
        let path = root.join(relative);
        File::open(&path)
            .and_then(|directory| directory.sync_all())
            .map_err(|source| io_error("sync document directory", &path, source))?;
    }
    Ok(())
}

fn collect_files(
    root: &Path,
    directory: &Path,
    entries: &mut BTreeMap<String, Vec<u8>>,
) -> Result<(), LauncherError> {
    for entry in fs::read_dir(directory)
        .map_err(|source| io_error("read generation directory", directory, source))?
    {
        let entry = entry.map_err(|source| io_error("read generation entry", directory, source))?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|source| io_error("inspect generation entry", &path, source))?;
        if metadata.file_type().is_dir() {
            validate_mode(&path, true)?;
            collect_files(root, &path, entries)?;
        } else if metadata.file_type().is_file() {
            validate_mode(&path, false)?;
            let relative = path
                .strip_prefix(root)
                .map_err(|_| LauncherError::LocalStore("generation path escaped root"))?
                .to_str()
                .ok_or(LauncherError::LocalStore("generation path is not UTF-8"))?
                .replace(std::path::MAIN_SEPARATOR, "/");
            let content = fs::read(&path)
                .map_err(|source| io_error("read generation file", &path, source))?;
            if entries.insert(relative, content).is_some() {
                return Err(LauncherError::LocalStore("published path is duplicated"));
            }
        } else {
            return Err(LauncherError::LocalStore(
                "published generation contains a nonregular entry",
            ));
        }
    }
    Ok(())
}

fn validate_mode(path: &Path, directory: bool) -> Result<(), LauncherError> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|source| io_error("inspect generation path", path, source))?;
    let valid_type = if directory {
        metadata.file_type().is_dir()
    } else {
        metadata.file_type().is_file()
    };
    let expected = if directory { 0o700 } else { 0o600 };
    if !valid_type || metadata.permissions().mode() & 0o777 != expected {
        return Err(LauncherError::LocalStore(
            "published generation permissions are invalid",
        ));
    }
    Ok(())
}

fn inject(fault: Option<FaultPoint>, point: FaultPoint) -> Result<(), LauncherError> {
    if fault == Some(point) {
        Err(LauncherError::StagingFault(point))
    } else {
        Ok(())
    }
}
