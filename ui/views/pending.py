"""Invoices saved on the phone: waiting, held by the server, or sent."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from models import Invoice
from offline_store import HELD, PENDING, SYNCED, OutboxEntry

from ..context import AppContext
from ..theme import (DANGER, MUTED, OFFLINE, PRIMARY_DARK, REVIEW, SYNCING)
from ..widgets import badge, section, status_text

ROUTE = "/pending"


def _when(text: str) -> str:
    return text.replace("T", " ")


def _money(value) -> str:
    return f"{value:,.2f}"


class PendingView:
    def __init__(self, ctx: AppContext,
                 on_correct: Callable[[Invoice], None]):
        self._ctx = ctx
        self._on_correct = on_correct
        self._summary = ft.Text("", size=13, color=MUTED)
        self._send_button = ft.Button(
            content="Enviar ahora", icon=ft.Icons.SEND, height=44,
            on_click=self._send_now)
        self._list = ft.Column(spacing=14)
        self._listening = False

    async def open(self) -> None:
        self._render()
        await self._ctx.navigator.push(ROUTE, "Facturas guardadas", ft.Column(
            expand=True, scroll=ft.ScrollMode.AUTO, spacing=14,
            controls=[
                ft.Card(elevation=1, content=ft.Container(
                    padding=16, border_radius=12,
                    content=ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(expand=True, content=self._summary),
                            self._send_button,
                        ]))),
                self._list,
            ]))
        if not self._listening:
            self._listening = True
            self._ctx.sync.subscribe(self._on_change)

    # ------------------------------------------------------------- render

    def _on_change(self) -> None:
        # Only while this screen is open.
        if any(v.route == ROUTE for v in self._ctx.page.views):
            self._render()

    def _render(self) -> None:
        sync = self._ctx.sync
        entries = self._ctx.store.entries()
        held = [e for e in entries if e.status == HELD]
        pending = [e for e in entries if e.status == PENDING]
        synced = [e for e in entries if e.status == SYNCED]
        synced.reverse()  # most recent first

        if not sync.online:
            self._summary.value = (f"Sin conexión. {len(pending)} por "
                                   "enviar; se enviarán solas al volver la "
                                   "conexión.")
            self._summary.color = OFFLINE
        elif sync.syncing:
            self._summary.value = f"Enviando {len(pending)} factura(s)…"
            self._summary.color = SYNCING
        elif pending:
            self._summary.value = f"{len(pending)} factura(s) por enviar."
            self._summary.color = SYNCING
        else:
            self._summary.value = "No hay facturas por enviar."
            self._summary.color = MUTED
        self._send_button.disabled = (not sync.online or sync.syncing
                                      or not pending)

        sections: list[ft.Control] = []
        if held:
            sections.append(section(
                f"Requieren revisión ({len(held)})", ft.Icons.ERROR_OUTLINE,
                ft.Text("El servidor no las emitió. Corríjalas (se cargan en "
                        "una factura nueva) o descártelas.", size=12,
                        color=MUTED),
                *[self._held_card(e) for e in held], colour=REVIEW))
        if pending:
            sections.append(section(
                f"Por enviar ({len(pending)})", ft.Icons.SCHEDULE_SEND,
                *[self._pending_card(e) for e in pending], colour=OFFLINE))
        if synced:
            sections.append(section(
                f"Enviadas ({len(synced)})", ft.Icons.CHECK_CIRCLE,
                *[self._synced_card(e) for e in synced],
                colour=ft.Colors.GREEN_700))
        if not sections:
            sections.append(status_text(
                "No hay facturas guardadas en este teléfono."))
        self._list.controls = sections

    def _card(self, entry: OutboxEntry, colour: str, icon,
              lines: list[ft.Control],
              actions: list[ft.Control] | None = None) -> ft.Container:
        body: list[ft.Control] = [
            ft.Row(spacing=10, controls=[
                badge(ft.Icon(icon, size=18, color=colour), colour, size=32),
                ft.Column(expand=True, spacing=2, controls=[
                    ft.Text(entry.invoice.customer_name or entry.invoice.customer_code, size=14,
                            weight=ft.FontWeight.W_500, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{entry.invoice.customer_code}  ·  ref. {entry.short_id}"
                            f"  ·  {_when(entry.captured_at)}", size=11,
                            color=MUTED),
                ]),
                ft.Text(_money(entry.invoice.total), size=15,
                        weight=ft.FontWeight.BOLD, color=PRIMARY_DARK),
            ]),
            *lines,
        ]
        if actions:
            body.append(ft.Row(alignment=ft.MainAxisAlignment.END,
                               controls=actions))
        return ft.Container(
            padding=12, border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.06, colour),
            content=ft.Column(spacing=8, controls=body))

    def _held_card(self, entry: OutboxEntry) -> ft.Container:
        return self._card(
            entry, REVIEW, ft.Icons.ERROR_OUTLINE,
            [ft.Text(entry.last_error or "Rechazada por el servidor.",
                     size=13, color=REVIEW, weight=ft.FontWeight.W_500)],
            [ft.TextButton(content="Descartar", icon=ft.Icons.DELETE_OUTLINE,
                           style=ft.ButtonStyle(color=DANGER),
                           on_click=lambda e, it=entry: self._confirm_discard(
                               it)),
             ft.FilledTonalButton(content="Corregir", icon=ft.Icons.EDIT_NOTE,
                                  on_click=lambda e, it=entry:
                                  self._confirm_correct(it))])

    def _pending_card(self, entry: OutboxEntry) -> ft.Container:
        lines: list[ft.Control] = []
        if entry.attempts:
            lines.append(ft.Text(
                f"Intentos: {entry.attempts}. Último error: "
                f"{entry.last_error}", size=12, color=MUTED))
        return self._card(entry, OFFLINE, ft.Icons.HOURGLASS_TOP, lines)

    def _synced_card(self, entry: OutboxEntry) -> ft.Container:
        return self._card(
            entry, ft.Colors.GREEN_700, ft.Icons.CHECK_CIRCLE,
            [ft.Text(f"Factura N° {entry.invoice_number}  ·  emitida "
                     f"{_when(entry.issued_at)}", size=12,
                     color=ft.Colors.GREEN_800)])

    # ------------------------------------------------------------ actions

    async def _send_now(self, e) -> None:
        self._ctx.sync.wake()

    def _confirm(self, title: str, text: str, label: str,
                 action: Callable[[], None]) -> None:
        page = self._ctx.page

        def close(e=None):
            page.pop_dialog()

        def accept(e=None):
            page.pop_dialog()
            action()

        page.show_dialog(ft.AlertDialog(
            modal=True, title=title, content=ft.Text(text),
            actions=[ft.TextButton(content="Cancelar", on_click=close),
                     ft.FilledButton(content=label, on_click=accept)]))

    def _confirm_discard(self, entry: OutboxEntry) -> None:
        def discard():
            self._ctx.store.remove(entry.id)
            self._render()
            self._ctx.indicator.refresh()

        self._confirm(
            "Descartar factura",
            f"La factura de {entry.invoice.customer_name or entry.invoice.customer_code} por "
            f"{_money(entry.invoice.total)} no se emitirá. Esta acción no se puede "
            "deshacer.", "Descartar", discard)

    def _confirm_correct(self, entry: OutboxEntry) -> None:
        def correct():
            # Removed first: the corrected invoice is a new one, with its
            # own UUID, so this one must never be sent too.
            self._ctx.store.remove(entry.id)
            self._on_correct(entry.invoice)
            self._ctx.indicator.refresh()
            self._ctx.page.run_task(self._ctx.navigator.back)

        self._confirm(
            "Corregir factura",
            "Se cargará en la pantalla de factura con los datos que tenía "
            "(sin los pagos), reemplazando lo que haya en ella, y se quitará "
            "de esta lista. Revise precios y pagos antes de totalizar.",
            "Corregir", correct)
