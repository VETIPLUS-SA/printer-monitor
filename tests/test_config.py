"""Unit tests for printer_monitor.config (single and multi-printer loading).

Every test passes an explicit `env` dict and `load_dotenv_files=False` (the
default is still exercised once, via monkeypatch, to prove it never falls
back to reading the real .env when an explicit env is given). No test ever
reads the project's real .env file.
"""
from __future__ import annotations

import pytest

from printer_monitor.config import ConfigError, Settings, load_printers


def _legacy_env(**overrides) -> dict:
    env = {
        "KYOCERA_URL": "https://192.168.1.59/",
        "KYOCERA_USER": "admin",
        "KYOCERA_PASSWORD": "secret",
    }
    env.update(overrides)
    return env


# -- legacy single-printer mode ----------------------------------------------

def test_legacy_single_printer_mode_returns_one_default_printer():
    printers = load_printers(env=_legacy_env(), load_dotenv_files=False)
    assert len(printers) == 1
    p = printers[0]
    assert p.name == "default"
    assert p.url == "https://192.168.1.59/"
    assert p.user == "admin"
    assert p.password == "secret"
    assert p.outdir == "output"
    assert p.delay_ms == 700
    assert p.timeout_ms == 20000


def test_legacy_mode_missing_variable_raises_config_error():
    env = _legacy_env()
    del env["KYOCERA_PASSWORD"]
    with pytest.raises(ConfigError, match="KYOCERA_PASSWORD"):
        load_printers(env=env, load_dotenv_files=False)


def test_legacy_mode_respects_shared_settings_overrides():
    env = _legacy_env(KYOCERA_OUTDIR="salida", KYOCERA_DELAY_MS="1000", KYOCERA_TIMEOUT_MS="5000")
    printers = load_printers(env=env, load_dotenv_files=False)
    p = printers[0]
    assert p.outdir == "salida"
    assert p.delay_ms == 1000
    assert p.timeout_ms == 5000


# -- multi-printer mode -------------------------------------------------------

def _multi_env(**overrides) -> dict:
    env = {
        "KYOCERA_PRINTERS": "pedidos,cartera,bodega",
        "KYOCERA_USER": "Admin",
        "KYOCERA_PASSWORD": "shared-pass",
        "KYOCERA_PEDIDOS_URL": "https://192.168.1.59/",
        "KYOCERA_PEDIDOS_USER": "Admin",
        "KYOCERA_PEDIDOS_PASSWORD": "pedidos-pass",
        "KYOCERA_CARTERA_URL": "https://192.168.1.104/",
        "KYOCERA_CARTERA_USER": "otro_usuario",
        "KYOCERA_CARTERA_PASSWORD": "otra_clave",
        "KYOCERA_BODEGA_URL": "https://192.168.1.162/",
    }
    env.update(overrides)
    return env


def test_multi_printer_with_own_credentials():
    printers = load_printers(env=_multi_env(), load_dotenv_files=False)
    by_name = {p.name: p for p in printers}
    assert set(by_name) == {"pedidos", "cartera", "bodega"}

    pedidos = by_name["pedidos"]
    assert pedidos.url == "https://192.168.1.59/"
    assert pedidos.user == "Admin"
    assert pedidos.password == "pedidos-pass"

    cartera = by_name["cartera"]
    assert cartera.user == "otro_usuario"
    assert cartera.password == "otra_clave"


def test_multi_printer_falls_back_to_shared_user_and_password_independently():
    printers = load_printers(env=_multi_env(), load_dotenv_files=False)
    bodega = next(p for p in printers if p.name == "bodega")
    # No KYOCERA_BODEGA_USER/PASSWORD given: both fall back to the shared ones.
    assert bodega.user == "Admin"
    assert bodega.password == "shared-pass"


