from __future__ import annotations

from decimal import Decimal

import flet as ft

from api_client import ApiError, ApiNetworkError
from discovery import DiscoveredServer, discover
from models import Invoice
from offline_store import OfflineStore

from .context import AppContext
from .navigation import Navigator
from .views.status import ConnectionIndicator
from .theme import BACKGROUND
from .utils import to_decimal
from .views.connection import ConnectionForm, splash_view
from .views.invoice import InvoiceScreen
from .views.pending import PendingView

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
        navigator = Navigator(page)
        self._ctx = AppContext(page=page, navigator=navigator,
                               store=OfflineStore())
        self._ctx.indicator = ConnectionIndicator(page, self._ctx.sync,
                                                  self._open_pending)
        navigator.indicator = self._ctx.indicator
        self._prefs = ft.SharedPreferences()
        self._invoice_screen = InvoiceScreen(self._ctx,
                                             open_pending=self._open_pending)
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
        saved_url = saved_url or self._ctx.sync.cached_url()

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

        # No server anywhere: work offline with what was last downloaded,
        # if this phone has ever connected.
        if saved_url and await self._enter_offline(saved_url):
            return
        await self._show_setup()

    async def _show_setup(self) -> None:
        await self._ctx.navigator.set_root(self._form.view())

    async def _open_pending(self) -> None:
        await PendingView(self._ctx,
                          on_correct=self._invoice_screen.load_invoice).open()

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
        ctx = self._ctx
        ctx.api.base_url = url

        try:
            info = await ctx.api.status()
            rows = await ctx.api.warehouses()
        except ApiError as exc:
            if isinstance(exc, ApiNetworkError):
                ctx.sync.report_network_error()
            self._form.set_status(str(exc), error=True)
            return False

        # Kept so the address does not have to be typed again next launch.
        try:
            await self._prefs.set(SERVER_URL_KEY, url)
        except Exception:
            pass

        ctx.sync.remember_server(info)
        ctx.store.replace_catalog("warehouses", rows)
        await self._open_session(info, rows)
        ctx.sync.set_online(True)
        # The offline copy is brought up to date, and anything saved while
        # offline is sent, without making the user wait for either.
        self._page.run_task(self._after_connect)
        return True

    async def _after_connect(self) -> None:
        await self._ctx.sync.refresh_catalogs()
        await self._ctx.sync.send_pending()

    async def _enter_offline(self, url: str) -> bool:
        """Opens the invoice screen with the last downloaded data.

        Only possible after at least one successful connection: without
        the catalogues there is nothing to invoice with.
        """
        ctx = self._ctx
        info = ctx.sync.cached_info()
        if not info or not ctx.store.has_catalogs():
            return False
        ctx.api.base_url = url
        ctx.sync.database = str(info.get("baseDatos") or "")
        ctx.sync.set_online(False)
        await self._open_session(info, ctx.store.search("warehouses",
                                                         limit=500))
        return True

    async def _open_session(self, info: dict, warehouses: list[dict]) -> None:
        ctx = self._ctx
        invoice = ctx.invoice
        _configure_invoice(invoice, info)

        ctx.warehouses.clear()
        ctx.warehouses.extend(warehouses)
        if warehouses:
            invoice.warehouse = warehouses[0]["code"]

        self._form.set_status("")
        ctx.sync.start()
        await self._invoice_screen.show(info)
