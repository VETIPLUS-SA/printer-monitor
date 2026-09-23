"""PDF naming: <outdir>/pdf/<device ip>/<UPPERCASE NAME>.pdf, no account id."""
from pathlib import Path

from printer_monitor.extract import _pdf_filename, _pdf_path

OUT = Path("output")
IP = "192.168.1.59"


def test_path_uses_ip_folder_and_uppercase_name_without_id():
    path = _pdf_path(OUT, IP, "6938", "Angel Zabaleta", set())
    assert path == OUT / "pdf" / IP / "ANGEL ZABALETA.pdf"


def test_accents_are_kept_and_uppercased():
    assert _pdf_filename("Carolina Mejía") == "CAROLINA MEJÍA"


def test_windows_invalid_characters_and_extra_spaces_removed():
    assert _pdf_filename('  Ana: "Pérez" / Gómez?. ') == "ANA PÉREZ GÓMEZ"


def test_empty_name_gets_placeholder():
    assert _pdf_filename("  ") == "SIN NOMBRE"


def test_duplicate_names_get_account_id_suffix_instead_of_overwriting():
    taken: set[str] = set()
    first = _pdf_path(OUT, IP, "1111", "Juan Perez", taken)
    second = _pdf_path(OUT, IP, "2222", "JUAN PEREZ", taken)
    assert first.name == "JUAN PEREZ.pdf"
    assert second.name == "JUAN PEREZ (2222).pdf"
