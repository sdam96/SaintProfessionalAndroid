"""Client-side invoice state.

Totals are recomputed here only to preview what the server will charge.
The figures that matter are the ones it returns after issuing, since it
resolves prices and tax rates itself.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


PRICE_LISTS = [
    (1, "Precio 1", "price1"),
    (2, "Precio 2", "price2"),
    (3, "Precio 3", "price3"),
]

# ivproser keeps stock in five positional columns, so a warehouse past the
# fifth row of ivdeposi has none to read.
STOCK_COLUMNS = ["stock", "stock2", "stock3", "stock4", "stock5"]


@dataclass
class InvoiceLine:
    product_code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    exempt: bool
    discount_rate: Decimal = Decimal(0)
    warehouse: str = "01"
    # One serial per unit when the product is serialised. Saint deletes the
    # matching ivserial rows as the invoice is written.
    serials: list[str] = field(default_factory=list)
    # The catalogue price of the chosen price list when the line was added.
    # Sent only for an invoice made offline: if the server's price differs
    # by then, it holds the invoice for review instead of issuing it.
    list_price: Decimal = Decimal(0)

    @property
    def gross(self) -> Decimal:
        return money(self.unit_price * self.quantity)

    @property
    def discount(self) -> Decimal:
        if self.discount_rate <= 0:
            return Decimal("0.00")
        return money(self.gross * self.discount_rate / 100)

    @property
    def net(self) -> Decimal:
        """Net of the line discount, before any global discount."""
        return self.gross - self.discount

    def to_json(self, offline: bool = False) -> dict:
        line = {
            "product": self.product_code,
            "quantity": float(self.quantity),
            "warehouse": self.warehouse,
        }
        if self.unit_price > 0:
            line["price"] = float(self.unit_price)
        if self.discount_rate > 0:
            line["discount"] = float(self.discount_rate)
        if self.serials:
            line["serials"] = list(self.serials)
        if offline:
            line["listPrice"] = float(self.list_price)
        return line


@dataclass
class PaymentSlot:
    """One of the five slots of Saint's payment window.

    TIPOCOBRO is not carried here: the server derives it from
    cfinstru.FUNCION for the two "other" slots, and it is fixed for the
    first three.
    """
    key: str            # cash, cheque, card, other1, other2
    label: str
    amount: Decimal = Decimal(0)
    reference: str = ""
    bank_code: str = ""
    instrument: str = ""

    def to_json(self) -> dict:
        slot = {"amount": float(self.amount)}
        if self.reference:
            slot["reference"] = self.reference
        if self.bank_code:
            slot["bankCode"] = self.bank_code
        if self.instrument:
            slot["instrument"] = self.instrument
        return slot


@dataclass
class Invoice:
    customer_code: str = ""
    customer_name: str = ""
    salesperson_code: str = "01"
    salesperson_name: str = ""
    price_list: int = 1
    warehouse: str = "01"
    user: str = "DEMO"
    cash_register: str = "DEMO"
    global_discount_rate: Decimal = Decimal(0)
    financed: Decimal = Decimal(0)
    credit_days: int = 0
    foreign_currency: bool = False
    igtf_rate: Decimal = Decimal(3)
    uses_igtf: bool = False
    reference_rate: Decimal = Decimal(0)   # igtfconfig.VALOR
    reference_label: str = ""
    lines: list[InvoiceLine] = field(default_factory=list)
    payments: list[PaymentSlot] = field(default_factory=list)

    # ------------------------------------------------------------- totals

    @property
    def gross(self) -> Decimal:
        return sum((l.gross for l in self.lines), Decimal("0.00"))

    @property
    def line_discount(self) -> Decimal:
        return sum((l.discount for l in self.lines), Decimal("0.00"))

    @property
    def global_discount_base(self) -> Decimal:
        """What the global discount applies to: gross less line discounts."""
        return self.gross - self.line_discount

    @property
    def global_discount(self) -> Decimal:
        if self.global_discount_rate <= 0:
            return Decimal("0.00")
        return money(self.global_discount_base * self.global_discount_rate / 100)

    @property
    def discount(self) -> Decimal:
        return self.line_discount + self.global_discount

    @property
    def subtotal(self) -> Decimal:
        return self.gross - self.discount

    def _line_shares(self):
        """Each line paired with its slice of the global discount.

        Mirrors how the server prorates it, with the last line absorbing
        the rounding, so the preview matches what comes back.
        """
        base = self.global_discount_base
        total = self.global_discount
        allocated = Decimal("0.00")
        last = len(self.lines) - 1

        for index, line in enumerate(self.lines):
            if total == 0 or base <= 0:
                share = Decimal("0.00")
            elif index == last:
                share = total - allocated
            else:
                share = money(total * line.net / base)
                allocated += share
            yield line, share

    @property
    def taxable_base(self) -> Decimal:
        """Net base of the non-exempt lines: dcheader.BASEIMPONIBLEIVA."""
        return sum((line.net - share
                    for line, share in self._line_shares()
                    if not line.exempt), Decimal("0.00"))

    @property
    def exempt_base(self) -> Decimal:
        """Net base of the exempt lines: dcheader.TOTALEXENTAS."""
        return sum((line.net - share
                    for line, share in self._line_shares()
                    if line.exempt), Decimal("0.00"))

    @property
    def tax(self) -> Decimal:
        total = Decimal("0.00")
        for line, share in self._line_shares():
            if not line.exempt:
                total += money((line.net - share) * line.tax_rate / 100)
        return total

    def tax_breakdown(self) -> list[tuple[Decimal, Decimal, Decimal]]:
        """Groups the non-exempt lines by their tax rate.

        Returns one (rate, base, tax) tuple per distinct rate present,
        ordered from lowest rate to highest. Each base is net of both the
        line and the prorated global discount, so the bases add up to
        taxable_base. The tax of each group is computed the same way as the
        `tax` property (line by line, then rounded), so the groups' taxes
        add up to `tax` without a rounding drift between the two views.
        """
        bases: dict[Decimal, Decimal] = {}
        taxes: dict[Decimal, Decimal] = {}
        for line, share in self._line_shares():
            if line.exempt:
                continue
            base = line.net - share
            bases[line.tax_rate] = bases.get(
                line.tax_rate, Decimal("0.00")) + base
            taxes[line.tax_rate] = taxes.get(
                line.tax_rate, Decimal("0.00")) + money(base * line.tax_rate / 100)

        return [(rate, bases[rate], taxes[rate]) for rate in sorted(bases)]

    @property
    def igtf(self) -> Decimal:
        # IGTF is settled at the till, so it does not apply while any part
        # of the invoice is financed.
        if (self.financed > 0 or not self.foreign_currency
                or not self.uses_igtf):
            return Decimal("0.00")
        return money((self.subtotal + self.tax) * self.igtf_rate / 100)

    @property
    def total(self) -> Decimal:
        return money(self.subtotal + self.tax + self.igtf)

    @property
    def payable(self) -> Decimal:
        """What has to be collected now, once financing is set aside."""
        return money(self.total - self.financed)

    @property
    def paid(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal("0.00"))

    @property
    def outstanding(self) -> Decimal:
        """Still unassigned across the payment slots."""
        return money(self.payable - self.paid)

    @property
    def total_in_reference(self) -> Decimal:
        if self.reference_rate <= 0:
            return Decimal("0.00")
        return money(self.total / self.reference_rate)

    # -------------------------------------------------------------- state

    def reset(self):
        self.lines.clear()
        self.payments.clear()
        self.customer_code = ""
        self.customer_name = ""
        self.global_discount_rate = Decimal(0)
        self.financed = Decimal(0)
        self.credit_days = 0
        self.foreign_currency = False

    def used_serials(self, product_code: str, warehouse: str) -> set[str]:
        """Serials already committed to other lines of this invoice.

        The server only knows what ivserial holds, so picking the same unit
        twice would pass validation and then fail on the second delete.
        """
        used = set()
        for line in self.lines:
            if line.product_code == product_code and line.warehouse == warehouse:
                used.update(line.serials)
        return used

    def to_json(self, offline_since: str = "") -> dict:
        """The request body. `offline_since` (ISO time the invoice was
        confirmed) marks it as made offline: the server then checks that
        prices, stock, credit and the total are still what the phone saw,
        and holds it for review if they are not."""
        payload = {
            "customer": self.customer_code,
            "salesperson": self.salesperson_code,
            "priceList": self.price_list,
            "user": self.user,
            "cashRegister": self.cash_register,
            "lines": [l.to_json(bool(offline_since)) for l in self.lines],
        }
        if self.global_discount_rate > 0:
            payload["globalDiscount"] = float(self.global_discount_rate)
        if self.financed > 0:
            payload["financed"] = float(self.financed)
            if self.credit_days > 0:
                payload["creditDays"] = self.credit_days
        if self.foreign_currency:
            payload["foreignCurrency"] = True
        used = [p for p in self.payments if p.amount > 0]
        if used:
            payload["payment"] = {p.key: p.to_json() for p in used}
        if offline_since:
            payload["offline"] = {
                "capturedAt": offline_since,
                "expectedTotal": float(self.total),
            }
        return payload

    # ---------------------------------------------------------- correcting

    def copy_from(self, other: "Invoice") -> None:
        """Puts another invoice's content into this one, which the screens
        share. Used to correct an invoice the server held for review.
        Payments are not copied: they are entered again against the
        current total."""
        self.reset()
        self.customer_code = other.customer_code
        self.customer_name = other.customer_name
        self.salesperson_code = other.salesperson_code
        self.salesperson_name = other.salesperson_name
        self.price_list = other.price_list
        self.warehouse = other.warehouse
        self.global_discount_rate = other.global_discount_rate
        self.financed = other.financed
        self.credit_days = other.credit_days
        self.foreign_currency = other.foreign_currency
        self.lines = list(other.lines)
