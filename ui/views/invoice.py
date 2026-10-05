from __future__ import annotations

from collections.abc import Callable

import flet as ft

from api_client import ApiError
from models import PRICE_LISTS, InvoiceLine

from ..context import AppContext
from ..theme import (ACCENT, BACKGROUND, DANGER, FIELD_MED, MUTED, PRIMARY,
                     PRIMARY_DARK)
from ..utils import rounded_border, to_decimal
from ..widgets import badge, fields, set_status, status_text, tag_row
from .customer_form import CustomerForm
from .line_editor import LineEditor
from .pickers import (open_customer_picker, open_product_picker,
                      open_salesperson_picker)
from .result import open_result_view
from .totalise import TotaliseView
from .totals_panel import TotalsPanel


def _line_card(index: int, line: InvoiceLine,
               warehouse_name: Callable[[str], str],
               on_remove: Callable[[int], None]) -> ft.Card:
    detail = f"{line.quantity:g} × {line.unit_price:,.2f}"
    if line.discount_rate > 0:
        detail += f"   −{line.discount_rate:g}%"

    tags = []
    if line.exempt:
        tags.append(("exento", ft.Colors.TEAL_700))
    else:
        tags.append((f"IVA {line.tax_rate:g}%", PRIMARY))
    tags.append((warehouse_name(line.warehouse), MUTED))
    if line.serials:
        tags.append((f"{len(line.serials)} S/N", ft.Colors.PURPLE_700))

    return ft.Card(elevation=1, content=ft.Container(
        padding=12, border_radius=12,
        content=ft.Row(spacing=12, controls=[
            badge(ft.Text(str(index + 1), size=14,
                          weight=ft.FontWeight.BOLD, color=PRIMARY),
                  PRIMARY, size=36, opacity=0.12),
            ft.Column(expand=True, spacing=4, controls=[
                ft.Text(line.description, size=15,
                        weight=ft.FontWeight.W_500, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{line.product_code}    {detail}", size=12,
                        color=MUTED),
                tag_row(tags, run_spacing=6),
            ]),
            ft.Column(horizontal_alignment=ft.CrossAxisAlignment.END,
                      spacing=4, controls=[
                          ft.Text(f"{line.net:,.2f}", size=17,
                                  weight=ft.FontWeight.BOLD,
                                  color=PRIMARY_DARK),
                          ft.IconButton(ft.Icons.DELETE_OUTLINE,
                                        icon_color=DANGER, icon_size=20,
                                        on_click=lambda e: on_remove(index)),
                      ]),
        ]),
    ))


def _empty_lines() -> ft.Container:
    return ft.Container(
        padding=48, alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                badge(ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, size=34,
                              color=PRIMARY),
                      PRIMARY, size=72, opacity=0.08),
                ft.Text("Sin renglones", size=15, color=MUTED,
                        weight=ft.FontWeight.W_500),
                ft.Text("Agregue productos para comenzar", size=12,
                        color=ft.Colors.BLUE_GREY_400),
            ]),
    )


