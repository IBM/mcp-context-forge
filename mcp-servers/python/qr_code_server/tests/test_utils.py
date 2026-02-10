# -*- coding: utf-8 -*-
import pytest
from pydantic_core import ValidationError

from qr_code_server.utils.file_utils import DEFAULT_FILE_NAME, convert_to_bytes, resolve_output_path


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def test_empty_string(tmp, monkeypatch):
    monkeypatch.chdir(tmp)
    out = resolve_output_path("", "png")
    assert out == str(tmp / f"{DEFAULT_FILE_NAME}.png")


def test_filename_only(tmp, monkeypatch):
    monkeypatch.chdir(tmp)
    out = resolve_output_path("file", "png")
    assert out == str(tmp / "file.png")


def test_filename_only_with_ext(tmp, monkeypatch):
    monkeypatch.chdir(tmp)
    out = resolve_output_path("file.jpg", "png")
    assert out == str(tmp / "file.jpg.png")


def test_existing_directory_no_trailing_slash(tmp):
    d = tmp / "outdir"
    d.mkdir()
    out = resolve_output_path(str(d), "png")
    assert out == str(d / f"{DEFAULT_FILE_NAME}.png")


def test_nonexistent_directory_vs_filename(tmp):
    # resolve_output_path can't know "foo/bar" means dir or file
    out = resolve_output_path(str(tmp / "foo" / "bar"), "png")
    assert out.endswith("/foo/bar.png")
    assert (tmp / "foo").exists()  # directory was created


def test_directory_with_trailing_sep(tmp):
    d = f"{tmp}/x/"
    out = resolve_output_path(str(d), "png")
    assert out == str(tmp / "x" / f"{DEFAULT_FILE_NAME}.png")


def test_path_ending_with_dot(tmp):
    out = resolve_output_path(str(tmp / "weird."), "png")
    assert out == str(tmp / "weird.png")


def test_relative_dot(tmp, monkeypatch):
    monkeypatch.chdir(tmp)
    out = resolve_output_path(".", "png")
    assert out == str(tmp / f"{DEFAULT_FILE_NAME}.png")


def test_relative_dotdot(tmp, monkeypatch):
    parent = tmp.parent
    monkeypatch.chdir(tmp)
    out = resolve_output_path("..", "png")
    assert out == str(parent / f"{DEFAULT_FILE_NAME}.png")


def test_leading_trailing_spaces(tmp, monkeypatch):
    monkeypatch.chdir(tmp)
    out = resolve_output_path("  file  ", "png")
    # filename preserved exactly
    assert out == str(tmp / "  file  .png")


def test_absolute_path(tmp):
    path = tmp / "foo"
    out = resolve_output_path(str(path), "png")
    assert out == str(tmp / "foo.png")


def test_no_filename_dir_created(tmp):
    path = f"{tmp}/newdir/"
    out = resolve_output_path(path, "png")
    assert out == str(tmp / "newdir" / f"{DEFAULT_FILE_NAME}.png")
    assert (tmp / "newdir").is_dir()


def test_convert_to_bytes():
    assert convert_to_bytes("100B") == 100
    assert convert_to_bytes("100") == 100
    assert convert_to_bytes("  50b  ") == 50
    assert convert_to_bytes("2.5kb") == int(2.5 * 1024)
    assert convert_to_bytes("0.5gb") == int(0.5 * 1024**3)


def test_convert_to_bytes_wrong_input():
    with pytest.raises(ValueError):
        convert_to_bytes("10TB")
    with pytest.raises(ValueError):
        convert_to_bytes("abc")
    with pytest.raises(ValueError):
        convert_to_bytes("100MBs")
    with pytest.raises(ValueError):
        convert_to_bytes("MB100")
    with pytest.raises(ValueError):
        convert_to_bytes("")


def test_load_config_defaults(tmp_path, monkeypatch):
    import qr_code_server.config as cfg

    fake_config = tmp_path / "config.yaml"

    monkeypatch.setattr(cfg, "CONFIG_PATH", fake_config)

    config = cfg.load_config()

    assert config.qr_generation.default_size == 10
    assert config.output.enable_zip_export is True
    assert config.decoding.preprocessing_enabled is True


def test_invalid_config_raises(tmp_path, monkeypatch):
    import qr_code_server.config as cfg

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
    output:
    max_batch_size: "not-an-int"
    """
    )

    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)

    with pytest.raises(ValidationError):
        cfg.load_config()
