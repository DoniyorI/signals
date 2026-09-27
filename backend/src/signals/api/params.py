"""Query parameter types shared by every router, so the contract stays uniform."""

from datetime import date
from typing import Annotated, Literal

from fastapi import Query

Cursor = Annotated[str | None, Query(description="Opaque cursor from a previous next_cursor")]
Limit = Annotated[int, Query(ge=1, le=500)]
Format = Annotated[Literal["json", "csv"], Query(description="json (default) or csv")]
BasisQ = Annotated[Literal["filed", "executed"], Query()]
WindowQ = Annotated[Literal["ytd", "1y", "3y", "5y"], Query()]
StrList = Annotated[list[str] | None, Query()]
OptDate = Annotated[date | None, Query()]
OptFloat = Annotated[float | None, Query()]
OptInt = Annotated[int | None, Query()]
