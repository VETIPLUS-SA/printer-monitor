"""Pure parsing helpers for the Kyocera job-accounting detail pages.

Kept free of Playwright so it can be unit tested with plain Python data:
the caller extracts visible table rows in-browser (see portal.py) and
passes them here as plain [label, limit, value] triples.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# Header row labels to ignore if they slip through (the browser-side
# extraction in portal.py already filters these out; this is a defensive
# second check).
HEADER_LABELS = {"Función", "Uso/MÁX.", "Contador"}

# Expected (label, output_key) pairs per detail page kind, in the order the
# labels appear on the rendered page. Duplicate labels (the two "Total"
# rows on the print-by-layout page) are disambiguated positionally: the
# first occurrence maps to the first entry, the second to the second.
LABEL_MAPS: dict[str, list[tuple[str, str]]] = {
    "print_function": [
        ("Copiadora Total", "copier_total"),
        ("Impresora Total", "printer_total"),
    ],
    "print_layout": [
        ("Dúplex (1 cara)", "duplex_1sided"),
        ("Dúplex (2 caras)", "duplex_2sided"),
        ("Total", "duplex_total"),
        ("Combinar (Ninguno)", "combine_none"),
        ("Combinar (2 en 1)", "combine_2in1"),
        ("Combinar (4 en 1)", "combine_4in1"),
        ("Total", "combine_total"),
    ],
    "scan": [
        ("Copia", "scan_copy"),
        ("FAX", "scan_fax"),
        ("Escaneo (Otras)", "scan_other"),
        ("Total de escaneado", "scan_total"),
    ],
    "fax": [
        ("Páginas transmisión FAX", "fax_tx_pages"),
        ("Hora transmisión FAX", "fax_tx_time"),
    ],
}

# Rows only some firmware shows (e.g. 192.168.1.40 lists received-FAX prints
# and a total on the print-by-function page). Mapped when present, never required.
OPTIONAL_LABEL_MAPS: dict[str, list[tuple[str, str]]] = {
    "print_function": [
        ("FAX", "fax_printed"),
        ("Total", "print_function_total"),
    ],
}

# Keys whose value is a hh:mm:ss duration instead of a plain integer.
TIME_KEYS = {"fax_tx_time"}

NUMERIC_RE = re.compile(r"^\d+$")
TIME_RE = re.compile(r"^\d+:\d{2}:\d{2}$")


class ParseError(Exception):
    """Raised when a detail page's rendered rows don't match what was
    expected: a required label is missing, or a value doesn't match the
    expected numeric/time format."""


def _normalize(text: str) -> str:
    """Collapse non-breaking spaces and extra whitespace, as seen on the
    real portal, into a single plain-space, trimmed string."""
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _slugify(label: str) -> str:
    slug = re.sub(r"[^\w]+", "_", label, flags=re.UNICODE).strip("_").lower()
    return slug or "extra"


def _validate_value(key: str, value: str) -> None:
    pattern = TIME_RE if key in TIME_KEYS else NUMERIC_RE
    if not pattern.match(value):
        raise ParseError(f"value for {key!r} does not match expected format: {value!r}")


def map_rows(kind: str, rows: list[list[str]]) -> dict[str, str]:
    """Map rendered detail-page rows to the fixed output columns for `kind`.

    `rows` is a list of [label, limit, value] triples (limit is ignored;
    it is either a number or "----------" for "no limit").

    Known labels (see LABEL_MAPS) are validated and mapped to their output
    key. Any label that doesn't match an expected one is logged and kept
    under a slugified column name instead of failing the whole run.
    Missing expected labels, or a value that doesn't match the expected
    numeric/time format, raise ParseError.
    """
    if kind not in LABEL_MAPS:
        raise ParseError(f"unknown detail kind: {kind!r}")

    expected = LABEL_MAPS[kind]
    queues: dict[str, deque[str]] = defaultdict(deque)
    for label, key in expected + OPTIONAL_LABEL_MAPS.get(kind, []):
        queues[label].append(key)

    result: dict[str, str] = {}
    used_slugs: set[str] = set()

    for row in rows:
        if not row:
            continue
        label = _normalize(row[0])
        if not label or label in HEADER_LABELS:
            continue
        value = _normalize(row[-1]) if len(row) > 1 else ""

        queue = queues.get(label)
        if queue:
            key = queue.popleft()
            _validate_value(key, value)
            result[key] = value
        else:
            logger.warning(
                "Unexpected label on %s detail page: %r (value=%r); keeping as extra column",
                kind, label, value,
            )
            slug = _slugify(label)
            base_slug = slug
            suffix = 2
            while slug in used_slugs or slug in result:
                slug = f"{base_slug}_{suffix}"
                suffix += 1
            used_slugs.add(slug)
            result[slug] = value

    missing = [label for label, key in expected if key not in result]
    if missing:
        raise ParseError(
            f"missing expected label(s) on {kind} detail page: {missing!r}"
        )

    return result


def validate_title(title: str, expected_account_name: str | None) -> None:
    """Sanity-check that a detail page's title mentions the expected
    account, guarding against silently reading the wrong account's data.

    Pass expected_account_name=None to skip the check (used for the device
    totals pages, which have no per-account name).
    """
    if expected_account_name is None:
        return
    normalized_title = _normalize(title)
    normalized_name = _normalize(expected_account_name)
    if normalized_name and normalized_name not in normalized_title:
        raise ParseError(
            f"detail page title {title!r} does not contain expected account name {expected_account_name!r}"
        )
