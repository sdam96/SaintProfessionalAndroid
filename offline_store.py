"""Local storage for invoicing without a connection to the server.

One SQLite file on the phone, one table per entity:

- server_connection: the server this phone last connected to (one row).
- customers, products, salespeople, warehouses, payment_instruments,
  banks: the last copy of each catalogue, so an invoice can be prepared
  with no connection at all.
- pending_invoices, with pending_invoice_lines, pending_invoice_serials
  and pending_invoice_payments: invoices waiting to reach the server.

Columns carry the same names as what they store: a catalogue's columns are
the keys of the API's JSON, and the pending-invoice columns are the fields
of Invoice, InvoiceLine and PaymentSlot. A row goes in and comes out as is,
with no translation in between.

Each pending invoice is identified by a UUID created when the user confirms
it and never changed. It is sent as the Idempotency-Key header and the
server keeps the result of every key it has processed, so an invoice is
issued once however many times it is sent.

Amounts, quantities and rates of a pending invoice are TEXT holding the
exact decimal: SQLite has no decimal type and REAL would round them.

The schema version is kept in PRAGMA user_version.
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from models import Invoice, InvoiceLine, PaymentSlot

DB_FILE = "saintpro_offline.db"
SCHEMA_VERSION = 2

# pending_invoices.status
PENDING = "pending"   # waiting to be sent
HELD = "held"         # the server refused it; the user corrects or discards
SYNCED = "synced"     # issued; kept for a while as a record

# Issued invoices stay listed this long, then are removed.
SYNCED_RETENTION = timedelta(days=30)

# Catalogue name used by the screens -> table.
CATALOGS = {
    "customers": "customers",
    "products": "products",
    "salespeople": "salespeople",
    "warehouses": "warehouses",
    "instruments": "payment_instruments",
    "banks": "banks",
}

_SCHEMA = """
CREATE TABLE server_connection (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    url               TEXT    NOT NULL,
    baseDatos         TEXT    NOT NULL,
    estacion          TEXT,
    usaIGTF           INTEGER,
    porcentajeIGTF    REAL,
    monedaReferencial TEXT,
    tasaReferencial   TEXT,
    tipoOperacion     TEXT,
    connectedAt       TEXT    NOT NULL
);

CREATE TABLE customers (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    taxId        TEXT,
    address      TEXT,
    phone        TEXT,
    priceList    INTEGER,
    creditDays   INTEGER,
    creditLimit  REAL,
    salesperson  TEXT,
    allowsCredit INTEGER,
    downloadedAt TEXT NOT NULL
);

CREATE TABLE products (
    code          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    unit          TEXT,
    price1        REAL,
    price2        REAL,
    price3        REAL,
    stock         REAL,
    stock2        REAL,
    stock3        REAL,
    stock4        REAL,
    stock5        REAL,
    taxRate       REAL,
    exempt        INTEGER,
    inventoryType INTEGER,
    usesSerial    INTEGER,
    downloadedAt  TEXT NOT NULL
);

CREATE TABLE salespeople (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT,
    downloadedAt TEXT NOT NULL
);

CREATE TABLE warehouses (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    manager      TEXT,
    downloadedAt TEXT NOT NULL
);

CREATE TABLE payment_instruments (
    code            TEXT PRIMARY KEY,
    name            TEXT,
    function        INTEGER,
    class           TEXT,
    withholdingRate REAL,
    taxRate         REAL,
    deferredDays    INTEGER,
    downloadedAt    TEXT NOT NULL
);

CREATE TABLE banks (
    code         TEXT PRIMARY KEY,
    name         TEXT,
    downloadedAt TEXT NOT NULL
);

