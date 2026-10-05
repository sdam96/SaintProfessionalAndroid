"""Picks the serial numbers of a serialised product."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from api_client import ApiError

from ..context import AppContext
from ..widgets import loading_indicator, set_status, status_text


class SerialPicker:
    """Picks exactly ``wanted`` serials out of what the warehouse holds.

    The result is written back into ``chosen`` in place.
    """

    def __init__(self, ctx: AppContext, product_code: str,
                 warehouse_code: str, wanted: int, chosen: list[str],
                 on_done: Callable[[], None]):
        self._ctx = ctx
        self._product_code = product_code
        self._warehouse_code = warehouse_code
        self._wanted = wanted
        self._chosen = chosen
        self._on_done = on_done

        self._selected = set(chosen)
        self._available: list[str] = []
        self._counter = ft.Text("", size=15, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE)
        self._results = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO,
                                  expand=True)
        self._message = status_text()

    async def open(self) -> None:
        await self._ctx.navigator.push("/serials", "Seriales", ft.Column(
            expand=True, spacing=12,
            controls=[
                self._banner(),
                self._results,
                self._message,
                ft.Row([ft.Button(content="Confirmar", icon=ft.Icons.CHECK,
                                  height=48, expand=True,
                                  on_click=self._confirm)]),
            ]))
        self._ctx.page.run_task(self._load)

    def _banner(self) -> ft.Container:
        return ft.Container(
            padding=14, border_radius=12,
            bgcolor=ft.Colors.PURPLE_600,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(spacing=10, controls=[
                        ft.Icon(ft.Icons.WAREHOUSE, size=18,
                                color=ft.Colors.WHITE),
                        ft.Text(self._ctx.warehouse_name(self._warehouse_code),
                                size=13, color=ft.Colors.WHITE),
                    ]),
                    self._counter,
                ]))

    def _toggle(self, serial: str, value: bool) -> None:
        if value:
            if len(self._selected) >= self._wanted:
                set_status(self._message,
                           f"Ya seleccionó {self._wanted} seriales.",
                           error=True)
                self._render()
                return
            self._selected.add(serial)
        else:
            self._selected.discard(serial)
        self._message.value = ""
        self._render()

    def _serial_card(self, serial: str) -> ft.Card:
        picked = serial in self._selected
        return ft.Card(
            elevation=2 if picked else 0,
            content=ft.Container(
                padding=ft.Padding(left=8, right=14, top=4, bottom=4),
                border_radius=10,
                bgcolor=(ft.Colors.with_opacity(0.10, ft.Colors.PURPLE_600)
                         if picked else None),
                content=ft.Row(spacing=6, controls=[
                    ft.Checkbox(
                        value=picked,
                        active_color=ft.Colors.PURPLE_600,
                        on_change=lambda e, s=serial: self._toggle(
                            s, e.control.value)),
                    ft.Text(serial, size=14,
                            weight=ft.FontWeight.W_500 if picked else None),
                ]),
            ))

    def _render(self) -> None:
        self._results.controls = (
            [self._serial_card(s) for s in self._available]
            or [status_text("No hay seriales disponibles en este depósito.")])
        self._counter.value = f"{len(self._selected)} de {self._wanted}"
        self._ctx.page.update()

    async def _confirm(self, e) -> None:
        if len(self._selected) != self._wanted:
            set_status(self._message,
                       f"Seleccione exactamente {self._wanted} seriales.",
                       error=True)
            self._ctx.page.update()
            return
        self._chosen.clear()
        self._chosen.extend(sorted(self._selected))
        await self._ctx.navigator.back()
        self._on_done()

    async def _load(self, e=None) -> None:
        page = self._ctx.page
        self._results.controls = [loading_indicator()]
        page.update()
        try:
            items = await self._ctx.api.serials(self._product_code,
                                                self._warehouse_code)
        except ApiError as exc:
            self._results.controls = [status_text(str(exc), error=True)]
            page.update()
            return

        # Serials already committed to other lines of this invoice are
        # still in ivserial, so they have to be hidden here.
        taken = self._ctx.invoice.used_serials(self._product_code,
                                               self._warehouse_code)
        self._available = [s for s in items if s not in taken]
        self._render()