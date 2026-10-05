"""Small building blocks reused across screens."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import flet as ft

from .theme import DANGER, MUTED, PRIMARY, PRIMARY_DARK

# (text, colour) pairs rendered as small coloured chips.
Tag = tuple[str, str]


def status_text(message: str = "", error: bool = False) -> ft.Text:
    """An inline status line; red when it reports an error."""
    return ft.Text(message, size=13, color=DANGER if error else MUTED)


def set_status(control: ft.Text, message: str, error: bool = False) -> None:
    control.value = message
    control.color = DANGER if error else MUTED


def amount_text(value: str, size: int = 14, bold: bool = False,
                colour: str | None = None) -> ft.Text:
    return ft.Text(value, size=size, color=colour,
                   weight=ft.FontWeight.BOLD if bold else None)


def badge(content: ft.Control, colour: str, size: int = 40,
          radius: int | None = None, opacity: float = 0.14) -> ft.Container:
    """A tinted square or circle holding an icon, initial or number."""
    return ft.Container(
        width=size, height=size,
        border_radius=size // 2 if radius is None else radius,
        bgcolor=ft.Colors.with_opacity(opacity, colour),
        alignment=ft.Alignment.CENTER,
        content=content)


def loading_indicator() -> ft.Container:
    return ft.Container(padding=30, alignment=ft.Alignment.CENTER,
                        content=ft.ProgressRing())


def section(title: str, icon, *controls: ft.Control,
            colour: str = PRIMARY) -> ft.Card:
    """A titled block of form fields.

    Grouping the fields under a heading is what keeps a long form from
    reading as one undifferentiated column.
    """
    return ft.Card(
        elevation=1,
        content=ft.Container(
            padding=16,
            border_radius=12,
            content=ft.Column(spacing=14, controls=[
                ft.Row(spacing=10, controls=[
                    badge(ft.Icon(icon, size=18, color=colour), colour,
                          size=32, opacity=0.12),
                    ft.Text(title, size=15, weight=ft.FontWeight.BOLD,
                            color=PRIMARY_DARK),
                ]),
                ft.Divider(height=1),
                *controls,
            ]),
        ),
    )


def fields(*controls: ft.Control) -> ft.Row:
    """Fields flow into as many columns as the screen allows.

    Only for fixed-width controls: a child with expand=True inside a
    wrapping row has no bounded width and the row fails to lay out,
    which renders as an empty grey box.
    """
    return ft.Row(wrap=True, spacing=12, run_spacing=12,
                  controls=list(controls))


def tag_row(tags: Iterable[Tag], run_spacing: int = 10) -> ft.Row:
    return ft.Row(wrap=True, spacing=6, run_spacing=run_spacing, controls=[
        ft.Container(
            padding=ft.Padding(left=8, right=8, top=2, bottom=2),
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.10, colour),
            content=ft.Text(text, size=10, color=colour,
                            weight=ft.FontWeight.W_500))
        for text, colour in tags
    ])


def picker_card(*, leading: ft.Control, title: str, subtitle: str,
                on_click: Callable, trailing: ft.Control | None = None,
                extra: ft.Control | None = None,
                title_lines: int | None = 1) -> ft.Card:
    """A tappable result row used by every search picker."""
    title_text = ft.Text(title, size=15, weight=ft.FontWeight.W_500)
    if title_lines:
        title_text.max_lines = title_lines
        title_text.overflow = ft.TextOverflow.ELLIPSIS

    body: list[ft.Control] = [title_text,
                              ft.Text(subtitle, size=12, color=MUTED)]
    if extra is not None:
        body.append(extra)

    return ft.Card(elevation=1, content=ft.Container(
        padding=12, border_radius=12, ink=True, on_click=on_click,
        content=ft.Row(spacing=12, controls=[
            leading,
            ft.Column(expand=True, spacing=4 if extra is not None else 2,
                      controls=body),
            trailing or ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED,
                                size=20),
        ]),
    ))