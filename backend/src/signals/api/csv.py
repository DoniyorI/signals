"""CSV export for list endpoints (`format=csv`).

Columns come from the response model, so an empty export still has its header. Nested
models flatten to dotted keys (`issuer.name`), mapping fields to one column per key
(`windows.1y`), and lists join with ';' (a list of models gives one ';'-joined column per
field, such as `owners.name`).
"""

import csv
import io
import types
from collections.abc import Sequence
from typing import Any, Union, get_args, get_origin

from fastapi import Response
from pydantic import BaseModel


def csv_response(
    rows: Sequence[BaseModel], filename: str, *, model: type[BaseModel] | None = None
) -> Response:
    model = model or (type(rows[0]) if rows else None)
    flat = [_flatten(row.model_dump(mode="json")) for row in rows]
    if model is not None:
        columns = _columns(model, flat)
    else:
        columns = list(dict.fromkeys(key for row in flat for key in row))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows([row.get(column, "") for column in columns] for row in flat)
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}."))
        elif isinstance(value, list) and any(isinstance(item, dict) for item in value):
            items = [
                _flatten(item) if isinstance(item, dict) else {"": _cell(item)} for item in value
            ]
            for sub in dict.fromkeys(k for item in items for k in item):
                out[f"{name}.{sub}" if sub else name] = ";".join(
                    item.get(sub, "") for item in items
                )
        elif isinstance(value, list):
            out[name] = ";".join(_cell(item) for item in value)
        else:
            out[name] = _cell(value)
    return out


def _columns(model: type[BaseModel], flat: list[dict[str, str]], prefix: str = "") -> list[str]:
    columns: list[str] = []
    for name, field in model.model_fields.items():
        key = f"{prefix}{name}"
        nested = _nested_model(field.annotation)
        if nested is not None:
            columns += _columns(nested, flat, f"{key}.")
        elif _is_mapping(field.annotation):
            seen = dict.fromkeys(k for row in flat for k in row if k.startswith(f"{key}."))
            columns += list(seen) or [key]
        else:
            columns.append(key)
    return columns


def _options(annotation: Any) -> list[Any] | None:
    """The non-None members of an Optional/Union annotation, or None if it isn't one."""
    if get_origin(annotation) in (Union, types.UnionType):
        return [arg for arg in get_args(annotation) if arg is not type(None)]
    return None


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    options = _options(annotation)
    if options is not None:
        return _nested_model(options[0]) if len(options) == 1 else None
    if get_origin(annotation) is list:
        args = get_args(annotation)
        return _nested_model(args[0]) if args else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _is_mapping(annotation: Any) -> bool:
    options = _options(annotation)
    if options is not None:
        return any(_is_mapping(option) for option in options)
    return annotation is dict or get_origin(annotation) is dict
