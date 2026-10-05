"""Running totals shown under (or beside) the invoice lines."""

from __future__ import annotations

import flet as ft

from models import Invoice

from ..theme import MUTED, PRIMARY, PRIMARY_DARK
from ..widgets import amount_text

_WHITE_SOFT = ft.Colors.with_opacity(0.85, ft.Colors.WHITE)


def _labelled(label: str, control: ft.Control, size: int = 14,
              visible: bool = True, colour: str = MUTED) -> ft.Row:
    return ft.Row(
        visible=visible, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[ft.Text(label, size=size, color=colour), control])


def _tax_line(label: str, value: str, size: int = 14,
              colour: str = MUTED) -> ft.Row:
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(label, size=size, color=colour),
            ft.Text(value, size=size, color=colour),
        ])


class TotalsPanel:
    def __init__(self):
        self._gross = amount_text("0,00")
        self._line_discount = amount_text("0,00")
        self._global_discount = amount_text("0,00")
        self._subtotal = amount_text("0,00")
        self._tax = amount_text("0,00")
        self._igtf = amount_text("0,00")
        self._total = ft.Text("0,00", size=28, weight=ft.FontWeight.BOLD,
                              color=ft.Colors.WHITE)
        self._reference = ft.Text("", size=13, color=_WHITE_SOFT)
        self._paid = amount_text("0,00", size=13, colour=ft.Colors.GREEN_700)
        self._financed = amount_text("0,00", size=13,
                                     colour=ft.Colors.ORANGE_800)

        # Rows that only make sense for some invoices start hidden.
        self._global_discount_row = _labelled(
            "Descuento global", self._global_discount, visible=False)
        self._igtf_row = _labelled("IGTF", self._igtf, visible=False)
        self._reference_row = _labelled(
            "Equivalente", self._reference, size=13, visible=False,
            colour=_WHITE_SOFT)
        self._financed_row = _labelled(
            "Financiado", self._financed, size=13, visible=False)

        # The total tax line plus one row per tax rate, rebuilt on refresh.
        self._tax_breakdown = ft.Column(spacing=6)

    def refresh(self, invoice: Invoice) -> None:
        self._gross.value = f"{invoice.gross:,.2f}"
        self._line_discount.value = f"{invoice.line_discount:,.2f}"
        self._global_discount.value = f"{invoice.global_discount:,.2f}"
        self._subtotal.value = f"{invoice.subtotal:,.2f}"
        self._tax.value = f"{invoice.tax:,.2f}"
        self._igtf.value = f"{invoice.igtf:,.2f}"
        self._total.value = f"{invoice.total:,.2f}"
        self._paid.value = f"{invoice.paid:,.2f}"
        self._financed.value = f"{invoice.financed:,.2f}"

        # Total tax, then one indented line per rate present.
        tax_rows: list[ft.Control] = [
            _labelled("Impuesto", self._tax)]
        for rate, base, tax in invoice.tax_breakdown():
            tax_rows.append(_tax_line(
                f"    IVA {rate:g}% sobre {base:,.2f}", f"{tax:,.2f}",
                size=13, colour=ft.Colors.BLUE_GREY_500))
        self._tax_breakdown.controls = tax_rows

        self._global_discount_row.visible = invoice.global_discount > 0
        self._igtf_row.visible = invoice.igtf > 0
        self._financed_row.visible = invoice.financed > 0
        self._reference_row.visible = invoice.reference_rate > 0
        if invoice.reference_rate > 0:
            self._reference.value = (
                f"{invoice.total_in_reference:,.2f} {invoice.reference_label}"
                f"  @ {invoice.reference_rate:,.2f}")

    def build(self, *, foreign_switch: ft.Control,
              totalise_button: ft.Control, message: ft.Control,
              issue_button: ft.Control) -> ft.Container:
        total_block = ft.Container(
            padding=16, border_radius=12,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[PRIMARY_DARK, PRIMARY]),
            content=ft.Column(spacing=4, controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                       controls=[
                           ft.Text("TOTAL", size=13,
                                   weight=ft.FontWeight.BOLD,
                                   color=ft.Colors.with_opacity(
                                       0.8, ft.Colors.WHITE)),
                           self._total,
                       ]),
                self._reference_row,
            ]))

        return ft.Container(
            padding=16,
            bgcolor=ft.Colors.WHITE,
            border_radius=ft.BorderRadius(top_left=18, top_right=18,
                                          bottom_left=0, bottom_right=0),
            content=ft.Column(spacing=8, controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                       controls=[foreign_switch, totalise_button]),
                ft.Divider(height=6),
                _labelled("Bruto", self._gross),
                _labelled("Descuento", self._line_discount),
                self._global_discount_row,
                _labelled("Subtotal", self._subtotal),
                self._tax_breakdown,
                self._igtf_row,
                ft.Container(height=4),
                total_block,
                _labelled("Cobrado", self._paid, size=13),
                self._financed_row,
                message,
                ft.Row([issue_button]),
            ]),
        )