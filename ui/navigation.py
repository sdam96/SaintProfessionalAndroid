from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from .theme import BACKGROUND, PRIMARY, bottom_allowance

if TYPE_CHECKING:
    from .views.status import ConnectionIndicator


class Navigator:
    def __init__(self, page: ft.Page):
        self._page = page
        self.indicator: ConnectionIndicator | None = None

    async def _route_to_top(self) -> None:
        if self._page.views:
            await self._page.push_route(self._page.views[-1].route)

    async def push(self, route: str, title: str, body: ft.Control,
                   show_back: bool = True) -> None:
        leading = None
        if show_back:
            leading = ft.IconButton(ft.Icons.ARROW_BACK,
                                    icon_color=ft.Colors.WHITE,
                                    on_click=self.back)

        if isinstance(body, ft.Column) and body.scroll:
            body.controls.append(bottom_allowance())

        appbar = ft.AppBar(
            title=ft.Text(title, weight=ft.FontWeight.W_500),
            bgcolor=PRIMARY, color=ft.Colors.WHITE, elevation=2,
            leading=leading,
            automatically_imply_leading=show_back,
        )
 
        content: list[ft.Control] = [ft.SafeArea(
            expand=True,
            content=ft.Container(expand=True, padding=16, content=body))]
        if self.indicator is not None:
            self.indicator.attach_appbar(appbar)
            content.insert(0, self.indicator.banner())

        view = ft.View(
            route=route,
            bgcolor=BACKGROUND,
            appbar=appbar,
            padding=0,
            spacing=0,
            controls=content,
            can_pop=show_back,
        )
        self._page.views.append(view)
        await self._page.push_route(route)

    async def back(self, e=None) -> None:
        if len(self._page.views) > 1:
            self._page.views.pop()
            await self._route_to_top()

    async def set_root(self, view: ft.View, navigate: bool = False) -> None:
        self._page.views.clear()
        self._page.views.append(view)
        if navigate:
            await self._page.push_route(view.route)
        else:
            self._page.update()