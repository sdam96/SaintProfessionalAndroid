from __future__ import annotations

from decimal import Decimal

import flet as ft

from api_client import ApiError
from discovery import DiscoveredServer, discover
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
        self._form = ConnectionForm(on_connect=self._connect,
                                    on_search=self._search,
                                    on_pick_server=self._pick_server)

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

        # The saved address goes first: it is the fastest path and the only
        # one that works for a server outside this network.
        if saved_url:
            self._form.url = saved_url
            await self._ctx.navigator.set_root(splash_view(saved_url))
            if await self._do_connect(saved_url):
                return

        # No saved address, or it stopped answering (a new DHCP lease can
        # move the server to another IP): look for it on this network.
        await self._ctx.navigator.set_root(
            splash_view("Buscando servidor en la red…"))
        if await self._discover_and_connect(automatic=True):
            return
        await self._show_setup()

    async def _show_setup(self) -> None:
        await self._ctx.navigator.set_root(self._form.view())

    # --------------------------------------------------------- discovery

    async def _discover_and_connect(self, automatic: bool) -> bool:
        """Connects straight away when exactly one server answers.

        With several, they are listed for the user to choose; with none,
        a manual search says so, while the automatic one at start-up keeps
        whatever error the saved address produced.
        """
        servers = await discover()
        if len(servers) == 1:
            self._form.clear_servers()
            return await self._connect_to(servers[0])

        self._form.show_servers(servers)
        if servers:
            self._form.set_status("Se encontraron varios servidores. "
                                  "Seleccione uno.")
        elif not automatic:
            self._form.set_status(
                "No se encontró ningún servidor en esta red. Verifique que "
                "el teléfono esté en el mismo Wi-Fi que el servidor, o "
                "escriba la dirección.", error=True)
        return False

    async def _search(self, e) -> None:
        self._form.set_searching(True)
        self._form.clear_servers()
        self._form.set_status("Buscando servidor en la red…")
        self._page.update()
        try:
            await self._discover_and_connect(automatic=False)
        finally:
            self._form.set_searching(False)
            self._page.update()

    async def _pick_server(self, server: DiscoveredServer) -> None:
        self._form.set_status("Conectando…")
        self._page.update()
        await self._connect_to(server)
        self._page.update()

    async def _connect_to(self, server: DiscoveredServer) -> bool:
        self._form.url = server.url
        return await self._do_connect(server.url)

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