from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import flet as ft

from discovery import DiscoveredServer

from ..theme import PRIMARY, PRIMARY_DARK, bottom_allowance
from ..utils import field_text, rounded_border
from ..widgets import set_status, status_text


def _gradient(*colors: str) -> ft.LinearGradient:
    return ft.LinearGradient(begin=ft.Alignment.TOP_CENTER,
                             end=ft.Alignment.BOTTOM_CENTER,
                             colors=list(colors))


class ConnectionForm:

    def __init__(self, on_connect: Callable[[object], Awaitable[None]],
                 on_search: Callable[[object], Awaitable[None]],
                 on_pick_server: Callable[[DiscoveredServer],
                                          Awaitable[None]]):
        self._server_field = ft.TextField(
            label="Dirección del servidor",
            hint_text="http://192.168.1.100:9000",
            prefix_icon=ft.Icons.DNS,
            keyboard_type=ft.KeyboardType.URL,
            border=rounded_border(10),
        )
        self._message = status_text()
        self._on_connect = on_connect
        self._on_pick_server = on_pick_server

        self._search_button = ft.OutlinedButton(
            content="Buscar en esta red", icon=ft.Icons.WIFI_FIND,
            height=44, expand=True, on_click=on_search)
        # Filled in when a search finds more than one server.
        self._servers = ft.Column(spacing=6, visible=False)

    @property
    def url(self) -> str:
        return field_text(self._server_field)

    @url.setter
    def url(self, value: str) -> None:
        self._server_field.value = value

    def set_status(self, message: str, error: bool = False) -> None:
        set_status(self._message, message, error)

    def set_searching(self, searching: bool) -> None:
        self._search_button.disabled = searching
        self._search_button.content = ("Buscando…" if searching
                                       else "Buscar en esta red")

    def show_servers(self, servers: list[DiscoveredServer]) -> None:
        """Lists the servers found so the user picks one."""
        tiles: list[ft.Control] = [
            ft.Text("Servidores encontrados", size=13,
                    weight=ft.FontWeight.BOLD, color=PRIMARY_DARK)]
        for server in servers:
            detail = f"{server.host}:{server.port}"
            if server.version:
                detail += f"  ·  v{server.version}"
            tiles.append(ft.Container(
                border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.06, PRIMARY),
                content=ft.ListTile(
                    leading=ft.Icon(ft.Icons.DNS, color=PRIMARY),
                    title=ft.Text(server.name, weight=ft.FontWeight.W_500),
                    subtitle=ft.Text(detail, size=12),
                    trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT),
                    # An async handler behind a lambda must be launched
                    # as a task, or the coroutine is dropped unrun.
                    on_click=lambda e, s=server: asyncio.create_task(
                        self._on_pick_server(s)))))
        self._servers.controls = tiles
        self._servers.visible = bool(servers)

    def clear_servers(self) -> None:
        self._servers.controls = []
        self._servers.visible = False

    def view(self) -> ft.View:
        card = ft.Card(
            elevation=6,
            content=ft.Container(
                padding=22, border_radius=14,
                content=ft.Column(spacing=16, controls=[
                    self._server_field,
                    ft.Row([ft.Button(
                        content="Conectar", icon=ft.Icons.LINK,
                        height=48, expand=True,
                        on_click=self._on_connect)]),
                    ft.Row([self._search_button]),
                    self._servers,
                    self._message,
                ]),
            ),
        )
        return ft.View(
            route="/",
            padding=0,
            controls=[
                ft.Container(
                    expand=True,
                    gradient=_gradient(PRIMARY_DARK, PRIMARY,
                                       ft.Colors.INDIGO_400),
                    content=ft.SafeArea(expand=True, content=ft.Column(
                        # Scrolls so a list of servers, a large system font
                        # or the keyboard never hide the buttons.
                        expand=True, scroll=ft.ScrollMode.AUTO,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[ft.Container(
                            padding=ft.Padding(left=24, right=24, top=48,
                                               bottom=24),
                            content=ft.Column(
                                width=420,
                                horizontal_alignment=(
                                    ft.CrossAxisAlignment.CENTER),
                                spacing=0,
                                controls=[
                                    ft.Container(
                                        width=88, height=88,
                                        border_radius=44,
                                        bgcolor=ft.Colors.with_opacity(
                                            0.18, ft.Colors.WHITE),
                                        alignment=ft.Alignment.CENTER,
                                        content=ft.Icon(
                                            ft.Icons.RECEIPT_LONG, size=44,
                                            color=ft.Colors.WHITE)),
                                    ft.Container(height=18),
                                    ft.Text("Saint Professional", size=26,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.WHITE),
                                    ft.Text("Facturación móvil", size=14,
                                            color=ft.Colors.with_opacity(
                                                0.75, ft.Colors.WHITE)),
                                    ft.Container(height=28),
                                    card,
                                ]),
                        ), bottom_allowance()],
                    )),
                )
            ],
        )


def splash_view(message: str) -> ft.View:
    return ft.View(
        route="/splash",
        padding=0,
        controls=[
            ft.Container(
                expand=True,
                gradient=_gradient(PRIMARY_DARK, PRIMARY),
                alignment=ft.Alignment.CENTER,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=18,
                    controls=[
                        ft.Icon(ft.Icons.RECEIPT_LONG, size=52,
                                color=ft.Colors.WHITE),
                        ft.Text("Saint Professional", size=20,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE),
                        ft.ProgressRing(color=ft.Colors.WHITE, width=28,
                                        height=28),
                        ft.Text(message, size=13,
                                color=ft.Colors.with_opacity(
                                    0.8, ft.Colors.WHITE)),
                    ]),
            )
        ],
    )