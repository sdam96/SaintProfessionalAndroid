from __future__ import annotations

from decimal import Decimal

import flet as ft

from api_client import ApiError
from models import Invoice

from .context import AppContext
from .navigation import Navigator
from .theme import BACKGROUND
from .utils import to_decimal
from .views.connection import ConnectionForm, splash_view
from .views.invoice import InvoiceScreen

SERVER_URL_KEY = "saintpro.server_url"


def _configure_invoice(invoice: Invoice, info: dict) -> None:
    invoice.uses_igtf = bool(info.get("usaIGTF"))
    if info.get("porcentajeIGTF"):
        invoice.igtf_rate = to_decimal(info["porcentajeIGTF"], Decimal(3))
    invoice.reference_label = info.get("monedaReferencial", "") or ""
    rate = to_decimal(info.get("tasaReferencial", ""), Decimal(0))
    if rate > 0 and str(info.get("tipoOperacion", "")).strip() == "2":
        invoice.reference_rate = rate
    else:
        invoice.reference_rate = Decimal(0)

class SaintApp:
    def __init__(self, page: ft.Page):
        self._page = page
        self._ctx = AppContext(page=page, navigator=Navigator(page))
        self._prefs = ft.SharedPreferences()
        self._invoice_screen = InvoiceScreen(self._ctx)
        self._form = ConnectionForm(on_connect=self._connect)

    def start(self) -> None:
        page = self._page
        page.title = "Saint Professional"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.bgcolor = BACKGROUND
        page.padding = 0
        page.run_task(self._restore_session)

    async def _restore_session(self) -> None:
        saved_url = None
        try:
            saved_url = await self._prefs.get(SERVER_URL_KEY)
        except Exception:
            pass

        if not saved_url:
            await self._show_setup()
            return

        self._form.url = saved_url
        await self._ctx.navigator.set_root(splash_view(saved_url))

        if not await self._do_connect(saved_url):
            await self._show_setup()

    async def _show_setup(self) -> None:
        await self._ctx.navigator.set_root(self._form.view())

    # --------------------------------------------------------- connection

    async def _connect(self, e) -> None:
        url = self._form.url
        if not url:
            self._form.set_status("Indique la dirección del servidor.",
                                  error=True)
            return

        self._form.set_status("Conectando…")
        self._page.update()
        await self._do_connect(url)

    async def _do_connect(self, url: str) -> bool:
        if not url.startswith("http"):
            url = "http://" + url
        api = self._ctx.api
        api.base_url = url

        try:
            info = await api.status()
            rows = await api.warehouses()
        except ApiError as exc:
            self._form.set_status(str(exc), error=True)
            return False

        # Kept so the address does not have to be typed again next launch.
        try:
            await self._prefs.set(SERVER_URL_KEY, url)
        except Exception:
            pass

        invoice = self._ctx.invoice
        _configure_invoice(invoice, info)

        self._ctx.warehouses.clear()
        self._ctx.warehouses.extend(rows)
        if rows:
            invoice.warehouse = rows[0]["code"]

        self._form.set_status("")
        await self._invoice_screen.show(info)
        return True