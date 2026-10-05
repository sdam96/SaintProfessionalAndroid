"""Confirmation shown after an invoice is issued."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import flet as ft

from models import Invoice

from ..context import AppContext
from ..theme import ACCENT, BACKGROUND, MUTED
from ..utils import to_decimal
from ..widgets import section


def _row(label: str, value, bold: bool = False,
         colour: str | None = None) -> ft.Row:
    return ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
        ft.Text(label, size=13, color=colour or MUTED,
                weight=ft.FontWeight.BOLD if bold else None),
        ft.Text(str(value), size=14, color=colour,
                weight=ft.FontWeight.BOLD if bold else ft.FontWeight.W_500),
    ])


def _hero(result: dict, total: Decimal) -> ft.Container:
    return ft.Container(
        padding=24, border_radius=14,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[ft.Colors.GREEN_700, ft.Colors.TEAL_600]),
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            controls=[
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=46,
                        color=ft.Colors.WHITE),
                ft.Text("Factura emitida", size=19,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text(f'N° {result.get("number", "")}', size=14,
                        color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE)),
                ft.Container(height=6),
                ft.Text(f"{total:,.2f}", size=32,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
            ]))


def _detail_rows(result: dict, total: Decimal,
                 invoice: Invoice) -> list[ft.Control]:
    rows: list[ft.Control] = [
        _row("Fecha", result.get("date", "")),
        _row("Base", f'{result.get("base", 0):,.2f}'),
    ]
    if result.get("discount"):
        rows.append(_row("Descuento", f'{result["discount"]:,.2f}'))
    rows.append(_row("Impuesto", f'{result.get("tax", 0):,.2f}'))
    if result.get("igtf"):
        rows.append(_row("IGTF", f'{result["igtf"]:,.2f}'))
    if invoice.reference_rate > 0:
        rows.append(_row(f"Equivalente en {invoice.reference_label}",
                         f"{total / invoice.reference_rate:,.2f}",
                         colour=ACCENT))
    if result.get("financed"):
        rows += [
            ft.Divider(height=6),
            _row("Cobrado", f'{result.get("paid", 0):,.2f}',
                 colour=ft.Colors.GREEN_700),
            _row("Financiado", f'{result["financed"]:,.2f}',
                 colour=ft.Colors.ORANGE_800),
            _row("Vencimiento", result.get("dueDate", "")),
        ]
    return rows


async def open_result_view(ctx: AppContext, result: dict,
                           on_new_invoice: Callable[[], None]) -> None:
    total = to_decimal(result.get("total", 0))

    async def start_over(e) -> None:
        on_new_invoice()
        await ctx.navigator.back()

    await ctx.navigator.push("/result", "Resultado", ft.Column(
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=14,
        controls=[
            _hero(result, total),
            section("Detalle", ft.Icons.LIST_ALT,
                    *_detail_rows(result, total, ctx.invoice)),
            ft.Container(
                padding=12, border_radius=10, bgcolor=BACKGROUND,
                content=ft.Text(
                    f'Control: {result.get("invoiceControl", "")}',
                    size=11, color=MUTED, selectable=True)),
            ft.Row([ft.Button(content="Nueva factura", icon=ft.Icons.ADD,
                              height=48, expand=True,
                              on_click=start_over)]),
        ]), show_back=False)