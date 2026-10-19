"""The connection indicator shown on every screen.

While the server cannot be reached the app must not look the same as when
it can, so being offline changes three things at once:

- Every app bar turns dark orange.
- A banner sits at the top of every screen and cannot be closed. It says
  that invoices are being kept on the phone and how many are waiting.
- A message appears the moment the connection is lost or comes back.

The banner stays after the connection returns while saved invoices are
still being sent, or while any of them needs the user's attention.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft

from offline_store import HELD, PENDING
from ui.views.sync import SyncService

from ..theme import OFFLINE, OFFLINE_DARK, PRIMARY, REVIEW, SYNCING

_WHITE_SOFT = ft.Colors.with_opacity(0.88, ft.Colors.WHITE)


class _Banner:
    def __init__(self, on_click: Callable):
        self.icon = ft.Icon(ft.Icons.CLOUD_OFF, color=ft.Colors.WHITE,
                            size=26)
        self.title = ft.Text("", size=14, weight=ft.FontWeight.BOLD,
                             color=ft.Colors.WHITE)
        self.detail = ft.Text("", size=12, color=_WHITE_SOFT)
        self.count = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
        self.count_chip = ft.Container(
            padding=ft.Padding(left=10, right=10, top=4, bottom=4),
            border_radius=12, bgcolor=ft.Colors.WHITE, content=self.count)
        self.control = ft.Container(
            visible=False, ink=True, on_click=on_click,
            padding=ft.Padding(left=14, right=12, top=10, bottom=10),
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self.icon,
                    ft.Column(expand=True, spacing=2,
                              controls=[self.title, self.detail]),
                    self.count_chip,
                ]))


class ConnectionIndicator:
    def __init__(self, page: ft.Page, sync: SyncService,
                 open_pending: Callable[[], Awaitable[None]]):
        self._page = page
        self._sync = sync
        self._open_pending = open_pending
        self._banners: list[_Banner] = []
        self._appbars: list[ft.AppBar] = []
        self._was_online: bool | None = None
        sync.subscribe(self.refresh)

    # ------------------------------------------------------- registration

    def banner(self) -> ft.Container:
        """A new banner for one screen. Each screen needs its own."""
        banner = _Banner(on_click=self._on_click)
        self._banners.append(banner)
        # Screens come and go; keep the list from growing without bound.
        del self._banners[:-30]
        self._apply_banner(banner)
        return banner.control

    def attach_appbar(self, appbar: ft.AppBar) -> ft.AppBar:
        self._appbars.append(appbar)
        del self._appbars[:-30]
        appbar.bgcolor = PRIMARY if self._sync.online else OFFLINE_DARK
        return appbar

    def _on_click(self, e) -> None:
        self._page.run_task(self._open_pending)

    # -------------------------------------------------------------- state

    def _state(self):
        counts = self._sync.counts()
        pending, held = counts[PENDING], counts[HELD]
        if not self._sync.online:
            detail = ("Las facturas se guardan en este teléfono y se "
                      "enviarán solas al volver la conexión.")
            if held:
                detail += f" {held} requiere(n) revisión."
            return (True, OFFLINE, ft.Icons.CLOUD_OFF,
                    "SIN CONEXIÓN CON EL SERVIDOR", detail,
                    f"{pending} por enviar" if pending else "", OFFLINE)
        if held:
            return (True, REVIEW, ft.Icons.ERROR_OUTLINE,
                    f"{held} factura(s) guardada(s) requieren revisión",
                    "El servidor no las emitió. Toque para corregirlas o "
                    "descartarlas.", f"{held}", REVIEW)
        if pending or self._sync.syncing:
            return (True, SYNCING, ft.Icons.SYNC,
                    f"Enviando {pending} factura(s) guardada(s)…",
                    "Se emiten con la fecha de hoy. No cierre la "
                    "aplicación.", f"{pending}" if pending else "", SYNCING)
        return (False, PRIMARY, ft.Icons.CLOUD_DONE, "", "", "", PRIMARY)

    def _apply_banner(self, banner: _Banner, state=None) -> None:
        visible, colour, icon, title, detail, count, count_colour = (
            state or self._state())
        banner.control.visible = visible
        banner.control.bgcolor = colour
        banner.icon.icon = icon
        banner.title.value = title
        banner.detail.value = detail
        banner.count.value = count
        banner.count.color = count_colour
        banner.count_chip.visible = bool(count)

    def refresh(self) -> None:
        state = self._state()
        for banner in self._banners:
            self._apply_banner(banner, state)
        for appbar in self._appbars:
            appbar.bgcolor = PRIMARY if self._sync.online else OFFLINE_DARK

        message = None
        if self._was_online is not None and self._was_online != \
                self._sync.online:
            message = ("Conexión restablecida." if self._sync.online else
                       "Sin conexión con el servidor. Las facturas se "
                       "guardarán en el teléfono.")
        elif self._sync.last_message:
            message = self._sync.last_message
        self._sync.last_message = ""
        self._was_online = self._sync.online

        if message:
            self._page.show_dialog(ft.SnackBar(
                ft.Text(message, color=ft.Colors.WHITE),
                bgcolor=SYNCING if self._sync.online else OFFLINE,
                duration=5000))
        try:
            self._page.update()
        except Exception:
            pass
