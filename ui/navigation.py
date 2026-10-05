"""Navigation over the page view stack.

1.0 keeps page.views as the editable stack. Both moving forward and going
back are done by adjusting page.views and then routing to whatever view is
on top with the awaitable page.push_route; there is no pop_route.
"""

from __future__ import annotations

import flet as ft

from .theme import BACKGROUND, PRIMARY


class Navigator:
    def __init__(self, page: ft.Page):
        self._page = page

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

        view = ft.View(
            route=route,
            bgcolor=BACKGROUND,
            appbar=ft.AppBar(
                title=ft.Text(title, weight=ft.FontWeight.W_500),
                bgcolor=PRIMARY, color=ft.Colors.WHITE, elevation=2,
                leading=leading,
            ),
            padding=16,
            controls=[body],
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