from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft

from ..theme import PRIMARY, PRIMARY_DARK
from ..utils import field_text, rounded_border
from ..widgets import set_status, status_text


def _gradient(*colors: str) -> ft.LinearGradient:
    return ft.LinearGradient(begin=ft.Alignment.TOP_CENTER,
                             end=ft.Alignment.BOTTOM_CENTER,
                             colors=list(colors))


class ConnectionForm:

    def __init__(self, on_connect: Callable[[object], Awaitable[None]]):
        self._server_field = ft.TextField(
            label="Dirección del servidor",
            hint_text="http://192.168.1.100:9000",
            prefix_icon=ft.Icons.DNS,
            keyboard_type=ft.KeyboardType.URL,
            border=rounded_border(10),
            autofocus=True,
        )
        self._message = status_text()
        self._on_connect = on_connect

    @property
    def url(self) -> str:
        return field_text(self._server_field)

    @url.setter
    def url(self, value: str) -> None:
        self._server_field.value = value

    def set_status(self, message: str, error: bool = False) -> None:
        set_status(self._message, message, error)

    def view(self) -> ft.View:
        return ft.View(
            route="/",
            padding=0,
            controls=[
                ft.Container(
                    expand=True,
                    gradient=_gradient(PRIMARY_DARK, PRIMARY,
                                       ft.Colors.INDIGO_400),
                    alignment=ft.Alignment.CENTER,
                    padding=24,
                    content=ft.Column(
                        width=420,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=0,
                        controls=[
                            ft.Container(
                                width=88, height=88, border_radius=44,
                                bgcolor=ft.Colors.with_opacity(
                                    0.18, ft.Colors.WHITE),
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.RECEIPT_LONG, size=44,
                                                color=ft.Colors.WHITE)),
                            ft.Container(height=18),
                            ft.Text("Saint Professional", size=26,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                            ft.Text("Facturación móvil", size=14,
                                    color=ft.Colors.with_opacity(
                                        0.75, ft.Colors.WHITE)),
                            ft.Container(height=28),
                            ft.Card(
                                elevation=6,
                                content=ft.Container(
                                    padding=22, border_radius=14,
                                    content=ft.Column(spacing=16, controls=[
                                        self._server_field,
                                        ft.Button(
                                            content="Conectar",
                                            icon=ft.Icons.LINK,
                                            width=360, height=48,
                                            on_click=self._on_connect),
                                        self._message,
                                    ]),
                                ),
                            ),
                        ],
                    ),
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