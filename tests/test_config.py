"""Unit tests for utils/config.py (lazy environment-variable readers)."""

import pytest

from utils import config


# --------------------------------------------------------------------------- #
# Boolean flags
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", " on "])
def test_listener_enabled_truthy(monkeypatch, value):
    monkeypatch.setenv("SLACK_LISTENER_ENABLED", value)
    assert config.listener_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_listener_enabled_falsy(monkeypatch, value):
    monkeypatch.setenv("SLACK_LISTENER_ENABLED", value)
    assert config.listener_enabled() is False


def test_listener_enabled_unset_is_false(monkeypatch):
    monkeypatch.delenv("SLACK_LISTENER_ENABLED", raising=False)
    assert config.listener_enabled() is False


def test_notify_user_defaults_true_when_unset(monkeypatch):
    monkeypatch.delenv("SLACK_NOTIFY_USER", raising=False)
    assert config.notify_user() is True


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("1", True), ("on", True),
    ("false", False), ("0", False), ("off", False), ("nonsense", False),
])
def test_notify_user_explicit(monkeypatch, value, expected):
    monkeypatch.setenv("SLACK_NOTIFY_USER", value)
    assert config.notify_user() is expected


# --------------------------------------------------------------------------- #
# Plain string-or-None readers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fn,var", [
    (lambda: config.app_token(), "SLACK_APP_TOKEN"),
    (lambda: config.bot_token(), "SLACK_BOT_TOKEN"),
    (lambda: config.workflow_dir(), "SLACK_WORKFLOW_DIR"),
    (lambda: config.comfy_api_key(), "SLACK_COMFY_API_KEY"),
])
def test_string_readers(monkeypatch, fn, var):
    monkeypatch.setenv(var, "value-xyz")
    assert fn() == "value-xyz"
    monkeypatch.setenv(var, "")          # empty string coerces to None
    assert fn() is None
    monkeypatch.delenv(var, raising=False)
    assert fn() is None


# --------------------------------------------------------------------------- #
# CSV allow-lists
# --------------------------------------------------------------------------- #
def test_allowed_users_parsing(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_USERS", " alice , bob ,, alice ,U123 ")
    assert config.allowed_users() == {"alice", "bob", "U123"}


def test_allowed_channels_parsing(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "#general,#general, C999 ")
    assert config.allowed_channels() == {"#general", "C999"}


def test_allowed_unset_is_empty_set(monkeypatch):
    monkeypatch.delenv("SLACK_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("SLACK_ALLOWED_CHANNELS", raising=False)
    assert config.allowed_users() == set()
    assert config.allowed_channels() == set()


def test_allowed_blank_is_empty_set(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_USERS", "   ")
    assert config.allowed_users() == set()


# --------------------------------------------------------------------------- #
# Integer readers with fallback + floor
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("var,fn,default", [
    ("SLACK_MAX_INPUT_MB", lambda: config.max_input_mb(), 20),
    ("SLACK_MAX_FANOUT", lambda: config.max_fanout(), 25),
])
def test_int_readers(monkeypatch, var, fn, default):
    monkeypatch.setenv(var, "7")
    assert fn() == 7
    monkeypatch.setenv(var, "0")         # floored to 1
    assert fn() == 1
    monkeypatch.setenv(var, "-5")        # floored to 1
    assert fn() == 1
    monkeypatch.setenv(var, "notanint")  # fallback to default
    assert fn() == default
    monkeypatch.delenv(var, raising=False)
    assert fn() == default


# --------------------------------------------------------------------------- #
# comfy_base_url
# --------------------------------------------------------------------------- #
def test_comfy_base_url_override_wins_and_strips_slash(monkeypatch):
    monkeypatch.setenv("SLACK_COMFY_URL", "http://example.com:9000/")
    assert config.comfy_base_url() == "http://example.com:9000"


def test_comfy_base_url_default_when_unset(monkeypatch):
    monkeypatch.delenv("SLACK_COMFY_URL", raising=False)
    # With no override and no running ComfyUI server/cli_args, falls back to loopback.
    assert config.comfy_base_url() == "http://127.0.0.1:8188"
