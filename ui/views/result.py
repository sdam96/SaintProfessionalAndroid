"""Shown once an invoice is issued, or saved to be sent later.

Laid out like the printed invoice: header, customer, lines, totals and
payment, on a sheet that scrolls on its own. "Nueva factura" sits in a bar
fixed under it, so it is always in reach without scrolling; it is also the
only way out of this screen (the app bar has no back arrow and the back
gesture is blocked).

The server's answer carries the number, control and totals, but not the
lines or the payment split. Those come from the invoice that was just
sent, still in ctx.invoice until "Nueva factura" clears it.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import flet as ft

from models import Invoice

from ..context import AppContext
from ..theme import ACCENT, MUTED, PRIMARY, bottom_allowance
from ..utils import to_decimal

# Lines shown before "Ver todos" on a long invoice.
VISIBLE_LINES = 5

# Monospaced digits keep the decimals of every amount in one column, as on
# a printed invoice.
AMOUNT_FONT = "monospace"

ISSUED_COLOUR = ft.Colors.GREEN_700
PENDING_COLOUR = ft.Colors.DEEP_ORANGE_800


# ------------------------------------------------------------------ helpers

def _money(value) -> str:
    return f"{to_decimal(value):,.2f}"


def _quantity(value: Decimal) -> str:
    """1 instead of 1.000, 2.5 instead of 2.500."""
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _rate(value: Decimal) -> str:
    return f"{value:g}"


def _caption(text: str) -> ft.Text:
    return ft.Text(text.upper(), size=11, color=MUTED,
                   weight=ft.FontWeight.BOLD)


def _amount(value: str, *, size: int = 14, bold: bool = False,
            colour: str | None = None) -> ft.Text:
    return ft.Text(value, size=size, color=colour,
                   font_family=AMOUNT_FONT, text_align=ft.TextAlign.RIGHT,
                   weight=ft.FontWeight.BOLD if bold else ft.FontWeight.W_500)


def _amount_row(label: str, value: str, *, bold: bool = False,
                size: int = 14, colour: str | None = None) -> ft.Row:
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(label, size=size - 1, color=colour or MUTED,
                    weight=ft.FontWeight.BOLD if bold else None,
                    expand=True),
            _amount(value, size=size, bold=bold, colour=colour),
        ])


def _rule() -> ft.Divider:
    return ft.Divider(height=24, thickness=1, color=ft.Colors.BLUE_GREY_100)


def _chip(text: str, icon: str, colour: str) -> ft.Container:
    return ft.Container(
        padding=ft.Padding(left=8, top=4, right=10, bottom=4),
        border_radius=20,
        bgcolor=ft.Colors.with_opacity(0.12, colour),
        content=ft.Row(tight=True, spacing=4, controls=[
            ft.Icon(icon, size=14, color=colour),
            ft.Text(text, size=11, color=colour,
                    weight=ft.FontWeight.BOLD),
        ]))


# ------------------------------------------------------------------ sections

def _header(result: dict, saved_offline: bool) -> ft.Column:
    date = str(result.get("date", "")).replace("T", " ")

    if saved_offline:
        reference = str(result.get("offlineId", ""))[:8].upper()
        return ft.Column(spacing=6, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                _chip("NO EMITIDA", ft.Icons.CLOUD_UPLOAD, PENDING_COLOUR),
                ft.Text(date, size=12, color=MUTED),
            ]),
            ft.Text("Factura pendiente de envío", size=20,
                    weight=ft.FontWeight.BOLD, color=PENDING_COLOUR),
            ft.Text("Sin número: se asignará al enviarla", size=13,
                    color=MUTED),
            ft.Container(
                padding=10, border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.08, PENDING_COLOUR),
                content=ft.Text(
                    "Se enviará sola en cuanto el teléfono vuelva a "
                    "conectarse con el servidor, y entonces recibe su número "
                    "y la fecha de ese día. Si los precios, la existencia o "
                    "el crédito del cliente cambiaron, quedará retenida "
                    "para que la revise.",
                    size=12, color=PENDING_COLOUR)),
            ft.Text(f"Referencia: {reference}", size=11, color=MUTED,
                    selectable=True),
        ])

    return ft.Column(spacing=4, controls=[
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
            _chip("EMITIDA", ft.Icons.CHECK_CIRCLE, ISSUED_COLOUR),
            ft.Text(date, size=12, color=MUTED),
        ]),
        ft.Container(height=4),
        _caption("Factura"),
        ft.Text(f'N° {result.get("number", "")}', size=24,
                weight=ft.FontWeight.BOLD),
        ft.Text(f'Control: {result.get("invoiceControl", "")}', size=11,
                color=MUTED, selectable=True),
    ])


def _customer(invoice: Invoice) -> ft.Column:
    controls: list[ft.Control] = [
        _caption("Cliente"),
        ft.Text(invoice.customer_name or invoice.customer_code, size=15,
                weight=ft.FontWeight.BOLD),
    ]
    if invoice.customer_code:
        controls.append(ft.Text(f"Código: {invoice.customer_code}",
                                size=12, color=MUTED))
    seller = invoice.salesperson_name or invoice.salesperson_code
    if seller:
        controls.append(ft.Text(f"Vendedor: {seller}", size=12, color=MUTED))
    return ft.Column(spacing=2, controls=controls)


def _line(line) -> ft.Column:
    detail = f"{_quantity(line.quantity)} × {line.unit_price:,.2f}"
    if line.discount_amount > 0:
        detail += f" · desc. {line.discount_amount:,.2f}"
    elif line.discount_rate > 0:
        detail += f" · desc. {_rate(line.discount_rate)}%"
    detail += " · exento" if line.exempt else f" · IVA {_rate(line.tax_rate)}%"
    return ft.Column(spacing=0, controls=[
        ft.Text(line.description, size=14, weight=ft.FontWeight.W_500,
                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
            ft.Text(detail, size=12, color=MUTED, expand=True),
            _amount(f"{line.net:,.2f}"),
        ]),
    ])


def _lines(invoice: Invoice, page: ft.Page) -> ft.Column:
    lines = [_line(line) for line in invoice.lines]
    shown = ft.Column(spacing=10, controls=lines[:VISIBLE_LINES])
    column = ft.Column(spacing=10, controls=[
        _caption(f"Detalle ({len(lines)} "
                 f"{'renglón' if len(lines) == 1 else 'renglones'})"),
        shown,
    ])

    hidden = lines[VISIBLE_LINES:]
    if hidden:
        def show_all(e) -> None:
            shown.controls = lines
            more.visible = False
            page.update()

        more = ft.TextButton(content=f"Ver todos ({len(lines)})",
                             icon=ft.Icons.EXPAND_MORE, on_click=show_all)
        column.controls.append(more)
    return column


def _totals(result: dict, invoice: Invoice,
            saved_offline: bool) -> ft.Column:
    # The server's figures once issued; the phone's own while it waits.
    if saved_offline:
        gross, discount = invoice.gross, invoice.discount
        tax, igtf, total = invoice.tax, invoice.igtf, invoice.total
    else:
        gross = to_decimal(result.get("base", 0))
        discount = to_decimal(result.get("discount", 0))
        tax = to_decimal(result.get("tax", 0))
        igtf = to_decimal(result.get("igtf", 0))
        total = to_decimal(result.get("total", 0))

    rows: list[ft.Control] = [_caption("Totales")]
    if discount > 0:
        rows += [_amount_row("Bruto", f"{gross:,.2f}"),
                 _amount_row("Descuento", f"-{discount:,.2f}")]
    rows.append(_amount_row("Subtotal", f"{gross - discount:,.2f}"))

    if invoice.exempt_base > 0:
        rows.append(_amount_row("Exento", f"{invoice.exempt_base:,.2f}"))

    breakdown = invoice.tax_breakdown()
    if len(breakdown) == 1:
        rate, base, _ = breakdown[0]
        rows.append(_amount_row(
            f"IVA {_rate(rate)}% s/ {base:,.2f}", f"{tax:,.2f}"))
    else:
        for rate, base, rate_tax in breakdown:
            rows.append(_amount_row(
                f"IVA {_rate(rate)}% s/ {base:,.2f}", f"{rate_tax:,.2f}",
                size=13))
        rows.append(_amount_row("Total IVA", f"{tax:,.2f}"))

    if igtf > 0:
        rows.append(_amount_row(f"IGTF {_rate(invoice.igtf_rate)}%",
                                f"{igtf:,.2f}"))

    rows += [
        ft.Divider(height=12, thickness=1, color=ft.Colors.BLUE_GREY_200),
        _amount_row("TOTAL", f"{total:,.2f}", bold=True, size=20,
                    colour=ft.Colors.BLACK),
    ]
    if invoice.reference_rate > 0:
        rows.append(_amount_row(
            f"Equivalente en {invoice.reference_label} "
            f"(tasa {invoice.reference_rate:,.2f})",
            f"{total / invoice.reference_rate:,.2f}", size=13,
            colour=ACCENT))
    return ft.Column(spacing=6, controls=rows)


def _payment(result: dict, invoice: Invoice,
             saved_offline: bool) -> ft.Column | None:
    if saved_offline:
        financed = invoice.financed
        paid = invoice.payable
        due = (f"{invoice.credit_days} días" if invoice.credit_days else "")
    else:
        financed = to_decimal(result.get("financed", 0))
        paid = to_decimal(result.get("paid", 0))
        due = str(result.get("dueDate", ""))

    used = [p for p in invoice.payments if p.amount > 0]
    if not used and paid <= 0 and financed <= 0:
        return None

    title: list[ft.Control] = [_caption("Pago")]
    if invoice.foreign_currency:
        title.append(_chip("EN DIVISAS", ft.Icons.ATTACH_MONEY, ACCENT))
    rows: list[ft.Control] = [
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=title)]

    if used:
        for slot in used:
            # Which instruments were paid in divisas: only those bore IGTF.
            label = (f"{slot.label} (divisas)" if slot.foreign_currency
                     else slot.label)
            rows.append(_amount_row(label, f"{slot.amount:,.2f}"))
    elif paid > 0:
        # Nothing assigned to a slot: the server takes it all as cash.
        rows.append(_amount_row("Efectivo", f"{paid:,.2f}"))

    if financed > 0:
        if len(used) > 1:
            rows.append(_amount_row("Cobrado", f"{paid:,.2f}", bold=True,
                                    colour=ISSUED_COLOUR))
        rows.append(_amount_row("A crédito", f"{financed:,.2f}", bold=True,
                                colour=ft.Colors.ORANGE_800))
        if due:
            rows.append(_amount_row("Vencimiento", due, size=13))
    return ft.Column(spacing=6, controls=rows)


def _sheet(ctx: AppContext, result: dict, saved_offline: bool) -> ft.Container:
    invoice = ctx.invoice
    controls: list[ft.Control] = [
        _header(result, saved_offline), _rule(),
        _customer(invoice), _rule(),
        _lines(invoice, ctx.page), _rule(),
        _totals(result, invoice, saved_offline),
    ]
    payment = _payment(result, invoice, saved_offline)
    if payment is not None:
        controls += [_rule(), payment]

    return ft.Container(
        padding=18, border_radius=12, bgcolor=ft.Colors.WHITE,
        border=ft.Border.all(
            2 if saved_offline else 1,
            PENDING_COLOUR if saved_offline else ft.Colors.BLUE_GREY_100),
        shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                            color=ft.Colors.with_opacity(0.08,
                                                         ft.Colors.BLACK),
                            offset=ft.Offset(0, 2)),
        content=ft.Column(spacing=0, controls=controls))


# ------------------------------------------------------------------- screen

async def open_result_view(ctx: AppContext, result: dict,
                           on_new_invoice: Callable[[], None],
                           saved_offline: bool = False) -> None:
    async def start_over(e) -> None:
        on_new_invoice()
        await ctx.navigator.back()

    new_invoice = ft.Button(
        content="Nueva factura", icon=ft.Icons.ADD, height=52, expand=True,
        bgcolor=PENDING_COLOUR if saved_offline else PRIMARY,
        color=ft.Colors.WHITE, on_click=start_over)

    # Only the sheet scrolls. The bar under it stays put, lifted clear of
    # Android's navigation bar by the same allowance every screen uses.
    body = ft.Column(expand=True, spacing=0, controls=[
        ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, controls=[
            _sheet(ctx, result, saved_offline),
            ft.Container(height=8),
        ]),
        ft.Container(padding=ft.Padding(left=0, top=12, right=0, bottom=0),
                     content=ft.Row([new_invoice])),
        bottom_allowance(),
    ])

    title = "Guardada sin conexión" if saved_offline else "Factura emitida"
    await ctx.navigator.push("/result", title, body, show_back=False)
