mod archive;
mod filesystem;

#[cfg(test)]
mod tests;

use std::fs::{self, DirBuilder, File};
use std::os::unix::fs::{DirBuilderExt as _, PermissionsExt as _};
use std::path::{Path, PathBuf};

use crate::artifact::VerifiedArtifact;
use crate::error::LauncherError;

const TEMP_SUFFIX: &str = ".tmp";

/// Deterministic failure boundaries used to prove crash-safe staging.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FaultPoint {
    TemporaryDirectoryCreated,
    DocumentDirectoryCreated,
    BeforeDocumentWrite,
    DocumentWritten,
    DocumentsSynced,
    ManifestWritten,
    GenerationSynced,
    BeforePublish,
}

/// One immutable, locally published generation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalGeneration {
    path: PathBuf,
}

impl LocalGeneration {
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }
}

/// Root for immutable local generation directories.
#[derive(Clone, Debug)]
pub struct LocalStore {
    root: PathBuf,
}

impl LocalStore {
    /// Opens a secure store and removes deterministic partial staging artifacts.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, LauncherError> {
        let root = root.as_ref().to_path_buf();
        if !root.exists() {
            let mut builder = DirBuilder::new();
            builder.mode(0o700).recursive(false);
            builder
                .create(&root)
                .map_err(|source| io_error("create store root", &root, source))?;
            fs::set_permissions(&root, fs::Permissions::from_mode(0o700))
                .map_err(|source| io_error("secure store root", &root, source))?;
        }
        validate_directory(&root, "store root is not a secure directory")?;
        let store = Self { root };
        store.cleanup_temporary()?;
        Ok(store)
    }

    /// Stages and atomically publishes one new immutable generation.
    pub fn stage(&self, artifact: &VerifiedArtifact) -> Result<LocalGeneration, LauncherError> {
        self.stage_with_fault(artifact, None)
    }

    /// Stages with one deterministic crash boundary for verification.
    #[doc(hidden)]
    pub fn stage_with_fault(
        &self,
        artifact: &VerifiedArtifact,
        fault: Option<FaultPoint>,
    ) -> Result<LocalGeneration, LauncherError> {
        let parsed = archive::validate(artifact)?;
        filesystem::publish(&self.root, &parsed, fault)
    }

    /// Reopens and fully verifies one already-published generation.
    pub fn generation(
        &self,
        generation_id: &str,
    ) -> Result<Option<LocalGeneration>, LauncherError> {
        if !is_generation_id(generation_id) {
            return Err(LauncherError::LocalStore("generation id is invalid"));
        }
        let path = self.root.join(generation_id);
        if !path.exists() {
            return Ok(None);
        }
        filesystem::verify_published(&path)?;
        Ok(Some(LocalGeneration { path }))
    }

    pub(crate) fn discard_corrupt_generation(
        &self,
        generation_id: &str,
    ) -> Result<(), LauncherError> {
        if !is_generation_id(generation_id) {
            return Err(LauncherError::LocalStore("generation id is invalid"));
        }
        let path = self.root.join(generation_id);
        fs::remove_dir_all(&path)
            .map_err(|source| io_error("remove corrupt generation", &path, source))?;
        File::open(&self.root)
            .and_then(|directory| directory.sync_all())
            .map_err(|source| io_error("sync store root", &self.root, source))
    }

    fn cleanup_temporary(&self) -> Result<(), LauncherError> {
        let mut removed = false;
        for entry in fs::read_dir(&self.root)
            .map_err(|source| io_error("read store root", &self.root, source))?
        {
            let entry = entry.map_err(|source| io_error("read store entry", &self.root, source))?;
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.strip_suffix(TEMP_SUFFIX).is_some_and(is_generation_id) {
                let path = entry.path();
                let metadata = fs::symlink_metadata(&path)
                    .map_err(|source| io_error("inspect partial generation", &path, source))?;
                if metadata.file_type().is_dir() {
                    fs::remove_dir_all(&path)
                        .map_err(|source| io_error("remove partial generation", &path, source))?;
                } else {
                    fs::remove_file(&path)
                        .map_err(|source| io_error("remove partial generation", &path, source))?;
                }
                removed = true;
            }
        }
        if removed {
            File::open(&self.root)
                .and_then(|directory| directory.sync_all())
                .map_err(|source| io_error("sync store root", &self.root, source))?;
        }
        Ok(())
    }
}

pub(crate) fn io_error(
    operation: &'static str,
    path: &Path,
    source: std::io::Error,
) -> LauncherError {
    LauncherError::LocalStoreIo {
        operation,
        path: path.to_path_buf(),
        source,
    }
}

fn validate_directory(path: &Path, message: &'static str) -> Result<(), LauncherError> {
    let metadata =
        fs::symlink_metadata(path).map_err(|source| io_error("inspect directory", path, source))?;
    if !metadata.file_type().is_dir() || metadata.permissions().mode() & 0o777 != 0o700 {
        return Err(LauncherError::LocalStore(message));
    }
    Ok(())
}

fn is_generation_id(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}
