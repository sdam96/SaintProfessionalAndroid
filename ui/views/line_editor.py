"""Editor for a single invoice line."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import flet as ft

from models import PRICE_LISTS, InvoiceLine

from ..context import AppContext
from ..theme import ACCENT, FIELD_MED, FIELD_NARROW, PRIMARY
from ..utils import rounded_border, to_decimal
from ..widgets import fields, section, set_status, status_text
from .serials import SerialPicker


class LineEditor:
    def __init__(self, ctx: AppContext, product: dict,
                 on_add: Callable[[InvoiceLine], None]):
        self._ctx = ctx
        self._product = product
        self._on_add = on_add
        self._serialised = bool(product.get("usesSerial"))
        self._chosen: list[str] = []
        _, _, price_key = PRICE_LISTS[ctx.invoice.price_list - 1]

        self._quantity = ft.TextField(
            label="Cantidad", value="1", autofocus=True, width=FIELD_NARROW,
            border=rounded_border(10), keyboard_type=ft.KeyboardType.NUMBER)
        self._price = ft.TextField(
            label="Precio unitario", width=FIELD_MED,
            value=f"{product.get(price_key, 0)}", border=rounded_border(10),
            keyboard_type=ft.KeyboardType.NUMBER)
        self._discount = ft.TextField(
            label="Descuento %", value="0", width=FIELD_NARROW,
            border=rounded_border(10), keyboard_type=ft.KeyboardType.NUMBER)
        self._warehouse = ft.Dropdown(
            label="Depósito", value=ctx.invoice.warehouse, width=FIELD_MED,
            border=rounded_border(10),
            options=[ft.DropdownOption(key=w["code"], text=w["name"])
                     for w in ctx.warehouses])
        self._message = status_text()
        self._serials_summary = ft.Text("", size=12,
                                        color=ft.Colors.PURPLE_700)
        self._serials_button = ft.FilledTonalButton(
            content="Seleccionar seriales", icon=ft.Icons.QR_CODE,
            height=44, on_click=self._choose_serials)

        # Changing either invalidates the serials already picked.
        self._quantity.on_change = self._reset_serials
        self._warehouse.on_change = self._reset_serials

    async def open(self) -> None:
        controls: list[ft.Control] = [
            self._header(),
            section("Cantidad y precio", ft.Icons.CALCULATE,
                    fields(self._quantity, self._price, self._discount)),
            section("Ubicación", ft.Icons.WAREHOUSE,
                    fields(self._warehouse), colour=ACCENT),
        ]
        if self._serialised:
            controls.append(
                section("Seriales", ft.Icons.QR_CODE,
                        ft.Row([self._serials_button]),
                        self._serials_summary,
                        colour=ft.Colors.PURPLE_600))
        controls += [
            self._message,
            ft.Row([ft.Button(content="Agregar renglón", icon=ft.Icons.ADD,
                              height=48, expand=True, on_click=self._add)]),
        ]

        self._refresh_serials()
        await self._ctx.navigator.push(
            "/line", "Renglón",
            ft.Column(controls, spacing=14, scroll=ft.ScrollMode.AUTO,
                      expand=True))

    def _header(self) -> ft.Container:
        product = self._product
        return ft.Container(
            padding=16, border_radius=12,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[PRIMARY, ft.Colors.INDIGO_400]),
            content=ft.Row(spacing=12, controls=[
                ft.Container(
                    width=44, height=44, border_radius=12,
                    bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.WHITE),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.INVENTORY_2, size=22,
                                    color=ft.Colors.WHITE)),
                ft.Column(expand=True, spacing=2, controls=[
                    ft.Text(product["name"], size=16,
                            weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f'{product["code"]}    '
                            f'IVA {product.get("taxRate", 0):g}%    '
                            f'{product.get("unit", "")}',
                            size=12,
                            color=ft.Colors.with_opacity(0.8,
                                                         ft.Colors.WHITE)),
                ]),
            ]))

    @property
    def _line_warehouse(self) -> str:
        return self._warehouse.value or self._ctx.invoice.warehouse

    # ------------------------------------------------------------ serials

    def _refresh_serials(self) -> None:
        if not self._serialised:
            return
        if self._chosen:
            self._serials_summary.value = (
                f"{len(self._chosen)} seleccionados: "
                + ", ".join(self._chosen))
        else:
            self._serials_summary.value = "Ningún serial seleccionado."
        self._ctx.page.update()

    async def _choose_serials(self, e) -> None:
        # The warehouse drives which serials are on hand, so it has to be
        # settled before picking.
        wanted = to_decimal(self._quantity.value)
        if wanted <= 0 or wanted != int(wanted):
            set_status(self._message,
                       "Indique una cantidad entera antes de elegir los "
                       "seriales.", error=True)
            self._ctx.page.update()
            return
        await SerialPicker(self._ctx, self._product["code"],
                           self._line_warehouse, int(wanted), self._chosen,
                           on_done=self._refresh_serials).open()

    def _reset_serials(self, e) -> None:
        if self._serialised and self._chosen:
            self._chosen.clear()
            self._refresh_serials()

    # ---------------------------------------------------------------- add

    def _validation_error(self, qty: Decimal, rate: Decimal) -> str | None:
        if qty <= 0:
            return "La cantidad debe ser mayor que cero."
        if rate < 0 or rate > 100:
            return "El descuento debe estar entre 0 y 100."
        if self._serialised:
            if qty != int(qty):
                return ("Un producto con seriales no admite cantidades "
                        "fraccionarias.")
            if len(self._chosen) != int(qty):
                return (f"Seleccione {int(qty)} seriales; "
                        f"hay {len(self._chosen)}.")
        return None

    async def _add(self, e) -> None:
        qty = to_decimal(self._quantity.value)
        rate = to_decimal(self._discount.value)
        error = self._validation_error(qty, rate)
        if error:
            set_status(self._message, error, error=True)
            return

        product = self._product
        self._on_add(InvoiceLine(
            product_code=product["code"],
            description=product["name"],
            quantity=qty,
            unit_price=to_decimal(self._price.value),
            tax_rate=to_decimal(product.get("taxRate", 0)),
            exempt=bool(product.get("exempt")),
            discount_rate=rate,
            warehouse=self._line_warehouse,
            serials=list(self._chosen),
        ))
        await self._ctx.navigator.back()