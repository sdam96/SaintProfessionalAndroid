from __future__ import annotations

from decimal import Decimal, InvalidOperation

import flet as ft


def to_decimal(text, default: Decimal = Decimal(0)) -> Decimal:
    try:
        return Decimal(str(text).replace(",", ".").strip() or "0")
    except InvalidOperation:
        return default


def field_text(control: ft.TextField) -> str:
    return (control.value or "").strip()


def rounded_border(radius: int = 10) -> ft.OutlineInputBorder:
    return ft.OutlineInputBorder(border_radius=radius)