CREATE TABLE pending_invoices (
    id                   TEXT    PRIMARY KEY CHECK (length(id) = 36),
    database_name        TEXT    NOT NULL,
    status               TEXT    NOT NULL
                         CHECK (status IN ('pending', 'held', 'synced')),
    captured_at          TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL,
    attempts             INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT    NOT NULL DEFAULT '',
    invoice_number       TEXT,
    invoice_control      TEXT,
    issued_at            TEXT,
    -- Invoice fields
    customer_code        TEXT    NOT NULL,
    customer_name        TEXT    NOT NULL,
    salesperson_code     TEXT    NOT NULL,
    salesperson_name     TEXT    NOT NULL,
    price_list           INTEGER NOT NULL CHECK (price_list BETWEEN 1 AND 3),
    warehouse            TEXT    NOT NULL,
    user                 TEXT    NOT NULL,
    cash_register        TEXT    NOT NULL,
    global_discount_rate TEXT    NOT NULL,
    financed             TEXT    NOT NULL,
    credit_days          INTEGER NOT NULL,
    foreign_currency     INTEGER NOT NULL CHECK (foreign_currency IN (0, 1)),
    igtf_rate            TEXT    NOT NULL,
    uses_igtf            INTEGER NOT NULL CHECK (uses_igtf IN (0, 1)),
    reference_rate       TEXT    NOT NULL,
    reference_label      TEXT    NOT NULL,
    CHECK (status <> 'synced' OR invoice_number IS NOT NULL)
);
CREATE INDEX pending_invoices_status
    ON pending_invoices (status, captured_at);

CREATE TABLE pending_invoice_lines (
    invoice_id    TEXT    NOT NULL
                  REFERENCES pending_invoices (id) ON DELETE CASCADE,
    line_no       INTEGER NOT NULL CHECK (line_no >= 1),
    -- InvoiceLine fields
    product_code  TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    quantity      TEXT    NOT NULL,
    unit_price    TEXT    NOT NULL,
    tax_rate      TEXT    NOT NULL,
    exempt        INTEGER NOT NULL CHECK (exempt IN (0, 1)),
    discount_rate TEXT    NOT NULL,
    warehouse     TEXT    NOT NULL,
    list_price    TEXT    NOT NULL,
    PRIMARY KEY (invoice_id, line_no)
);

CREATE TABLE pending_invoice_serials (
    invoice_id TEXT    NOT NULL,
    line_no    INTEGER NOT NULL,
    serial     TEXT    NOT NULL,
    PRIMARY KEY (invoice_id, line_no, serial),
    FOREIGN KEY (invoice_id, line_no)
        REFERENCES pending_invoice_lines (invoice_id, line_no)
        ON DELETE CASCADE
);

