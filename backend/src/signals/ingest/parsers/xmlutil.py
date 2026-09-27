"""Small, strict XML helpers shared by every SEC form parser."""

import re
from dataclasses import dataclass
from datetime import date, datetime

from lxml import etree

_PARSER = etree.XMLParser(
    recover=False, resolve_entities=False, no_network=True, remove_blank_text=True
)
_TZ_SUFFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})[+-]\d{2}:\d{2}$")
_DATE_FORMATS = ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%d-%b-%Y", "%Y%m%d")


@dataclass(frozen=True)
class FieldValue:
    value: str | None
    footnote_ids: tuple[str, ...]


def parse_xml(data: bytes) -> etree._Element:
    """Parse and strip namespaces from every tag, so paths never need prefixes."""
    root = etree.fromstring(data.strip(), _PARSER)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    etree.cleanup_namespaces(root)
    return root


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def text(el: etree._Element, path: str) -> str | None:
    found = el.find(path)
    return _clean(found.text) if found is not None else None


def field(el: etree._Element, path: str) -> FieldValue:
    """Read `path/value` (or `path` itself) plus any footnoteId ids under `path`."""
    node = el.find(path)
    if node is None:
        return FieldValue(None, ())
    value_node = node.find("value")
    raw = value_node.text if value_node is not None else node.text
    ids = tuple(fn.get("id", "") for fn in node.iter("footnoteId") if fn.get("id"))
    return FieldValue(_clean(raw), ids)


def to_bool(s: str | None) -> bool | None:
    if s is None:
        return None
    value = s.strip().lower()
    if value in ("1", "true", "yes", "y"):
        return True
    if value in ("0", "false", "no", "n"):
        return False
    return None


def to_float(s: str | None) -> float | None:
    if s is None:
        return None
    value = s.strip().replace(",", "").replace("$", "").rstrip("%").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def to_date(s: str | None) -> date | None:
    if s is None:
        return None
    value = s.strip()
    if not value:
        return None
    tz = _TZ_SUFFIX.match(value)
    if tz:
        value = tz.group(1)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
