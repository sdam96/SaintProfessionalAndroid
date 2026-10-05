"""State shared by every screen of a session."""

from __future__ import annotations

from dataclasses import dataclass, field

import flet as ft

from api_client import ApiClient
from models import STOCK_COLUMNS, Invoice

from .navigation import Navigator
from .theme import TABLET_BREAKPOINT


@dataclass
class AppContext:
    page: ft.Page
    navigator: Navigator
    api: ApiClient = field(default_factory=ApiClient)
    invoice: Invoice = field(default_factory=Invoice)
    # Filled in place on connect, so every holder sees the same list.
    warehouses: list[dict] = field(default_factory=list)

    def is_tablet(self) -> bool:
        return (self.page.width or 0) >= TABLET_BREAKPOINT

    def warehouse_name(self, code: str) -> str:
        for item in self.warehouses:
            if item["code"] == code:
                return item["name"]
        return code

    def stock_column(self) -> str:
        """The stock column matching the selected warehouse position."""
        for index, item in enumerate(self.warehouses):
            if item["code"] == self.invoice.warehouse:
                if index < len(STOCK_COLUMNS):
                    return STOCK_COLUMNS[index]
                break
        return "stock"