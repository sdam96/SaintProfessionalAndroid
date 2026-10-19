from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import flet as ft

from api_client import ApiError, ApiNetworkError
from models import PRICE_LISTS, Invoice, InvoiceLine
from offline_store import new_invoice_id
from ui.views.sync import now_iso

from ..context import AppContext
from ..theme import (ACCENT, BACKGROUND, DANGER, FIELD_MED, MUTED, OFFLINE,
                     PRIMARY, PRIMARY_DARK, bottom_allowance)
from ..utils import rounded_border, to_decimal
from ..widgets import badge, fields, set_status, status_text, tag_row
from .customer_form import CustomerForm
from .line_editor import LineEditor
from .pickers import (open_customer_picker, open_product_picker,
                      open_salesperson_picker)
from .result import open_result_view
from .totalise import TotaliseView
from .totals_panel import TotalsPanel

PAYMENT_BUTTON_LABEL = "Detalles de pago"
ISSUE_BUTTON_LABEL = "Totalizar"
# Offline the button does not issue anything: it keeps the invoice on the
# phone, and its label says so.
OFFLINE_ISSUE_LABEL = "Guardar sin conexión"


def _allows_credit(customer: dict) -> bool:
    """Whether a customer may be invoiced on credit: cfprocli.PERCREDITO.

    Exposed by the API as allowsCredit, 1 when allowed and 0 when not.
    Accepts it as a number, a string or a boolean, since TFlag may reach
    the JSON in any of those forms. A missing value counts as no credit,
    which is also Saint's default for the column.
    """
    value = customer.get("allowsCredit")
    if isinstance(value, bool):
        return value
    return str(value).strip() in ("1", "1.0")


def _line_card(index: int, line: InvoiceLine,
               warehouse_name: Callable[[str], str],
               on_remove: Callable[[int], None],
               compact: bool = False) -> ft.Card:
    """One invoice line. `compact` trims sizes for a phone-width list."""
    detail = f"{line.quantity:g} × {line.unit_price:,.2f}"
    if line.discount_rate > 0:
        detail += f"   −{line.discount_rate:g}%"

    tags = []
    if line.exempt:
        tags.append(("exento", ft.Colors.TEAL_700))
    else:
        tags.append((f"IVA {line.tax_rate:g}%", PRIMARY))
    tags.append((warehouse_name(line.warehouse), MUTED))
    if line.serials:
        tags.append((f"{len(line.serials)} S/N", ft.Colors.PURPLE_700))

    return ft.Card(elevation=1, content=ft.Container(
        padding=10 if compact else 12, border_radius=12,
        content=ft.Row(
            spacing=10 if compact else 12,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                badge(ft.Text(str(index + 1), size=12 if compact else 14,
                              weight=ft.FontWeight.BOLD, color=PRIMARY),
                      PRIMARY, size=28 if compact else 36, opacity=0.12),
                ft.Column(expand=True, spacing=4, controls=[
                    ft.Text(line.description, size=14 if compact else 15,
                            weight=ft.FontWeight.W_500, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{line.product_code}    {detail}", size=12,
                            color=MUTED),
                    tag_row(tags, run_spacing=6),
                ]),
                ft.Column(horizontal_alignment=ft.CrossAxisAlignment.END,
                          spacing=4 if not compact else 0, controls=[
                              ft.Text(f"{line.net:,.2f}",
                                      size=15 if compact else 17,
                                      weight=ft.FontWeight.BOLD,
                                      color=PRIMARY_DARK),
                              ft.IconButton(
                                  ft.Icons.DELETE_OUTLINE,
                                  icon_color=DANGER, icon_size=20,
                                  visual_density=(ft.VisualDensity.COMPACT
                                                  if compact else None),
                                  on_click=lambda e: on_remove(index)),
                          ]),
            ]),
    ))


def _empty_lines(compact: bool = False) -> ft.Container:
    return ft.Container(
        padding=24 if compact else 48, alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                badge(ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, size=34,
                              color=PRIMARY),
                      PRIMARY, size=72, opacity=0.08),
                ft.Text("Sin renglones", size=15, color=MUTED,
                        weight=ft.FontWeight.W_500),
                ft.Text("Agregue productos para comenzar", size=12,
                        color=ft.Colors.BLUE_GREY_400),
            ]),
    )


