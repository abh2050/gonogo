"""Small helpers that several rules share."""

from __future__ import annotations

from datetime import date


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def day(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def money_free_label(*parts: str | None) -> str:
    return ", ".join(p for p in parts if p)
