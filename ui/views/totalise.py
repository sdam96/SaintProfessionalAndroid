"""Payment details: document conditions, breakdown and payment instruments.

The five instruments are the five slots of Saint's payment window and keep
its names. They are not all shown up front: the user adds the ones the
customer pays with, each at most once, and can remove them again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import flet as ft

from api_client import ApiError
from models import PaymentSlot

from ..context import AppContext
from ..theme import (ACCENT, DANGER, FIELD_MED, FIELD_NARROW,
                     FIELD_WIDE, MUTED, PRIMARY, PRIMARY_DARK, SURFACE,
                     bottom_allowance)
from ..utils import field_text, rounded_border, to_decimal
from ..widgets import badge, fields, section, set_status, status_text

# (key, label, icon, colour) for each slot of Saint's payment window.
PAYMENT_SLOTS = [
    ("cash", "Efectivo", ft.Icons.PAYMENTS, ft.Colors.GREEN_600),
    ("cheque", "Cheque", ft.Icons.RECEIPT, ft.Colors.ORANGE_700),
    ("card", "Tarjeta", ft.Icons.CREDIT_CARD, ft.Colors.BLUE_600),
    ("other1", "Otro instrumento 1", ft.Icons.ACCOUNT_BALANCE,
     ft.Colors.PURPLE_600),
    ("other2", "Otro instrumento 2", ft.Icons.ACCOUNT_BALANCE_WALLET,
     ft.Colors.BROWN_500),
]
_SLOT_SPEC = {key: (label, icon, colour)
              for key, label, icon, colour in PAYMENT_SLOTS}

# Cash only needs the amount: no number, bank or type.
_AMOUNT_ONLY_SLOTS = ("cash",)
# Slots whose "Tipo" is picked from cfinstru. Cheque is a fixed slot and
# takes no cfinstru code, so its type dropdown stays disabled.
_TYPE_SLOTS = ("card", "other1", "other2")
# Every slot except cash asks for a bank.
_BANK_SLOTS = ("cheque", "card", "other1", "other2")
# The server needs the instrument code of these to resolve TIPOCOBRO.
_OTHER_SLOTS = ("other1", "other2")


@dataclass
class _SlotFields:
    amount: ft.TextField
    reference: ft.TextField | None = None
    bank: ft.Dropdown | None = None        # from bancos
    instrument: ft.Dropdown | None = None  # "Tipo", from cfinstru


def _dropdown_value(control: ft.Dropdown | None) -> str:
    if control is None:
        return ""
    return (control.value or "").strip()


def _number_field(label: str, value: str, width: int = FIELD_MED
                  ) -> ft.TextField:
    return ft.TextField(label=label, width=width, border=rounded_border(10),
                        value=value, keyboard_type=ft.KeyboardType.NUMBER)


def _money_row(label: str, value: Decimal, bold: bool = False,
               colour: str | None = None) -> ft.Row:
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(label, size=13,
                    color=colour or (PRIMARY_DARK if bold else MUTED),
                    weight=ft.FontWeight.BOLD if bold else None),
            ft.Text(f"{value:,.2f}", size=14 if bold else 13,
                    color=colour or (PRIMARY_DARK if bold else None),
                    weight=ft.FontWeight.BOLD if bold else None),
        ])


def _label(code: str, name: str) -> str:
    return f"{code} — {name}" if name else code


class TotaliseView:
    def __init__(self, ctx: AppContext, on_saved: Callable[[], None],
                 allows_credit: bool = True):
        self._ctx = ctx
        self._invoice = ctx.invoice
        self._on_saved = on_saved
        self._allows_credit = allows_credit
        invoice = self._invoice

        self._global_discount = _number_field(
            "Descuento global %",
            f"{invoice.global_discount_rate:g}"
            if invoice.global_discount_rate else "")
        self._financed = _number_field(
            "Monto a financiar",
            f"{invoice.financed}"
            if invoice.financed and allows_credit else "")
        self._credit_days = _number_field(
            "Días de crédito",
            str(invoice.credit_days) if allows_credit else "0",
            width=FIELD_NARROW)
        # A customer without credit pays everything now.
        self._financed.disabled = not allows_credit
        self._credit_days.disabled = not allows_credit

        self._breakdown = ft.Column(spacing=6)
        self._summary_icon = ft.Icon(ft.Icons.INFO_OUTLINE, size=18,
                                     color=MUTED)
        self._summary = status_text()
        self._pickers_status = status_text("Cargando tipos y bancos…")
        self._save_button = ft.Button(
            content="Guardar", icon=ft.Icons.SAVE, height=44,
            on_click=lambda e: asyncio.create_task(self._save(e)))

        # Options from cfinstru and bancos; None until they load. Slots
        # added later take their options from here.
        self._instruments: list[dict] | None = None
        self._banks: list[dict] | None = None

        # Codes from a previous save, applied once the options load.
        self._initial_type: dict[str, str] = {}
        self._initial_bank: dict[str, str] = {}

        # Slots currently on screen, in the order they were added.
        self._slots: dict[str, _SlotFields] = {}
        self._slot_cards: dict[str, ft.Card] = {}
        self._slot_list = ft.Column(spacing=12)
        self._empty_hint = ft.Text(
            "Aún no hay instrumentos. Agregue abajo los que use el cliente.",
            size=13, color=MUTED)
        self._add_buttons = ft.Row(wrap=True, spacing=8, run_spacing=8)
        self._add_section = ft.Column(spacing=8, controls=[
            ft.Text("Agregar instrumento", size=13, color=MUTED,
                    weight=ft.FontWeight.W_500),
            self._add_buttons,
        ])

        for payment in invoice.payments:
            if payment.key in _SLOT_SPEC:
                self._add_slot(payment.key, existing=payment)
        self._refresh_slot_list()

        self._global_discount.on_change = self._recompute
        self._financed.on_change = self._recompute
        self._financed.on_focus = self._on_financed_focus
        self._credit_days.on_change = self._recompute

    # ------------------------------------------------------------- layout

    async def open(self) -> None:
        self._recompute()

        conditions = [fields(self._global_discount, self._financed,
                             self._credit_days)]
        if not self._allows_credit:
            conditions.append(ft.Text(
                "Cliente sin crédito: la factura debe pagarse completa.",
                size=12, color=ft.Colors.ORANGE_800))

        # Save and the balance stay pinned above the scrolling content, so
        # they are always in reach however many instruments are added.
        top_bar = ft.Container(
            padding=ft.Padding(left=14, right=10, top=10, bottom=10),
            border_radius=12, bgcolor=ft.Colors.WHITE,
            shadow=ft.BoxShadow(blur_radius=8, spread_radius=0,
                                offset=ft.Offset(0, 2),
                                color=ft.Colors.with_opacity(
                                    0.10, ft.Colors.BLACK)),
            content=ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self._summary_icon,
                    ft.Container(expand=True, content=self._summary),
                    self._save_button,
                ]))

        content = ft.Column(
            expand=True, scroll=ft.ScrollMode.AUTO, spacing=14,
            controls=[
                section("Condiciones del documento", ft.Icons.TUNE,
                        *conditions, colour=ft.Colors.ORANGE_700),
                ft.Text("Instrumentos de pago", size=15,
                        weight=ft.FontWeight.BOLD, color=PRIMARY_DARK),
                self._pickers_status,
                self._empty_hint,
                self._slot_list,
                self._add_section,
                ft.Card(elevation=2, content=ft.Container(
                    padding=18, border_radius=12, bgcolor=SURFACE,
                    content=ft.Column(spacing=6, controls=[
                        ft.Row(spacing=10, controls=[
                            ft.Icon(ft.Icons.RECEIPT_LONG, size=18,
                                    color=PRIMARY),
                            ft.Text("Desglose", size=15,
                                    weight=ft.FontWeight.BOLD,
                                    color=PRIMARY_DARK),
                        ]),
                        ft.Divider(height=1),
                        self._breakdown,
                    ]),
                )),
                bottom_allowance(),
            ])

        await self._ctx.navigator.push(
            "/payment", "Detalles de pago",
            ft.Column(expand=True, spacing=12, controls=[top_bar, content]))
        self._ctx.page.run_task(self._load_pickers)

    # -------------------------------------------------------------- slots

    def _add_slot(self, key: str, existing: PaymentSlot | None = None
                  ) -> None:
        label, icon, colour = _SLOT_SPEC[key]
        amount = _number_field("Monto",
                               f"{existing.amount}" if existing else "")
        amount.on_focus = lambda e: self._on_slot_focus(key)
        amount.on_change = self._recompute

        if key in _AMOUNT_ONLY_SLOTS:
            self._slots[key] = _SlotFields(amount)
            body = fields(amount)
        else:
            reference = ft.TextField(
                label="Número", width=FIELD_MED, border=rounded_border(10),
                value=existing.reference if existing else "")
            # Bank dropdown (from bancos) for every non-cash slot.
            bank = ft.Dropdown(
                label="Banco", width=FIELD_WIDE, border=rounded_border(10),
                options=[], disabled=True)
            # "Tipo" dropdown (from cfinstru). Cheque is fixed: disabled.
            instrument = ft.Dropdown(
                label="Tipo", width=FIELD_WIDE, border=rounded_border(10),
                options=[], disabled=True)
            if existing and existing.bank_code:
                self._initial_bank[key] = existing.bank_code
            if existing and existing.instrument:
                self._initial_type[key] = existing.instrument
            self._slots[key] = _SlotFields(amount, reference, bank,
                                           instrument)
            body = fields(amount, reference, instrument, bank)
            self._apply_options(key)

        card = ft.Card(elevation=1, content=ft.Container(
            padding=ft.Padding(left=16, right=8, top=10, bottom=16),
            border_radius=12,
            content=ft.Column(spacing=12, controls=[
                ft.Row(spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER,
                       controls=[
                           badge(ft.Icon(icon, size=18, color=colour),
                                 colour, size=32, opacity=0.12),
                           ft.Text(label, size=15, expand=True,
                                   weight=ft.FontWeight.BOLD,
                                   color=PRIMARY_DARK),
                           ft.IconButton(
                               ft.Icons.DELETE_OUTLINE, icon_color=DANGER,
                               tooltip=f"Quitar {label}",
                               on_click=lambda e: self._on_remove(key)),
                       ]),
                ft.Divider(height=1),
                body,
            ]),
        ))
        self._slot_cards[key] = card
        self._slot_list.controls.append(card)

    def _on_add(self, key: str) -> None:
        if key in self._slots:
            return
        self._add_slot(key)
        self._refresh_slot_list()
        self._recompute()

    def _on_remove(self, key: str) -> None:
        card = self._slot_cards.pop(key, None)
        if card is not None:
            self._slot_list.controls.remove(card)
        self._slots.pop(key, None)
        # Added again later, it starts empty.
        self._initial_type.pop(key, None)
        self._initial_bank.pop(key, None)
        self._refresh_slot_list()
        self._recompute()

    def _refresh_slot_list(self) -> None:
        """One add button per instrument not yet on screen."""
        unused = [(key, label, icon, colour)
                  for key, label, icon, colour in PAYMENT_SLOTS
                  if key not in self._slots]
        self._add_buttons.controls = [
            ft.OutlinedButton(
                content=label, icon=icon, icon_color=colour,
                on_click=lambda e, k=key: self._on_add(k))
            for key, label, icon, colour in unused]
        self._add_section.visible = bool(unused)
        self._empty_hint.visible = not self._slots

    # -------------------------------------------------------- pickers load

    def _apply_options(self, key: str) -> None:
        """Fills one slot's Tipo and Banco once the options are loaded."""
        slot = self._slots.get(key)
        if slot is None:
            return

        if key in _TYPE_SLOTS and self._instruments is not None:
            dd = slot.instrument
            codes = {r["code"] for r in self._instruments}
            dd.options = [ft.DropdownOption(key=r["code"],
                                            text=_label(r["code"], r["name"]))
                          for r in self._instruments]
            current = dd.value or self._initial_type.get(key, "")
            dd.value = current if current in codes else None
            dd.disabled = not self._instruments

        if key in _BANK_SLOTS and self._banks is not None:
            dd = slot.bank
            codes = {r["code"] for r in self._banks}
            dd.options = [ft.DropdownOption(key=r["code"],
                                            text=_label(r["code"], r["name"]))
                          for r in self._banks]
            current = dd.value or self._initial_bank.get(key, "")
            dd.value = current if current in codes else None
            dd.disabled = not self._banks

    async def _load_pickers(self) -> None:
        """Loads the Tipo (cfinstru) and Banco (bancos) options.

        Loaded on every opening so a type or bank created in Saint shows up
        without restarting the app.
        """
        page = self._ctx.page
        try:
            instruments = await self._ctx.catalog.payment_instruments()
            banks = await self._ctx.catalog.banks()
        except ApiError as exc:
            set_status(self._pickers_status,
                       f"No se pudieron cargar tipos/bancos: {exc}",
                       error=True)
            page.update()
            return

        self._instruments = instruments
        self._banks = banks
        for key in list(self._slots):
            self._apply_options(key)

        msgs = []
        if not instruments:
            msgs.append("No hay tipos de pago registrados.")
        if not banks:
            msgs.append("No hay bancos registrados.")
        set_status(self._pickers_status, "  ".join(msgs), error=bool(msgs))
        self._pickers_status.visible = bool(msgs)
        # Runs through run_task, so the automatic page update does not
        # apply here.
        page.update()

    # ------------------------------------------------------- calculations

    def _financed_value(self) -> Decimal:
        if not self._allows_credit:
            return Decimal(0)
        return to_decimal(self._financed.value)

    def _preview_total(self) -> Decimal:
        """The total under the discount and financing typed in here."""
        self._invoice.global_discount_rate = to_decimal(
            self._global_discount.value)
        self._invoice.financed = self._financed_value()
        return self._invoice.total

    def _slots_total(self, skip_key: str = "") -> Decimal:
        return sum((to_decimal(slot.amount.value)
                    for key, slot in self._slots.items() if key != skip_key),
                   Decimal(0))

    def _refresh_breakdown(self) -> None:
        total = self._preview_total()
        invoice = self._invoice
        controls: list[ft.Control] = [
            _money_row("Bruto", invoice.gross),
            _money_row("Descuento renglones", invoice.line_discount),
            _money_row("Descuento global", invoice.global_discount),
            ft.Divider(height=6),
            _money_row("Subtotal", invoice.subtotal),
        ]
        controls += self._tax_rows(invoice)
        if invoice.igtf > 0:
            controls.append(_money_row("IGTF", invoice.igtf))
        controls += [
            ft.Divider(height=6),
            _money_row("TOTAL", total, bold=True),
            _money_row("A financiar", invoice.financed,
                       colour=ft.Colors.ORANGE_800),
            _money_row("A cobrar", invoice.payable, bold=True,
                       colour=ft.Colors.GREEN_700),
        ]
        if invoice.reference_rate > 0:
            controls += self._reference_rows()
        self._breakdown.controls = controls

    def _tax_rows(self, invoice) -> list[ft.Control]:
        """Taxable base, exempt base, total tax, and the per-rate breakdown.

        The breakdown always follows the total tax line, one row per rate
        present, even when there is a single rate.
        """
        rows: list[ft.Control] = [
            _money_row("Base gravable", invoice.taxable_base),
            _money_row("Base exenta", invoice.exempt_base),
            _money_row("Impuesto", invoice.tax),
        ]
        for rate, base, tax in invoice.tax_breakdown():
            rows.append(_money_row(f"    IVA {rate:g}% sobre {base:,.2f}", tax))
        return rows

    def _reference_rows(self) -> list[ft.Control]:
        invoice = self._invoice
        return [
            ft.Divider(height=6),
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.Text(f"Equivalente en {invoice.reference_label}",
                        size=12, color=ACCENT),
                ft.Text(f"{invoice.total_in_reference:,.2f}", size=13,
                        color=ACCENT, weight=ft.FontWeight.BOLD),
            ]),
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.Text("Tasa", size=11, color=ft.Colors.BLUE_GREY_400),
                ft.Text(f"{invoice.reference_rate:,.2f}", size=11,
                        color=ft.Colors.BLUE_GREY_400),
            ]),
        ]

    def _set_summary(self, text: str, colour: str, icon=None) -> None:
        self._summary.value = text
        self._summary.color = colour
        if icon is not None:
            self._summary_icon.name = icon
            self._summary_icon.color = colour

    def _fail(self, text: str) -> None:
        self._set_summary(text, DANGER, ft.Icons.ERROR_OUTLINE)
        # _save runs as a task launched from a lambda, after the automatic
        # update of the click has already happened.
        self._ctx.page.update()

    def _recompute(self, e=None) -> None:
        self._refresh_breakdown()
        payable = self._invoice.payable
        assigned = self._slots_total()
        pending = payable - assigned
        if assigned == 0:
            if self._allows_credit:
                self._set_summary("Sin instrumentos: lo no financiado se "
                                  "cobra en efectivo.", MUTED,
                                  ft.Icons.INFO_OUTLINE)
            else:
                self._set_summary(f"Por cobrar: {payable:,.2f}",
                                  ft.Colors.ORANGE_800,
                                  ft.Icons.INFO_OUTLINE)
        elif pending == 0:
            self._set_summary(f"Cuadra: {payable:,.2f}",
                              ft.Colors.GREEN_700, ft.Icons.CHECK_CIRCLE)
        else:
            self._set_summary(f"Pendiente: {pending:,.2f}",
                              DANGER, ft.Icons.ERROR_OUTLINE)

    # ---------------------------------------------------- focus auto-fill

    def _on_slot_focus(self, key: str) -> None:
        """Fill the focused slot with whatever is still unassigned.

        Matches how Saint's payment window behaves: each field you land on
        proposes the remaining balance, so a single instrument takes the
        whole amount and the next one only what is left.
        """
        slot = self._slots.get(key)
        if slot is None or to_decimal(slot.amount.value) > 0:
            return
        self._preview_total()
        pending = self._invoice.payable - self._slots_total(skip_key=key)
        if pending > 0:
            slot.amount.value = f"{pending:.2f}"
            self._recompute()

    def _on_financed_focus(self, e) -> None:
        """Propose as financed whatever the instruments leave unassigned."""
        if not self._allows_credit or to_decimal(self._financed.value) > 0:
            return
        invoice = self._invoice
        invoice.global_discount_rate = to_decimal(self._global_discount.value)
        # Once anything is financed IGTF stops applying, so the reference
        # total is subtotal + tax, without IGTF.
        total = invoice.subtotal + invoice.tax
        pending = total - self._slots_total()
        if pending > 0:
            self._financed.value = f"{pending:.2f}"
            self._recompute()

    # --------------------------------------------------------------- save

    def _collect_slots(self) -> list[PaymentSlot] | None:
        """The filled slots, or None when one of them is incomplete."""
        slots = []
        # Saint's slot order, whatever order they were added in.
        for key, label, _, _ in PAYMENT_SLOTS:
            slot_fields = self._slots.get(key)
            if slot_fields is None:
                continue
            value = to_decimal(slot_fields.amount.value)
            if value <= 0:
                continue

            instrument = _dropdown_value(slot_fields.instrument)
            bank = _dropdown_value(slot_fields.bank)

            # The "other" slots need a type to resolve TIPOCOBRO.
            if key in _OTHER_SLOTS and not instrument:
                self._fail(f"Seleccione el tipo en {label}.")
                return None
            # Every non-cash slot needs a bank.
            if key in _BANK_SLOTS and not bank:
                self._fail(f"Seleccione el banco en {label}.")
                return None

            slots.append(PaymentSlot(
                key=key, label=label, amount=value,
                reference=field_text(slot_fields.reference)
                if slot_fields.reference is not None else "",
                bank_code=bank,
                instrument=instrument,
            ))
        return slots

    async def _save(self, e) -> None:
        invoice = self._invoice
        rate = to_decimal(self._global_discount.value)
        if rate < 0 or rate > 100:
            self._fail("El descuento global debe estar entre 0 y 100.")
            return

        invoice.global_discount_rate = rate
        invoice.financed = self._financed_value()
        invoice.credit_days = (int(to_decimal(self._credit_days.value))
                               if self._allows_credit else 0)

        if invoice.financed > invoice.total:
            self._fail("Lo financiado excede el total.")
            return

        slots = self._collect_slots()
        if slots is None:
            return

        if not self._allows_credit and not slots:
            self._fail("Cliente sin crédito: agregue al menos un "
                       "instrumento de pago.")
            return

        assigned = sum((s.amount for s in slots), Decimal(0))
        if slots and assigned != invoice.payable:
            self._fail("El desglose no coincide con lo que se cobra.")
            return

        invoice.payments = slots
        self._on_saved()
        await self._ctx.navigator.back()