class InvoiceScreen:
    def __init__(self, ctx: AppContext,
                 open_pending: Callable[[], Awaitable[None]]):
        self._ctx = ctx
        self._open_pending = open_pending
        # The connection banner at the top of this screen.
        self._banner: ft.Control | None = None
        self._invoice = ctx.invoice
        self._totals = TotalsPanel()

        # The root view, kept so the layout can be swapped when the screen
        # crosses the tablet breakpoint (rotation, split screen, resizing).
        self._view: ft.View | None = None
        self._tablet = False
        # No customer selected yet: the credit rule only applies once one
        # is, and issuing without a customer is refused anyway.
        self._allows_credit = True

        self._customer_button = ft.OutlinedButton(
            content="Seleccionar cliente", icon=ft.Icons.PERSON, expand=True,
            on_click=self._open_customer_picker)
        self._salesperson_button = ft.OutlinedButton(
            content="Vendedor 01", icon=ft.Icons.BADGE, expand=True,
            on_click=self._open_salesperson_picker)

        self._price_list = ft.Dropdown(
            label="Lista de precio", width=FIELD_MED, value="1",
            border=rounded_border(10),
            options=[ft.DropdownOption(key=str(k), text=t)
                     for k, t, _ in PRICE_LISTS])
        self._warehouse = ft.Dropdown(
            label="Depósito", width=FIELD_MED, value="01",
            border=rounded_border(10))
        self._foreign_switch = ft.Switch(label="Pago en divisa", value=False,
                                         active_color=ACCENT)
        for control in (self._price_list, self._warehouse,
                        self._foreign_switch):
            control.on_change = self._on_input_change

        # Never scrolls on its own: it always sits inside the scrolling
        # body, and a nested scroll would get unbounded height and render
        # empty.
        self._lines = ft.Column(spacing=10)
        # Heading over the list on a phone, where the list scrolls together
        # with the header and the count is the quickest check.
        self._lines_title = ft.Text("Renglones", size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=PRIMARY_DARK)

        self._totalise_button = ft.FilledTonalButton(
            content=PAYMENT_BUTTON_LABEL, icon=ft.Icons.PAYMENTS,
            expand=True, height=44, on_click=self._open_payment_details)
        self._message = status_text()
        self._issue_button = ft.Button(
            content=ISSUE_BUTTON_LABEL, icon=ft.Icons.CHECK_CIRCLE, height=52,
            expand=True, on_click=self._issue)
        # Shown under the issue button while it is disabled, so the user
        # knows what is missing instead of facing a dead button.
        self._issue_hint = ft.Text(
            "El cliente no tiene crédito: registre el pago en "
            f"«{PAYMENT_BUTTON_LABEL}» para poder totalizar.",
            size=12, color=ft.Colors.ORANGE_800, visible=False)

        # The issue button follows the connection state.
        ctx.sync.subscribe(self._on_connection_change)

    # ------------------------------------------------------------- layout

    async def show(self, info: dict) -> None:
        self._warehouse.options = [
            ft.DropdownOption(key=w["code"], text=w["name"])
            for w in self._ctx.warehouses]
        if self._ctx.warehouses:
            self._warehouse.value = self._invoice.warehouse

        appbar = ft.AppBar(
            title=ft.Text("Nueva factura", weight=ft.FontWeight.W_500),
            bgcolor=PRIMARY, color=ft.Colors.WHITE, elevation=2,
            actions=[
                ft.IconButton(
                    ft.Icons.OUTBOX, icon_color=ft.Colors.WHITE,
                    tooltip="Facturas guardadas sin conexión",
                    on_click=lambda e: self._ctx.page.run_task(
                        self._open_pending)),
                ft.IconButton(
                    ft.Icons.INFO_OUTLINE, icon_color=ft.Colors.WHITE,
                    tooltip=f'{info.get("baseDatos", "")} · '
                            f'est.{info.get("estacion", "")}'),
            ],
        )
        self._ctx.indicator.attach_appbar(appbar)
        self._banner = self._ctx.indicator.banner()
        view = ft.View(
            route="/invoice",
            bgcolor=BACKGROUND,
            appbar=appbar,
            padding=0,
            spacing=0,
            controls=[self._banner, self._body()],
        )
        self._view = view
        # On Android the first width can arrive late or change on rotation;
        # the layout is rebuilt whenever it crosses the breakpoint.
        self._ctx.page.on_resize = self._on_resize
        await self._ctx.navigator.set_root(view, navigate=True)
        self.refresh_lines()

    def _header(self, compact: bool = False) -> ft.Container:
        if compact:
            # Both dropdowns share one row instead of wrapping to two.
            selectors = ft.Row(spacing=10,
                               controls=[self._price_list, self._warehouse])
        else:
            selectors = fields(self._price_list, self._warehouse)
        return ft.Container(
            padding=12 if compact else 16,
            bgcolor=ft.Colors.WHITE,
            content=ft.Column(spacing=10 if compact else 12, controls=[
                ft.Row([self._customer_button]),
                ft.Row([self._salesperson_button]),
                selectors,
                ft.Row([ft.FilledTonalButton(
                    content="Agregar producto",
                    icon=ft.Icons.ADD_SHOPPING_CART,
                    expand=True, height=46,
                    on_click=self._open_product_picker)]),
            ]),
        )

    def _body(self) -> ft.Control:
        """The whole screen, kept clear of the system bars.

        Nothing in it has a fixed height. Whatever the screen size, font
        scale or navigation-bar style (buttons or gestures), every control,
        the issue button included, can be reached by scrolling.
        """
        self._tablet = self._ctx.is_tablet()
        body = self._tablet_body() if self._tablet else self._phone_body()
        return ft.SafeArea(expand=True, content=body)

    def _tablet_body(self) -> ft.Control:
        for dropdown in (self._price_list, self._warehouse):
            dropdown.width = FIELD_MED
            dropdown.expand = None
        self._totalise_button.height = 44
        self._issue_button.height = 52

        lines_pane = ft.Container(
            padding=ft.Padding(left=16, right=16, top=12, bottom=16),
            content=self._lines)
        panel = self._totals.build(
            foreign_switch=self._foreign_switch,
            totalise_button=self._totalise_button,
            message=self._message,
            issue_button=self._issue_button,
            hint=self._issue_hint)

        # Each pane scrolls on its own. A wide but short screen (a phone in
        # landscape crosses the breakpoint too) still reaches every line.
        return ft.Row(expand=True, spacing=0, controls=[
            ft.Container(expand=3, content=ft.Column(
                [self._header(), lines_pane, bottom_allowance()],
                expand=True, spacing=0,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
            ft.VerticalDivider(width=1),
            ft.Container(expand=2, padding=12, bgcolor=BACKGROUND,
                         content=ft.Column([panel, bottom_allowance()],
                                           scroll=ft.ScrollMode.AUTO)),
        ])

    def _phone_body(self) -> ft.Control:
        """Header, lines and totals in one scrolling column.

        No section is pinned to the screen, so none can push another out
        of view: the actions are at the end of the list, one scroll away.
        """
        for dropdown in (self._price_list, self._warehouse):
            dropdown.width = None
            dropdown.expand = 1
        self._totalise_button.height = 48
        self._issue_button.height = 52

        lines_pane = ft.Container(
            padding=ft.Padding(left=12, right=12, top=12, bottom=4),
            content=ft.Column(spacing=8, controls=[
                self._lines_title, self._lines]))
        panel = ft.Container(
            padding=ft.Padding(left=12, right=12, top=8, bottom=16),
            content=self._totals.build(
                foreign_switch=self._foreign_switch,
                totalise_button=self._totalise_button,
                message=self._message,
                issue_button=self._issue_button,
                hint=self._issue_hint,
                compact=True))

        return ft.Column(
            expand=True, spacing=0, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[self._header(compact=True), lines_pane, panel,
                      bottom_allowance()])

    def _on_resize(self, e=None) -> None:
        if self._view is None or self._ctx.is_tablet() == self._tablet:
            return
        self._view.controls = [self._banner, self._body()]
        self.refresh_lines()
        self._ctx.page.update()

    # ------------------------------------------------------------ refresh

    def refresh_totals(self) -> None:
        invoice = self._invoice
        invoice.price_list = int(to_decimal(self._price_list.value, 1))
        invoice.warehouse = self._warehouse.value or invoice.warehouse
        invoice.foreign_currency = self._foreign_switch.value
        self._totals.refresh(invoice)
        self._refresh_issue_state()

    def _issue_blocked(self) -> bool:
        """A customer without credit cannot leave anything unpaid."""
        return not self._allows_credit and not self._invoice.payments

    def _refresh_issue_state(self) -> None:
        blocked = self._issue_blocked()
        self._issue_button.disabled = blocked
        self._issue_hint.visible = blocked
        self._apply_issue_label()

    def _apply_issue_label(self) -> None:
        if self._ctx.online:
            self._issue_button.content = ISSUE_BUTTON_LABEL
            self._issue_button.icon = ft.Icons.CHECK_CIRCLE
            self._issue_button.bgcolor = None
            self._issue_button.color = None
        else:
            self._issue_button.content = OFFLINE_ISSUE_LABEL
            self._issue_button.icon = ft.Icons.SAVE
            self._issue_button.bgcolor = OFFLINE
            self._issue_button.color = ft.Colors.WHITE

    def _on_connection_change(self) -> None:
        # Not while a request is running: _issue restores the label itself.
        if self._issue_button.content != "Procesando…":
            self._apply_issue_label()

    def refresh_lines(self) -> None:
        compact = not self._tablet
        count = len(self._invoice.lines)
        self._lines_title.value = (f"Renglones ({count})" if count
                                   else "Renglones")
        if self._invoice.lines:
            self._lines.controls = [
                _line_card(i, line, self._ctx.warehouse_name,
                           self._remove_line, compact=compact)
                for i, line in enumerate(self._invoice.lines)]
        else:
            self._lines.controls = [_empty_lines(compact=compact)]
        self.refresh_totals()

    def _on_input_change(self, e) -> None:
        self.refresh_totals()

    def _invalidate_payments(self) -> None:
        self._invoice.payments.clear()
        self._totalise_button.content = PAYMENT_BUTTON_LABEL

    # ----------------------------------------------------------- customer

    async def _open_customer_picker(self, e=None) -> None:
        await open_customer_picker(self._ctx, on_pick=self._select_customer,
                                   on_create=self._open_customer_form)

    async def _open_customer_form(self) -> None:
        # A customer created offline would not exist on the server when
        # the invoice arrives, so creation needs the connection.
        if not self._ctx.online:
            self._ctx.page.show_dialog(ft.SnackBar(
                ft.Text("Crear clientes requiere conexión con el servidor.",
                        color=ft.Colors.WHITE), bgcolor=OFFLINE))
            return
        await CustomerForm(self._ctx,
                           on_created=self._customer_created).open()

    def _set_customer(self, code: str, name: str) -> None:
        self._invoice.customer_code = code
        self._invoice.customer_name = name
        self._customer_button.content = f"{code} — {name}"

    def _select_customer(self, item: dict) -> None:
        self._set_customer(item["code"], item["name"])
        if item.get("priceList"):
            self._price_list.value = str(item["priceList"])
        if (item.get("salesperson") or "").strip():
            self._invoice.salesperson_code = item["salesperson"]
            self._salesperson_button.content = (
                f'Vendedor {item["salesperson"]}')
        if item.get("creditDays"):
            self._invoice.credit_days = int(item["creditDays"])
        self._apply_credit_rule(_allows_credit(item))
        self.refresh_totals()

    def _customer_created(self, created: dict) -> None:
        self._set_customer(created["code"], created["name"])
        if created.get("priceList"):
            self._price_list.value = str(created["priceList"])
        self._apply_credit_rule(_allows_credit(created))
        self.refresh_totals()

    def _apply_credit_rule(self, allows_credit: bool) -> None:
        """Drops any financing left from a previous customer with credit.

        The saved payment details were balanced against what was financed,
        so once that is gone they no longer add up and are cleared too.
        """
        self._allows_credit = allows_credit
        if allows_credit:
            return
        self._invoice.credit_days = 0
        if self._invoice.financed > 0:
            self._invoice.financed = Decimal(0)
            self._invalidate_payments()

    # -------------------------------------------------------- salesperson

    async def _open_salesperson_picker(self, e=None) -> None:
        await open_salesperson_picker(self._ctx,
                                      on_pick=self._select_salesperson)

    def _select_salesperson(self, item: dict) -> None:
        self._invoice.salesperson_code = item["code"]
        self._invoice.salesperson_name = item["name"]
        self._salesperson_button.content = f'{item["code"]} — {item["name"]}'

    # -------------------------------------------------------------- lines

    async def _open_product_picker(self, e=None) -> None:
        await open_product_picker(self._ctx, on_pick=self._open_line_editor)

    async def _open_line_editor(self, product: dict) -> None:
        await LineEditor(self._ctx, product, on_add=self._add_line).open()

    def _add_line(self, line: InvoiceLine) -> None:
        self._invoice.lines.append(line)
        self._invalidate_payments()
        self.refresh_lines()

    def _remove_line(self, index: int) -> None:
        self._invoice.lines.pop(index)
        self._invalidate_payments()
        self.refresh_lines()

    # ---------------------------------------------------- payment details

    async def _open_payment_details(self, e=None) -> None:
        if not self._invoice.lines:
            set_status(self._message, "Agregue al menos un renglón.",
                       error=True)
            self._ctx.page.update()
            return
        await TotaliseView(self._ctx, on_saved=self._payment_details_saved,
                           allows_credit=self._allows_credit).open()

    def _payment_details_saved(self) -> None:
        count = len(self._invoice.payments)
        self._totalise_button.content = (
            f"{PAYMENT_BUTTON_LABEL} ({count})" if count
            else PAYMENT_BUTTON_LABEL)
        self.refresh_totals()

    # -------------------------------------------------------------- issue

    async def _issue(self, e) -> None:
        if not self._invoice.customer_code:
            set_status(self._message, "Seleccione un cliente.", error=True)
            return
        if not self._invoice.lines:
            set_status(self._message, "Agregue al menos un renglón.",
                       error=True)
            return
        if self._issue_blocked():
            set_status(self._message, "El cliente no tiene crédito: "
                       "registre el pago antes de totalizar.", error=True)
            return

        # The UUID that makes this invoice unique for the server. It is
        # created once, here, and reused for every resend.
        invoice_id = new_invoice_id()

        if not self._ctx.online:
            if any(line.serials for line in self._invoice.lines):
                set_status(self._message,
                           "Las facturas con seriales requieren conexión: "
                           "otro equipo podría vender el mismo serial.",
                           error=True)
                return
            await self._save_offline(invoice_id)
            return

        page = self._ctx.page
        self._issue_button.disabled = True
        self._issue_button.content = "Procesando…"
        self._message.value = ""
        page.update()

        result = None
        lost = False
        try:
            result = await self._ctx.api.create_invoice(
                self._invoice.to_json(), invoice_id)
        except ApiNetworkError:
            # No answer: the server may or may not have issued it. Saved
            # with the same UUID, resending later returns that invoice if
            # it was issued, and issues it if it was not; never twice.
            self._ctx.sync.report_network_error()
            lost = True
        except ApiError as exc:
            set_status(self._message, str(exc), error=True)
        except Exception as exc:
            set_status(self._message, f"Error inesperado: {exc}", error=True)
        finally:
            self._issue_button.content = ISSUE_BUTTON_LABEL
            self._refresh_issue_state()
            page.update()

        if lost:
            await self._save_offline(invoice_id)
        elif result is not None:
            await open_result_view(self._ctx, result,
                                   on_new_invoice=self._new_invoice)

    async def _save_offline(self, invoice_id: str) -> None:
        invoice = self._invoice
        captured = now_iso()
        total = f"{invoice.total:.2f}"
        self._ctx.sync.save_offline(invoice_id, invoice, captured)
        await open_result_view(
            self._ctx,
            {"offlineId": invoice_id, "total": total, "date": captured},
            on_new_invoice=self._new_invoice, saved_offline=True)

    # ------------------------------------------------------ held invoices

    def load_invoice(self, held: Invoice) -> None:
        """Puts a held invoice back on screen to be corrected and issued
        again, as a new invoice with a new UUID."""
        invoice = self._invoice
        invoice.copy_from(held)
        self._set_customer(invoice.customer_code, invoice.customer_name)
        self._salesperson_button.content = (
            f"{invoice.salesperson_code} — {invoice.salesperson_name}"
            if invoice.salesperson_name
            else f"Vendedor {invoice.salesperson_code}")
        self._price_list.value = str(invoice.price_list)
        self._warehouse.value = invoice.warehouse
        self._foreign_switch.value = invoice.foreign_currency
        self._totalise_button.content = PAYMENT_BUTTON_LABEL
        self._message.value = ""

        # Whether the customer may buy on credit, from the local copy.
        self._allows_credit = True
        for item in self._ctx.store.search("customers",
                                           invoice.customer_code, 20):
            if item.get("code") == invoice.customer_code:
                self._allows_credit = _allows_credit(item)
                break
        self._apply_credit_rule(self._allows_credit)
        self.refresh_lines()

    def _new_invoice(self) -> None:
        self._invoice.reset()
        self._customer_button.content = "Seleccionar cliente"
        self._totalise_button.content = PAYMENT_BUTTON_LABEL
        self._allows_credit = True
        self._foreign_switch.value = False
        self._message.value = ""
        self.refresh_lines()