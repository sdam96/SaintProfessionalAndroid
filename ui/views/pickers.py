"""Search-and-pick screens for customers, salespeople and products."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import flet as ft

from api_client import ApiError
from models import PRICE_LISTS

from ..context import AppContext
from ..theme import ACCENT, DANGER, MUTED, OFFLINE, PRIMARY, PRIMARY_DARK
from ..utils import rounded_border, to_decimal
from ..widgets import (badge, loading_indicator, picker_card, status_text,
                       tag_row)

Fetch = Callable[[str], Awaitable[list[dict]]]
CardBuilder = Callable[[list[dict]], list[ft.Control]]
OnPick = Callable[[dict], None]


class SearchPicker:
    """A search field over a list of results loaded from the API."""

    def __init__(self, ctx: AppContext, *, route: str, title: str,
                 label: str, fetch: Fetch, build_cards: CardBuilder,
                 trailing: ft.Control | None = None):
        self._ctx = ctx
        self._route = route
        self._title = title
        self._fetch = fetch
        self._build_cards = build_cards
        self._trailing = trailing

        self._search = ft.TextField(
            label=label, autofocus=True, prefix_icon=ft.Icons.SEARCH,
            border=rounded_border(10),
            # Only needs to stretch when it shares the row with an action.
            expand=True if trailing is not None else None)
        self._search.on_submit = self._load
        self._results = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO,
                                  expand=True)

    async def open(self) -> None:
        top: ft.Control = self._search
        if self._trailing is not None:
            top = ft.Row(spacing=10, controls=[self._search, self._trailing])

        await self._ctx.navigator.push(
            self._route, self._title,
            ft.Column([top, self._results], expand=True, spacing=12))
        self._ctx.page.run_task(self._load)

    async def _load(self, e=None) -> None:
        page = self._ctx.page
        self._results.controls = [loading_indicator()]
        page.update()
        try:
            items = await self._fetch(self._search.value or "")
        except ApiError as exc:
            self._results.controls = [status_text(str(exc), error=True)]
            page.update()
            return

        cards = (self._build_cards(items)
                 or [status_text("Sin resultados")])
        if not self._ctx.online:
            # Offline the list comes from the phone's copy, which may be
            # older than the server's.
            age = self._ctx.store.catalog_age().replace("T", " ")
            cards.insert(0, ft.Text(
                "Sin conexión: datos guardados en el teléfono"
                + (f" (actualizados {age})" if age else "") + ".",
                size=12, color=OFFLINE, weight=ft.FontWeight.W_500))
        self._results.controls = cards
        # _load() also runs through run_task, not as an event handler, so
        # the automatic page update does not always apply here.
        page.update()


# ------------------------------------------------------------------ customers

async def open_customer_picker(ctx: AppContext, on_pick: OnPick,
                               on_create: Callable[[], Awaitable[None]]
                               ) -> None:
    async def pick(item: dict) -> None:
        on_pick(item)
        await ctx.navigator.back()

    def card(item: dict) -> ft.Card:
        initials = (item["name"] or "?").strip()[:1].upper()
        return picker_card(
            leading=badge(ft.Text(initials, size=16, color=ACCENT,
                                  weight=ft.FontWeight.BOLD), ACCENT),
            title=item["name"],
            subtitle=f'{item["code"]}    {item.get("taxId", "")}',
            # An async on_click must be launched as a task; assigning the
            # coroutine alone creates it and drops it without running.
            on_click=lambda e, it=item: asyncio.create_task(pick(it)))

    await SearchPicker(
        ctx, route="/customers", title="Clientes", label="Buscar cliente",
        fetch=ctx.catalog.customers,
        build_cards=lambda items: [card(it) for it in items],
        trailing=ft.IconButton(
            ft.Icons.PERSON_ADD, icon_color=PRIMARY, tooltip="Crear cliente",
            on_click=lambda e: asyncio.create_task(on_create())),
    ).open()


# --------------------------------------------------------------- salespeople

async def open_salesperson_picker(ctx: AppContext, on_pick: OnPick) -> None:
    async def pick(item: dict) -> None:
        on_pick(item)
        await ctx.navigator.back()

    def card(item: dict) -> ft.Card:
        return picker_card(
            leading=badge(ft.Icon(ft.Icons.BADGE, size=20, color=PRIMARY),
                          PRIMARY),
            title=item["name"],
            subtitle=item["code"],
            title_lines=None,
            on_click=lambda e, it=item: asyncio.create_task(pick(it)))

    await SearchPicker(
        ctx, route="/salespeople", title="Vendedores",
        label="Buscar vendedor", fetch=ctx.catalog.salespeople,
        build_cards=lambda items: [card(it) for it in items],
    ).open()


# ------------------------------------------------------------------ products

def _product_card(item: dict, price_key: str, stock_column: str,
                  pick: Callable) -> ft.Card:
    stock = to_decimal(item.get(stock_column, 0))
    stock_colour = (ft.Colors.GREEN_700 if stock > 0
                    else DANGER if stock < 0 else MUTED)
    tags = [(f"exist. {stock:g}", stock_colour)]
    if item.get("usesSerial"):
        tags.append(("seriales", ft.Colors.PURPLE_700))
    if item.get("exempt"):
        tags.append(("exento", ft.Colors.TEAL_700))

    return picker_card(
        leading=badge(ft.Icon(ft.Icons.INVENTORY_2, size=20, color=ACCENT),
                      ACCENT, radius=10),
        title=item["name"],
        subtitle=item["code"],
        extra=tag_row(tags),
        trailing=ft.Text(f"{item.get(price_key, 0):,.2f}", size=15,
                         weight=ft.FontWeight.BOLD, color=PRIMARY_DARK),
        on_click=lambda e, it=item: asyncio.create_task(pick(it)))


async def open_product_picker(ctx: AppContext,
                              on_pick: Callable[[dict], Awaitable[None]]
                              ) -> None:
    async def pick(item: dict) -> None:
        # The picker closes first so the line editor opens in its place.
        await ctx.navigator.back()
        await on_pick(item)

    def cards(items: list[dict]) -> list[ft.Control]:
        _, _, price_key = PRICE_LISTS[ctx.invoice.price_list - 1]
        column = ctx.stock_column()
        return [_product_card(it, price_key, column, pick) for it in items]

    await SearchPicker(
        ctx, route="/products", title="Productos", label="Buscar producto",
        fetch=ctx.catalog.products, build_cards=cards,
    ).open()