class InvoiceScreen:
    def __init__(self, ctx: AppContext):
        self._ctx = ctx
        self._invoice = ctx.invoice
        self._totals = TotalsPanel()

        self._customer_button = ft.OutlinedButton(
            content="Seleccionar cliente", icon=ft.Icons.PERSON, expand=True,
            on_click=self._open_customer_picker)
        self._salesperson_button = ft.OutlinedButton(
            content="Vendedor 01", icon=ft.Icons.BADGE, expand=True,
            on_click=self._open_salesperson_picker)

        self._price_list = ft.Dropdown(
            label="Lista de precio", width=FIELD_MED, value="1",
            border=rounded_border(10),
            options=[ft.DropdownOption(key=str(k), text=t)
                     for k, t, _ in PRICE_LISTS])
        self._warehouse = ft.Dropdown(
            label="Depósito", width=FIELD_MED, value="01",
            border=rounded_border(10))
        self._foreign_switch = ft.Switch(label="Pago en divisa", value=False,
                                         active_color=ACCENT)
        for control in (self._price_list, self._warehouse,
                        self._foreign_switch):
            control.on_change = self._on_input_change

        self._lines = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO,
                                expand=True)

        self._totalise_button = ft.FilledTonalButton(
            content="Totalizar", icon=ft.Icons.CALCULATE, expand=True,
            height=44, on_click=self._open_totalise)
        self._message = status_text()
        self._issue_button = ft.Button(
            content="Emitir factura", icon=ft.Icons.CHECK_CIRCLE, height=52,
            expand=True, on_click=self._issue)

    # ------------------------------------------------------------- layout

    async def show(self, info: dict) -> None:
        self._warehouse.options = [
            ft.DropdownOption(key=w["code"], text=w["name"])
            for w in self._ctx.warehouses]
        if self._ctx.warehouses:
            self._warehouse.value = self._invoice.warehouse

        view = ft.View(
            route="/invoice",
            bgcolor=BACKGROUND,
            appbar=ft.AppBar(
                title=ft.Text("Nueva factura", weight=ft.FontWeight.W_500),
                bgcolor=PRIMARY, color=ft.Colors.WHITE, elevation=2,
                actions=[ft.IconButton(
                    ft.Icons.INFO_OUTLINE, icon_color=ft.Colors.WHITE,
                    tooltip=f'{info.get("baseDatos", "")} · '
                            f'est. {info.get("estacion", "")}')],
            ),
            padding=0,
            controls=[self._body()],
        )
        await self._ctx.navigator.set_root(view, navigate=True)
        self.refresh_lines()

    def _header(self) -> ft.Container:
        return ft.Container(
            padding=16,
            bgcolor=ft.Colors.WHITE,
            content=ft.Column(spacing=12, controls=[
                ft.Row([self._customer_button]),
                ft.Row([self._salesperson_button]),
                fields(self._price_list, self._warehouse),
                ft.Row([ft.FilledTonalButton(
                    content="Agregar producto",
                    icon=ft.Icons.ADD_SHOPPING_CART,
                    expand=True, height=46,
                    on_click=self._open_product_picker)]),
            ]),
        )

    def _body(self) -> ft.Control:
        header = self._header()
        lines_pane = ft.Container(
            expand=True,
            padding=ft.Padding(left=16, right=16, top=12, bottom=0),
            content=self._lines)
        panel = self._totals.build(
            foreign_switch=self._foreign_switch,
            totalise_button=self._totalise_button,
            message=self._message,
            issue_button=self._issue_button)

        if self._ctx.is_tablet():
            return ft.Row(expand=True, spacing=0, controls=[
                ft.Container(expand=3, content=ft.Column(
                    [header, lines_pane], expand=True, spacing=0)),
                ft.VerticalDivider(width=1),
                ft.Container(expand=2, padding=12, bgcolor=BACKGROUND,
                             content=ft.Column([panel],
                                               scroll=ft.ScrollMode.AUTO)),
            ])
        return ft.Column(expand=True, spacing=0,
                         controls=[header, lines_pane, panel])

    # ------------------------------------------------------------ refresh

    def refresh_totals(self) -> None:
        invoice = self._invoice
        invoice.price_list = int(to_decimal(self._price_list.value, 1))
        invoice.warehouse = self._warehouse.value or invoice.warehouse
        invoice.foreign_currency = self._foreign_switch.value
        self._totals.refresh(invoice)

    def refresh_lines(self) -> None:
        if self._invoice.lines:
            self._lines.controls = [
                _line_card(i, line, self._ctx.warehouse_name,
                           self._remove_line)
                for i, line in enumerate(self._invoice.lines)]
        else:
            self._lines.controls = [_empty_lines()]
        self.refresh_totals()

    def _on_input_change(self, e) -> None:
        self.refresh_totals()

    def _invalidate_payments(self) -> None:
        self._invoice.payments.clear()
        self._totalise_button.content = "Totalizar"

    # ----------------------------------------------------------- customer

    async def _open_customer_picker(self, e=None) -> None:
        await open_customer_picker(self._ctx, on_pick=self._select_customer,
                                   on_create=self._open_customer_form)

    async def _open_customer_form(self) -> None:
        await CustomerForm(self._ctx,
                           on_created=self._customer_created).open()

    def _set_customer(self, code: str, name: str) -> None:
        self._invoice.customer_code = code
        self._invoice.customer_name = name
        self._customer_button.content = f"{code} — {name}"

    def _select_customer(self, item: dict) -> None:
        self._set_customer(item["code"], item["name"])
        if item.get("priceList"):
            self._price_list.value = str(item["priceList"])
        if (item.get("salesperson") or "").strip():
            self._invoice.salesperson_code = item["salesperson"]
            self._salesperson_button.content = (
                f'Vendedor {item["salesperson"]}')
        if item.get("creditDays"):
            self._invoice.credit_days = int(item["creditDays"])
        self.refresh_totals()

    def _customer_created(self, created: dict) -> None:
        self._set_customer(created["code"], created["name"])
        if created.get("priceList"):
            self._price_list.value = str(created["priceList"])
        self.refresh_totals()

    # -------------------------------------------------------- salesperson

    async def _open_salesperson_picker(self, e=None) -> None:
        await open_salesperson_picker(self._ctx,
                                      on_pick=self._select_salesperson)

    def _select_salesperson(self, item: dict) -> None:
        self._invoice.salesperson_code = item["code"]
        self._invoice.salesperson_name = item["name"]
        self._salesperson_button.content = f'{item["code"]} — {item["name"]}'

    # -------------------------------------------------------------- lines

    async def _open_product_picker(self, e=None) -> None:
        await open_product_picker(self._ctx, on_pick=self._open_line_editor)

    async def _open_line_editor(self, product: dict) -> None:
        await LineEditor(self._ctx, product, on_add=self._add_line).open()

    def _add_line(self, line: InvoiceLine) -> None:
        self._invoice.lines.append(line)
        self._invalidate_payments()
        self.refresh_lines()

    def _remove_line(self, index: int) -> None:
        self._invoice.lines.pop(index)
        self._invalidate_payments()
        self.refresh_lines()

    # ----------------------------------------------------------- totalise

    async def _open_totalise(self, e=None) -> None:
        if not self._invoice.lines:
            set_status(self._message, "Agregue al menos un renglón.",
                       error=True)
            self._ctx.page.update()
            return
        await TotaliseView(self._ctx, on_saved=self._totalise_saved).open()

    def _totalise_saved(self) -> None:
        count = len(self._invoice.payments)
        self._totalise_button.content = (
            f"Totalizado ({count})" if count else "Totalizar")
        self.refresh_totals()

    # -------------------------------------------------------------- issue

    async def _issue(self, e) -> None:
        if not self._invoice.customer_code:
            set_status(self._message, "Seleccione un cliente.", error=True)
            return
        if not self._invoice.lines:
            set_status(self._message, "Agregue al menos un renglón.",
                       error=True)
            return

        page = self._ctx.page
        self._issue_button.disabled = True
        self._issue_button.content = "Emitiendo…"
        self._message.value = ""
        page.update()

        try:
            result = await self._ctx.api.create_invoice(
                self._invoice.to_json())
        except ApiError as exc:
            set_status(self._message, str(exc), error=True)
            return
        except Exception as exc:
            set_status(self._message, f"Error inesperado: {exc}", error=True)
            return
        finally:
            self._issue_button.disabled = False
            self._issue_button.content = "Emitir factura"
            page.update()

        await open_result_view(self._ctx, result,
                               on_new_invoice=self._new_invoice)

    def _new_invoice(self) -> None:
        self._invoice.reset()
        self._customer_button.content = "Seleccionar cliente"
        self._totalise_button.content = "Totalizar"
        self._foreign_switch.value = False
        self._message.value = ""
        self.refresh_lines()