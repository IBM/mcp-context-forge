from pathlib import Path


def test_repository_does_not_include_machine_specific_home_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    machine_specific_home = "/home/" + "cmihai"
    offenders: list[str] = []

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pyc"}:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if machine_specific_home in content:
            offenders.append(str(path.relative_to(repo_root)))

    assert offenders == []
