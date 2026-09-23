"""PDF naming: <outdir>/pdf/<device ip>/<YYYY-MM>/<UPPERCASE NAME>.pdf, no account id."""
from pathlib import Path

from printer_monitor.extract import _pdf_filename, _pdf_path

OUT = Path("output")
IP = "192.168.1.59"
MONTH = "2026-09"


def test_path_uses_ip_and_month_folders_and_uppercase_name_without_id():
    path = _pdf_path(OUT, IP, MONTH, "6938", "Angel Zabaleta", set())
    assert path == OUT / "pdf" / IP / MONTH / "ANGEL ZABALETA.pdf"


def test_accents_removed_but_n_tilde_kept_and_uppercased():
    assert _pdf_filename("Carolina Mejía") == "CAROLINA MEJIA"
    assert _pdf_filename("Eliana Sánchez Muñoz") == "ELIANA SANCHEZ MUÑOZ"


def test_windows_invalid_characters_and_extra_spaces_removed():
    assert _pdf_filename('  Ana: "Pérez" / Gómez?. ') == "ANA PEREZ GOMEZ"


def test_empty_name_gets_placeholder():
    assert _pdf_filename("  ") == "SIN NOMBRE"


def test_duplicate_names_get_account_id_suffix_instead_of_overwriting():
    taken: set[str] = set()
    first = _pdf_path(OUT, IP, MONTH, "1111", "Juan Perez", taken)
    second = _pdf_path(OUT, IP, MONTH, "2222", "JUAN PEREZ", taken)
    assert first.name == "JUAN PEREZ.pdf"
    assert second.name == "JUAN PEREZ (2222).pdf"


def test_different_months_produce_different_folders():
    path_sep = _pdf_path(OUT, IP, MONTH, "1111", "Juan Perez", set())
    path_oct = _pdf_path(OUT, IP, "2026-10", "1111", "Juan Perez", set())
    assert path_sep.parent == OUT / "pdf" / IP / "2026-09"
    assert path_oct.parent == OUT / "pdf" / IP / "2026-10"
