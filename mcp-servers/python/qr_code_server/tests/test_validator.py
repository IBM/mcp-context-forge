# -*- coding: utf-8 -*-
from qr_code_server.tools.validator import (
    QRValidationRequest,
    encoded_bits,
    smallest_fitting_version,
    validate,
)


def test_validation_fits_explicit_version():
    """Data fits the specified version → valid=True, fits=True."""
    req = QRValidationRequest(data="abc", target_version=5, error_correction="L")
    result = validate(req)
    assert result.valid is True
    assert result.fits is True
    assert result.error is None


def test_validation_not_fit_explicit_version():
    req = QRValidationRequest(data="abc" * 100, target_version=5, error_correction="L")
    result = validate(req)
    assert result.valid is False
    assert result.fits is False


def test_validation_without_target_version_checks_general_fit():
    """When version=None, it should only check whether any QR version fits."""
    req = QRValidationRequest(data="Hello", target_version=None)
    result = validate(req)
    assert result.valid is True
    assert result.fits is True


def test_validation_no_version_and_data_too_large_for_all():
    """If no version is supplied and the data fits in no version → error."""
    text = "A" * 20000  # guaranteed to exceed even version 40-H
    req = QRValidationRequest(data=text, target_version=None)
    result = validate(req)
    assert result.valid is False
    assert result.fits is False
    assert result.error == "Data too large for any QR version"


def test_validation_suggests_optimization():
    """When suggest_optimization=True, result must include suggested_version."""
    req = QRValidationRequest(data="abcdef", target_version=10, suggest_optimization=True)
    result = validate(req)

    assert result.suggested_version is not None


def test_encode_bits_small_version():
    """Test encoded bits calculates correctly"""
    result = 32
    text = "aa"
    version = 9
    assert encoded_bits(text, version) == result


def test_encode_bits_big_version():
    """Test encoded bits calculates correctly"""
    result = 40
    text = "aa"
    version = 39
    assert encoded_bits(text, version) == result


def test_smallest_fitting_version():
    result = 1
    text = "a"
    error_correction = "M"
    assert smallest_fitting_version(text, error_correction) == result


def test_encode_bits_empty_string():
    """Encoding empty text should return the overhead bits only."""
    text = ""
    version = 5
    assert encoded_bits(text, version) == 16


def test_smallest_fitting_version_exact_boundary():
    """Text exactly matching the capacity should choose that version."""
    text = "a" * 20
    ec = "L"
    version = smallest_fitting_version(text, ec)
    assert version == 2


def test_smallest_fitting_version_large_text():
    """Large text must choose a larger version."""
    text = "a" * 1000
    ec = "Q"
    version = smallest_fitting_version(text, ec)
    assert version >= 30


def test_smallest_fitting_version_same_ec_level_different_results():
    """Different EC levels must give different versions."""
    text = "hello world"
    v_l = smallest_fitting_version(text, "L")
    v_h = smallest_fitting_version(text, "H")
    assert v_h >= v_l


def test_encode_bits_consistency():
    """encoded_bits should increase or stay the same when version increases."""
    text = "abcdef"
    for v in range(1, 39):
        assert encoded_bits(text, v) <= encoded_bits(text, v + 1)
