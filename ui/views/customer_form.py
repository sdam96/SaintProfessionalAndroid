"""Form to register a new customer from the picker."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from api_client import ApiError
from models import PRICE_LISTS

from ..context import AppContext
from ..theme import ACCENT, FIELD_MED, FIELD_NARROW, FIELD_WIDE, MUTED
from ..utils import field_text, rounded_border, to_decimal
from ..widgets import fields, section, set_status, status_text


class CustomerForm:
    def __init__(self, ctx: AppContext,
                 on_created: Callable[[dict], None]):
        self._ctx = ctx
        self._on_created = on_created

        self._code = ft.TextField(label="Código", width=FIELD_MED,
                                  autofocus=True, prefix_icon=ft.Icons.TAG,
                                  border=rounded_border(10))
        self._name = ft.TextField(label="Nombre o razón social",
                                  width=FIELD_WIDE, border=rounded_border(10))
        self._tax_id = ft.TextField(label="RIF", width=FIELD_MED,
                                    border=rounded_border(10))
        self._address = ft.TextField(label="Dirección", width=FIELD_WIDE,
                                     multiline=True, max_lines=2,
                                     border=rounded_border(10))
        self._phone = ft.TextField(label="Teléfono", width=FIELD_MED,
                                   prefix_icon=ft.Icons.PHONE,
                                   border=rounded_border(10))
        self._email = ft.TextField(label="Correo", width=FIELD_MED,
                                   prefix_icon=ft.Icons.MAIL,
                                   border=rounded_border(10))
        self._price_list = ft.Dropdown(
            label="Lista de precio", width=FIELD_MED, value="1",
            border=rounded_border(10),
            options=[ft.DropdownOption(key=str(k), text=t)
                     for k, t, _ in PRICE_LISTS])
        self._credit_days = ft.TextField(
            label="Días de crédito", width=FIELD_NARROW, value="0",
            border=rounded_border(10), keyboard_type=ft.KeyboardType.NUMBER)
        self._credit_limit = ft.TextField(
            label="Límite de crédito", width=FIELD_MED, value="0",
            border=rounded_border(10), keyboard_type=ft.KeyboardType.NUMBER)
        self._message = status_text()
        self._save_button = ft.Button(
            content="Guardar cliente", icon=ft.Icons.SAVE, height=48,
            expand=True, on_click=self._save)

    async def open(self) -> None:
        await self._ctx.navigator.push(
            "/customers/new", "Nuevo cliente", ft.Column(
                expand=True, scroll=ft.ScrollMode.AUTO, spacing=14,
                controls=[
                    section("Identificación", ft.Icons.BADGE,
                            fields(self._code, self._tax_id),
                            fields(self._name),
                            ft.Text("El código suele ser la cédula o el RIF "
                                    "sin guiones.", size=11, color=MUTED)),
                    section("Contacto", ft.Icons.CONTACT_PHONE,
                            fields(self._phone, self._email),
                            fields(self._address),
                            colour=ACCENT),
                    section("Condiciones comerciales", ft.Icons.HANDSHAKE,
                            fields(self._price_list, self._credit_days,
                                   self._credit_limit),
                            colour=ft.Colors.ORANGE_700),
                    self._message,
                    ft.Row([self._save_button]),
                ]))

    def _payload(self) -> dict:
        code = field_text(self._code)
        return {
            "code": code,
            "name": field_text(self._name),
            "taxId": field_text(self._tax_id) or code,
            "address": field_text(self._address),
            "phone": field_text(self._phone),
            "email": field_text(self._email),
            "priceList": int(to_decimal(self._price_list.value, 1)),
            "creditDays": int(to_decimal(self._credit_days.value)),
            "creditLimit": float(to_decimal(self._credit_limit.value)),
            "salesperson": self._ctx.invoice.salesperson_code,
        }

    async def _save(self, e) -> None:
        if not field_text(self._code):
            set_status(self._message, "Indique el código.", error=True)
            return
        if not field_text(self._name):
            set_status(self._message, "Indique el nombre.", error=True)
            return

        self._save_button.disabled = True
        set_status(self._message, "Guardando…")
        self._ctx.page.update()

        try:
            created = await self._ctx.api.create_customer(self._payload())
        except ApiError as exc:
            set_status(self._message, str(exc), error=True)
            return
        finally:
            self._save_button.disabled = False

        self._on_created(created)
        # Two views deep: the form and the picker behind it.
        await self._ctx.navigator.back()
        await self._ctx.navigator.back()