def test_multi_printer_falls_back_to_shared_user_only_when_own_password_given():
    env = _multi_env(
        KYOCERA_BODEGA_PASSWORD="bodega-only-pass",
    )
    printers = load_printers(env=env, load_dotenv_files=False)
    bodega = next(p for p in printers if p.name == "bodega")
    assert bodega.user == "Admin"  # falls back
    assert bodega.password == "bodega-only-pass"  # its own


def test_multi_printer_missing_url_raises_config_error_naming_variable():
    env = _multi_env()
    del env["KYOCERA_BODEGA_URL"]
    with pytest.raises(ConfigError, match="KYOCERA_BODEGA_URL"):
        load_printers(env=env, load_dotenv_files=False)


def test_multi_printer_missing_credentials_with_no_fallback_names_exact_variables():
    env = _multi_env(KYOCERA_USER="", KYOCERA_PASSWORD="")
    del env["KYOCERA_BODEGA_URL"]
    env["KYOCERA_BODEGA_URL"] = "https://192.168.1.162/"
    with pytest.raises(ConfigError) as exc_info:
        load_printers(env=env, load_dotenv_files=False)
    message = str(exc_info.value)
    assert "KYOCERA_BODEGA_USER" in message
    assert "KYOCERA_BODEGA_PASSWORD" in message


def test_invalid_printer_name_raises_config_error():
    env = _multi_env(KYOCERA_PRINTERS="pedidos,office 2")
    with pytest.raises(ConfigError, match="office 2"):
        load_printers(env=env, load_dotenv_files=False)


def test_duplicate_printer_names_are_rejected_case_insensitively():
    env = _multi_env(KYOCERA_PRINTERS="pedidos,Pedidos")
    with pytest.raises(ConfigError, match="[Dd]uplicate"):
        load_printers(env=env, load_dotenv_files=False)


def test_printer_names_are_case_insensitive_for_env_prefix_lookup():
    env = _multi_env(KYOCERA_PRINTERS="Pedidos")
    printers = load_printers(env=env, load_dotenv_files=False)
    assert len(printers) == 1
    assert printers[0].name == "Pedidos"  # original casing preserved
    assert printers[0].url == "https://192.168.1.59/"


def test_empty_entries_in_printers_list_are_ignored():
    env = _multi_env(KYOCERA_PRINTERS="pedidos,,cartera,bodega,")
    printers = load_printers(env=env, load_dotenv_files=False)
    assert {p.name for p in printers} == {"pedidos", "cartera", "bodega"}


def test_multi_printer_order_matches_kyocera_printers_list():
    printers = load_printers(env=_multi_env(), load_dotenv_files=False)
    assert [p.name for p in printers] == ["pedidos", "cartera", "bodega"]


# -- Settings repr / safety ---------------------------------------------------

def test_settings_repr_hides_password():
    settings = Settings(url="https://192.168.1.59/", user="admin", password="super-secret")
    text = repr(settings)
    assert "super-secret" not in text
    assert "***" in text


# -- never touches the real .env / os.environ when env is given --------------

def test_explicit_env_never_loads_dotenv_files(monkeypatch):
    called = {"load_dotenv": False}

    def _fail_if_called(*args, **kwargs):
        called["load_dotenv"] = True
        raise AssertionError("dotenv.load_dotenv must not be called when env= is given")

    monkeypatch.setattr("printer_monitor.config.load_dotenv", _fail_if_called)
    load_printers(env=_legacy_env(), load_dotenv_files=True)  # even True must be ignored
    assert called["load_dotenv"] is False


def test_load_dotenv_files_false_skips_dotenv_even_reading_os_environ(monkeypatch):
    called = {"load_dotenv": False}

    def _fail_if_called(*args, **kwargs):
        called["load_dotenv"] = True
        raise AssertionError("dotenv.load_dotenv must not be called")

    monkeypatch.setattr("printer_monitor.config.load_dotenv", _fail_if_called)
    for key, value in _legacy_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("KYOCERA_PRINTERS", raising=False)

    printers = load_printers(env=None, load_dotenv_files=False)
    assert printers[0].name == "default"
    assert called["load_dotenv"] is False
