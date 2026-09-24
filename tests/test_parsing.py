"""Unit tests for printer_monitor.parsing (pure, no Playwright).

All fixture data below is synthetic (fake account/user names), not taken
from any real recon dump.
"""
import pytest

from printer_monitor.parsing import ParseError, map_rows, validate_title


# -- print_function -----------------------------------------------------------------

def test_print_function_happy_path():
    rows = [
        ["Copiadora Total", "----------", "120"],
        ["Impresora Total", "----------", "980"],
    ]
    result = map_rows("print_function", rows)
    assert result == {"copier_total": "120", "printer_total": "980"}


# -- print_layout: duplicate "Total" label disambiguation -----------------------------

def test_print_layout_happy_path_and_duplicate_total():
    rows = [
        ["Dúplex (1 cara)", "----------", "500"],
        ["Dúplex (2 caras)", "----------", "300"],
        ["Total", "----------", "800"],
        ["Combinar (Ninguno)", "----------", "700"],
        ["Combinar (2 en 1)", "----------", "90"],
        ["Combinar (4 en 1)", "----------", "10"],
        ["Total", "----------", "800"],
    ]
    result = map_rows("print_layout", rows)
    assert result == {
        "duplex_1sided": "500",
        "duplex_2sided": "300",
        "duplex_total": "800",
        "combine_none": "700",
        "combine_2in1": "90",
        "combine_4in1": "10",
        "combine_total": "800",
    }


# -- scan -----------------------------------------------------------------------------

def test_scan_happy_path():
    rows = [
        ["Copia", "----------", "40"],
        ["FAX", "----------", "5"],
        ["Escaneo (Otras)", "----------", "15"],
        ["Total de escaneado", "----------", "60"],
    ]
    result = map_rows("scan", rows)
    assert result == {
        "scan_copy": "40",
        "scan_fax": "5",
        "scan_other": "15",
        "scan_total": "60",
    }


# -- fax --------------------------------------------------------------------------------

def test_fax_happy_path_with_time_value():
    rows = [
        ["Páginas transmisión FAX", "----------", "12"],
        ["Hora transmisión FAX", "----------", "0:05:32"],
    ]
    result = map_rows("fax", rows)
    assert result == {"fax_tx_pages": "12", "fax_tx_time": "0:05:32"}


# -- non-breaking space handling ---------------------------------------------------------

def test_handles_non_breaking_spaces_in_label_and_value():
    rows = [
        ["Copiadora\xa0Total", "----------", "\xa0120\xa0"],
        ["Impresora Total", "----------", "980"],
    ]
    result = map_rows("print_function", rows)
    assert result == {"copier_total": "120", "printer_total": "980"}


# -- errors -----------------------------------------------------------------------------

def test_missing_label_raises_parse_error():
    rows = [["Copiadora Total", "----------", "120"]]  # Impresora Total missing
    with pytest.raises(ParseError):
        map_rows("print_function", rows)


def test_bad_value_raises_parse_error():
    rows = [
        ["Copiadora Total", "----------", "not-a-number"],
        ["Impresora Total", "----------", "980"],
    ]
    with pytest.raises(ParseError):
        map_rows("print_function", rows)


def test_bad_time_value_raises_parse_error():
    rows = [
        ["Páginas transmisión FAX", "----------", "12"],
        ["Hora transmisión FAX", "----------", "not-a-time"],
    ]
    with pytest.raises(ParseError):
        map_rows("fax", rows)


def test_unknown_kind_raises_parse_error():
    with pytest.raises(ParseError):
        map_rows("not_a_real_kind", [])


# -- unknown extra labels become extra columns instead of failing -----------------------

def test_unknown_label_becomes_extra_column():
    rows = [
        ["Copiadora Total", "----------", "120"],
        ["Impresora Total", "----------", "980"],
        ["Nuevo Contador Futuro", "----------", "42"],
    ]
    result = map_rows("print_function", rows)
    assert result["copier_total"] == "120"
    assert result["printer_total"] == "980"
    assert result["nuevo_contador_futuro"] == "42"


def test_unknown_labels_get_unique_slugs_on_collision():
    rows = [
        ["Copiadora Total", "----------", "120"],
        ["Impresora Total", "----------", "980"],
        ["Nuevo!", "----------", "1"],
        ["Nuevo?", "----------", "2"],
    ]
    result = map_rows("print_function", rows)
    # Both slugify to "nuevo"; the second must not overwrite the first.
    assert result["nuevo"] == "1"
    assert result["nuevo_2"] == "2"


def test_header_rows_are_skipped():
    rows = [
        ["Función", "Uso/MÁX.", "Contador"],
        ["Copiadora Total", "----------", "120"],
        ["Impresora Total", "----------", "980"],
    ]
    result = map_rows("print_function", rows)
    assert result == {"copier_total": "120", "printer_total": "980"}


# -- validate_title -----------------------------------------------------------------------

def test_validate_title_passes_when_name_present():
    validate_title("Juan Perez - Páginas impresas", "Juan Perez")  # no raise


def test_validate_title_raises_when_name_missing():
    with pytest.raises(ParseError):
        validate_title("Otra Persona - Páginas impresas", "Juan Perez")


def test_validate_title_skips_check_when_expected_name_is_none():
    validate_title("Contabilidad total tbjos. - Páginas impresas", None)  # no raise


def test_validate_title_handles_non_breaking_space():
    validate_title("Juan\xa0Perez - Páginas impresas", "Juan Perez")  # no raise


def test_print_function_optional_fax_and_total_rows_from_older_firmware():
    rows = [
        ["Copiadora Total", "----------", "3"],
        ["Impresora Total", "----------", "40"],
        ["FAX", "----------", "2"],
        ["Total", "----------", "45"],
    ]
    assert map_rows("print_function", rows) == {
        "copier_total": "3",
        "printer_total": "40",
        "fax_printed": "2",
        "print_function_total": "45",
    }


def test_print_function_optional_rows_are_not_required():
    rows = [["Copiadora Total", "----------", "0"], ["Impresora Total", "----------", "7"]]
    assert map_rows("print_function", rows) == {"copier_total": "0", "printer_total": "7"}
