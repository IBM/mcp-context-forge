# -*- coding: utf-8 -*-
import pytest
from pydantic import ValidationError
from mcpgateway.config import Settings


@pytest.mark.parametrize("url", ["http://ok.com/", "https://secure.org/"])
def test_app_domain_valid(url):
    settings = Settings(app_domain=url)
    assert str(settings.app_domain) == url


@pytest.mark.parametrize("url", ["not-a-url", "ftp://unsupported"])
def test_app_domain_invalid(url):
    with pytest.raises(ValidationError):
        Settings(app_domain=url)


@pytest.mark.parametrize("level", ["info", "debug", "warning"])
def test_log_level_valid(level):
    settings = Settings(log_level=level)
    assert str(settings.log_level) == level.upper()


@pytest.mark.parametrize("level", ["verbose", "none"])
def test_log_level_invalid(level):
    with pytest.raises(ValidationError):
        Settings(log_level=level)


@pytest.mark.parametrize("size", [1024, 16384, 1048576])
def test_log_detailed_max_body_size_valid(size):
    settings = Settings(log_detailed_max_body_size=size, _env_file=None)
    assert settings.log_detailed_max_body_size == size


@pytest.mark.parametrize("size", [0, 512, 1048577])
def test_log_detailed_max_body_size_invalid(size):
    with pytest.raises(ValidationError):
        Settings(log_detailed_max_body_size=size, _env_file=None)


@pytest.mark.parametrize("port", [1, 8080, 65535])
def test_port_valid(port):
    settings = Settings(port=port)
    assert settings.port == port


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_port_invalid(port):
    with pytest.raises(ValidationError):
        Settings(port=port)