CREATE TABLE pending_invoice_payments (
    invoice_id TEXT NOT NULL
               REFERENCES pending_invoices (id) ON DELETE CASCADE,
    -- PaymentSlot fields
    key        TEXT NOT NULL
               CHECK (key IN ('cash', 'cheque', 'card', 'other1', 'other2')),
    label      TEXT NOT NULL,
    amount     TEXT NOT NULL,
    reference  TEXT NOT NULL,
    bank_code  TEXT NOT NULL,
    instrument TEXT NOT NULL,
    PRIMARY KEY (invoice_id, key)
);
"""

# Every table of earlier layouts of this file, dropped on upgrade. None of
# them was ever released.
_OLD_TABLES = (
    "catalog", "catalog_meta", "kv", "outbox",
    "pending_invoice_payments", "pending_invoice_serials",
    "pending_invoice_lines", "pending_invoices", "server_connection",
    "customers", "products", "salespeople", "warehouses",
    "payment_instruments", "banks",
)


def default_path() -> Path:
    """The app's private data folder, as Flet reports it.

    FLET_APP_STORAGE_DATA is set by Flet in a packaged app; the fallback
    only applies when running from a desktop during development.
    """
    folder = os.getenv("FLET_APP_STORAGE_DATA")
    base = Path(folder) if folder else Path.home() / ".saintpro"
    base.mkdir(parents=True, exist_ok=True)
    return base / DB_FILE


def new_invoice_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# A dataclass to a row and back, field by field under the same names. The
# field types say what needs converting: Decimal goes as TEXT, bool as 0/1.

def _to_row(obj, skip: tuple[str, ...] = ()) -> dict:
    row = {}
    for f in dataclasses.fields(obj):
        if f.name in skip:
            continue
        value = getattr(obj, f.name)
        if f.type is Decimal:
            value = str(value)
        elif f.type is bool:
            value = int(value)
        row[f.name] = value
    return row


def _from_row(cls, row: sqlite3.Row, **extra):
    values = {}
    for f in dataclasses.fields(cls):
        if f.name not in row.keys():
            continue
        value = row[f.name]
        if f.type is Decimal:
            value = Decimal(value)
        elif f.type is bool:
            value = bool(value)
        values[f.name] = value
    return cls(**values, **extra)


@dataclass
class OutboxEntry:
    id: str
    database_name: str
    status: str
    captured_at: str
    updated_at: str
    attempts: int
    last_error: str
    invoice_number: str | None
    invoice_control: str | None
    issued_at: str | None
    invoice: Invoice

    @property
    def short_id(self) -> str:
        """Enough of the UUID to tell entries apart on screen."""
        return self.id[:8].upper()

    @property
    def payload(self) -> dict:
        """The request body, rebuilt from the stored rows. Marked as made
        offline, so the server checks it is still valid before issuing."""
        return self.invoice.to_json(offline_since=self.captured_at)


class OfflineStore:
    def __init__(self, path: Path | str | None = None):
        self._db = sqlite3.connect(str(path or default_path()))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        # The file must survive the app being killed mid-write.
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = FULL")
        self._columns: dict[str, set[str]] = {}
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        with self._db:
            for table in _OLD_TABLES:
                self._db.execute(f"DROP TABLE IF EXISTS {table}")
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ------------------------------------------------------------- helpers

    def _table_columns(self, table: str) -> set[str]:
        if table not in self._columns:
            self._columns[table] = {
                r["name"] for r in self._db.execute(
                    f"PRAGMA table_info({table})")}
        return self._columns[table]

    def _insert(self, table: str, row: dict, replace: bool = False) -> None:
        """Writes the keys of `row` that are columns of `table`. Anything
        else the API sends is ignored, so a new field does not break it."""
        columns = self._table_columns(table)
        values = {k: v for k, v in row.items() if k in columns}
        names = ", ".join(f'"{k}"' for k in values)
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        self._db.execute(
            f"{verb} INTO {table} ({names}) "
            f"VALUES ({', '.join('?' * len(values))})",
            tuple(values.values()))

    # -------------------------------------------------------------- server

    def save_server(self, url: str, info: dict) -> None:
        with self._db:
            self._insert("server_connection",
                         {**info, "id": 1, "url": url, "connectedAt": _now()},
                         replace=True)

    def load_server(self) -> tuple[str, dict] | None:
        """The last server's address and its /status, or None if this
        phone never connected."""
        row = self._db.execute(
            "SELECT * FROM server_connection WHERE id = 1").fetchone()
        if row is None:
            return None
        info = dict(row)
        url = info.pop("url")
        del info["id"], info["connectedAt"]
        return url, info

    # ---------------------------------------------------------- catalogues

    def replace_catalog(self, kind: str, rows: list[dict]) -> None:
        """A full download: what the server no longer has is dropped."""
        table = CATALOGS[kind]
        stamp = _now()
        with self._db:
            self._db.execute(f"DELETE FROM {table}")
            for row in rows:
                if row.get("code"):
                    self._insert(table, {**row, "downloadedAt": stamp},
                                 replace=True)

    def upsert_catalog(self, kind: str, rows: list[dict]) -> None:
        """A partial result (a search): refreshes those rows only."""
        table = CATALOGS[kind]
        stamp = _now()
        with self._db:
            for row in rows:
                if row.get("code"):
                    self._insert(table, {**row, "downloadedAt": stamp},
                                 replace=True)

    def search(self, kind: str, text: str = "", limit: int = 100
               ) -> list[dict]:
        """Rows whose name or code contains `text`, ignoring case, with the
        same keys the API returns."""
        pattern = f"%{text.strip()}%"
        rows = self._db.execute(
            f"SELECT * FROM {CATALOGS[kind]} "
            "WHERE name LIKE ? OR code LIKE ? ORDER BY name LIMIT ?",
            (pattern, pattern, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            del item["downloadedAt"]
            result.append(item)
        return result

    def has_catalogs(self) -> bool:
        """Whether there is enough to invoice offline."""
        return all(
            self._db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            for table in ("customers", "products", "warehouses"))

    def catalog_age(self) -> str:
        """When the oldest catalogue copy was downloaded, or ''."""
        stamps = [self._db.execute(
            f"SELECT MAX(downloadedAt) FROM {table}").fetchone()[0]
            for table in CATALOGS.values()]
        stamps = [s for s in stamps if s]
        return min(stamps) if stamps else ""

    # -------------------------------------------------------------- outbox

    def add(self, invoice_id: str, *, database: str, invoice: Invoice,
            captured_at: str) -> None:
        now = _now()
        with self._db:
            self._insert("pending_invoices", {
                **_to_row(invoice, skip=("lines", "payments")),
                "id": invoice_id, "database_name": database,
                "status": PENDING, "captured_at": captured_at,
                "updated_at": now})
            for line_no, line in enumerate(invoice.lines, start=1):
                self._insert("pending_invoice_lines", {
                    **_to_row(line, skip=("serials",)),
                    "invoice_id": invoice_id, "line_no": line_no})
                for serial in line.serials:
                    self._insert("pending_invoice_serials", {
                        "invoice_id": invoice_id, "line_no": line_no,
                        "serial": serial})
            for payment in invoice.payments:
                self._insert("pending_invoice_payments", {
                    **_to_row(payment), "invoice_id": invoice_id})

    def _invoice(self, row: sqlite3.Row) -> Invoice:
        invoice_id = row["id"]
        serials: dict[int, list[str]] = {}
        for s in self._db.execute(
                "SELECT line_no, serial FROM pending_invoice_serials "
                "WHERE invoice_id = ? ORDER BY line_no, serial",
                (invoice_id,)):
            serials.setdefault(s["line_no"], []).append(s["serial"])
        lines = [
            _from_row(InvoiceLine, line,
                      serials=serials.get(line["line_no"], []))
            for line in self._db.execute(
                "SELECT * FROM pending_invoice_lines WHERE invoice_id = ? "
                "ORDER BY line_no", (invoice_id,))]
        payments = [
            _from_row(PaymentSlot, p)
            for p in self._db.execute(
                "SELECT * FROM pending_invoice_payments WHERE invoice_id = ? "
                "ORDER BY rowid", (invoice_id,))]
        return _from_row(Invoice, row, lines=lines, payments=payments)

    def _entry(self, row: sqlite3.Row) -> OutboxEntry:
        return _from_row(OutboxEntry, row, invoice=self._invoice(row))

    def entries(self, statuses: tuple[str, ...] = (PENDING, HELD, SYNCED)
                ) -> list[OutboxEntry]:
        """Oldest first, which is also the order they are sent in."""
        marks = ", ".join("?" * len(statuses))
        rows = self._db.execute(
            f"SELECT * FROM pending_invoices WHERE status IN ({marks}) "
            "ORDER BY captured_at, id", statuses).fetchall()
        return [self._entry(r) for r in rows]

    def entry(self, invoice_id: str) -> OutboxEntry | None:
        row = self._db.execute("SELECT * FROM pending_invoices WHERE id = ?",
                               (invoice_id,)).fetchone()
        return self._entry(row) if row else None

    def counts(self) -> dict[str, int]:
        result = {PENDING: 0, HELD: 0, SYNCED: 0}
        for status, count in self._db.execute(
                "SELECT status, COUNT(*) FROM pending_invoices "
                "GROUP BY status"):
            result[status] = count
        return result

    def mark_synced(self, invoice_id: str, result: dict) -> None:
        with self._db:
            self._db.execute(
                "UPDATE pending_invoices SET status = ?, invoice_number = ?, "
                "invoice_control = ?, issued_at = ?, last_error = '', "
                "updated_at = ? WHERE id = ?",
                (SYNCED, str(result.get("number") or ""),
                 str(result.get("invoiceControl") or ""), _now(), _now(),
                 invoice_id))

    def mark_held(self, invoice_id: str, reason: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE pending_invoices SET status = ?, last_error = ?, "
                "updated_at = ? WHERE id = ?",
                (HELD, reason, _now(), invoice_id))

    def mark_failed_attempt(self, invoice_id: str, error: str) -> int:
        """Records a try that did not settle it; returns the attempt count."""
        with self._db:
            self._db.execute(
                "UPDATE pending_invoices SET attempts = attempts + 1, "
                "last_error = ?, updated_at = ? WHERE id = ?",
                (error, _now(), invoice_id))
        row = self._db.execute(
            "SELECT attempts FROM pending_invoices WHERE id = ?",
            (invoice_id,)).fetchone()
        return row["attempts"] if row else 0

    def remove(self, invoice_id: str) -> None:
        """Only for an invoice that will never be sent: held, or synced.
        Its lines, serials and payments go with it (ON DELETE CASCADE)."""
        with self._db:
            self._db.execute(
                "DELETE FROM pending_invoices "
                "WHERE id = ? AND status IN (?, ?)",
                (invoice_id, HELD, SYNCED))

    def purge_synced(self) -> None:
        limit = (datetime.now() - SYNCED_RETENTION).isoformat(
            timespec="seconds")
        with self._db:
            self._db.execute(
                "DELETE FROM pending_invoices "
                "WHERE status = ? AND updated_at < ?", (SYNCED, limit))
