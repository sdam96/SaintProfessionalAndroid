"""The connection indicator shown on every screen.

While the server cannot be reached the app must not look the same as when
it can, so being offline changes three things at once:

- Every app bar turns dark orange.
- A status strip at the top of every screen turns orange and says how many
  invoices are waiting on the phone.
- A message appears the moment the connection is lost or comes back.

The strip has the same height in every state and is never hidden, so a
change of state never moves the screen: only its colour, icon and words
change, with a short fade. A screen is redrawn only when the state really
changed; the periodic connection check that finds everything as it was
touches nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft

from offline_store import HELD, PENDING
from .sync import SyncService

from ..theme import (MUTED, OFFLINE, OFFLINE_DARK, PRIMARY, REVIEW, SURFACE,
                     SYNCING)

# One line of text plus its padding, in every state.
STRIP_HEIGHT = 40
# Colour and icon changes fade instead of switching at once.
_FADE = ft.Animation(250, ft.AnimationCurve.EASE_IN_OUT)


class _Strip:
    def __init__(self, on_click: Callable):
        self.icon = ft.Icon(ft.Icons.CLOUD_DONE, size=20)
        self.title = ft.Text("", size=13, weight=ft.FontWeight.BOLD,
                             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.count = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
        self.count_chip = ft.Container(
            padding=ft.Padding(left=10, right=10, top=2, bottom=2),
            border_radius=12, bgcolor=ft.Colors.WHITE, content=self.count,
            opacity=0, animate_opacity=_FADE)
        self.control = ft.Container(
            height=STRIP_HEIGHT, ink=True, on_click=on_click,
            animate=_FADE,
            padding=ft.Padding(left=14, right=12, top=0, bottom=0),
            content=ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self.icon,
                    ft.Container(expand=True, content=self.title),
                    self.count_chip,
                ]))


class ConnectionIndicator:
    def __init__(self, page: ft.Page, sync: SyncService,
                 open_pending: Callable[[], Awaitable[None]]):
        self._page = page
        self._sync = sync
        self._open_pending = open_pending
        self._strips: list[_Strip] = []
        self._appbars: list[ft.AppBar] = []
        self._was_online: bool | None = None
        # What every strip shows now; refresh() compares against it.
        self._shown: tuple | None = None
        sync.subscribe(self.refresh)

    # ------------------------------------------------------- registration

    def banner(self) -> ft.Container:
        """A new status strip for one screen. Each screen needs its own."""
        strip = _Strip(on_click=self._on_click)
        self._strips.append(strip)
        # Screens come and go; keep the list from growing without bound.
        del self._strips[:-30]
        self._apply(strip, self._state())
        return strip.control

    def attach_appbar(self, appbar: ft.AppBar) -> ft.AppBar:
        self._appbars.append(appbar)
        del self._appbars[:-30]
        appbar.bgcolor = PRIMARY if self._sync.online else OFFLINE_DARK
        return appbar

    def _on_click(self, e) -> None:
        self._page.run_task(self._open_pending)

    # -------------------------------------------------------------- state

    def _state(self) -> tuple:
        """(background, foreground, icon, text, count, count colour)."""
        counts = self._sync.counts()
        pending, held = counts[PENDING], counts[HELD]
        if not self._sync.online:
            return (OFFLINE, ft.Colors.WHITE, ft.Icons.CLOUD_OFF,
                    "SIN CONEXIÓN · se guardan en el teléfono",
                    f"{pending} por enviar" if pending else "", OFFLINE)
        if held:
            return (REVIEW, ft.Colors.WHITE, ft.Icons.ERROR_OUTLINE,
                    f"{held} factura(s) requieren revisión · toque aquí",
                    f"{held}", REVIEW)
        # Only when there really is something to send.
        if pending:
            return (SYNCING, ft.Colors.WHITE, ft.Icons.SYNC,
                    f"Enviando {pending} factura(s) guardada(s)…",
                    f"{pending}", SYNCING)
        return (SURFACE, MUTED, ft.Icons.CLOUD_DONE,
                "Conectado al servidor", "", PRIMARY)

    @staticmethod
    def _apply(strip: _Strip, state: tuple) -> None:
        background, foreground, icon, text, count, count_colour = state
        strip.control.bgcolor = background
        strip.icon.icon = icon
        strip.icon.color = foreground
        strip.title.value = text
        strip.title.color = foreground
        strip.count.value = count
        strip.count.color = count_colour
        # Faded out rather than hidden, so the strip keeps its layout.
        strip.count_chip.opacity = 1 if count else 0

    def refresh(self) -> None:
        state = self._state()
        online = self._sync.online
        changed = state != self._shown
        if changed:
            self._shown = state
            for strip in self._strips:
                self._apply(strip, state)
            colour = PRIMARY if online else OFFLINE_DARK
            for appbar in self._appbars:
                appbar.bgcolor = colour

        message = None
        if self._was_online is not None and self._was_online != online:
            message = ("Conexión restablecida." if online else
                       "Sin conexión con el servidor. Las facturas se "
                       "guardarán en el teléfono.")
        elif self._sync.last_message:
            message = self._sync.last_message
        self._sync.last_message = ""
        self._was_online = online

        if message:
            self._page.show_dialog(ft.SnackBar(
                ft.Text(message, color=ft.Colors.WHITE),
                bgcolor=SYNCING if online else OFFLINE,
                duration=5000))
        # Nothing changed and nothing to say: leave the screen alone.
        if not changed and not message:
            return
        try:
            self._page.update()
        except Exception:
            pass
