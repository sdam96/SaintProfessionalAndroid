"""Connection state, catalogue cache and sending of saved invoices.

SyncService is the single source of truth for "is the server reachable".
Every screen asks it, and it tells them when that changes. It also sends
the outbox, oldest first, whenever the server is reachable.

How an invoice is never issued twice:

1. Each invoice gets a UUID when the user confirms it. The UUID is stored
   with the invoice before anything is sent, and never regenerated.
2. Every send carries it as the Idempotency-Key header. The server records
   the key with the invoice it produced, and a repeated key gets that same
   invoice back instead of a new one.
3. A failure to reach the server, or a missing answer (timeout), leaves the
   invoice pending with the same UUID. Resending is safe whether or not the
   server had processed it.
4. Only one send runs at a time (a lock), so the background loop and a
   manual "send now" never race on the same invoice.
5. An invoice is only marked as sent once the server's answer is stored;
   if the app dies before that, the next send replays the key and gets the
   stored answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from api_client import ApiClient, ApiError, ApiNetworkError
from models import Invoice
from offline_store import PENDING, OfflineStore

# How often the connection is checked: often while offline, so the switch
# back is noticed quickly; less often while online, where any failed
# request already reports the loss.
CHECK_OFFLINE_SECONDS = 10
CHECK_ONLINE_SECONDS = 30

# Codes the server adds to an error, besides the message.
CODE_REVIEW = "REVIEW"            # offline invoice no longer valid as made
CODE_IN_PROGRESS = "IN_PROGRESS"  # this key is being processed right now

# A server error (5xx) is retried this many times before the invoice is
# held for review, so a request that always fails cannot block the queue.
MAX_SERVER_ERRORS = 5

# Full catalogue downloads; the server may cap these.
CATALOG_LIMIT = 10000


class SyncService:
    def __init__(self, api: ApiClient, store: OfflineStore):
        self._api = api
        self._store = store
        self._listeners: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._loop_task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.online = False
        self.syncing = False
        # Database of the server this session works against. Invoices made
        # for another database are never sent here.
        self.database = ""
        # Last outcome worth telling the user about ("3 facturas enviadas").
        self.last_message = ""

    # ----------------------------------------------------------- listeners

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                pass

    # --------------------------------------------------------------- state

    def counts(self) -> dict[str, int]:
        return self._store.counts()

    def set_online(self, online: bool) -> None:
        if online == self.online:
            return
        self.online = online
        self._notify()
        if online:
            self._wake.set()

    def report_network_error(self) -> None:
        """Any request that could not reach the server calls this."""
        self.set_online(False)

    def start(self) -> None:
        """Starts the background loop once; later calls do nothing."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.get_running_loop().create_task(
                self._run())

    def wake(self) -> None:
        """Checks the connection and sends pending invoices now."""
        self._wake.set()

    async def _run(self) -> None:
        while True:
            delay = CHECK_ONLINE_SECONDS if self.online else CHECK_OFFLINE_SECONDS
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                was_online = self.online
                await self.check()
                if self.online:
                    if not was_online:
                        await self.refresh_catalogs()
                    await self.send_pending()
            except Exception:
                # The loop must survive anything; the next round retries.
                pass

    async def check(self) -> bool:
        try:
            info = await self._api.status(quick=True)
        except ApiNetworkError:
            self.set_online(False)
            return False
        except ApiError:
            # It answered, so it is reachable, even if /status complained.
            self.set_online(True)
            return True
        self.remember_server(info)
        self.set_online(True)
        return True

    # ------------------------------------------------------ server identity

    def remember_server(self, info: dict) -> None:
        self.database = str(info.get("baseDatos") or "")
        self._store.save_server(self._api.base_url, info)

    def cached_info(self) -> dict | None:
        saved = self._store.load_server()
        return saved[1] if saved else None

    def cached_url(self) -> str:
        saved = self._store.load_server()
        return saved[0] if saved else ""

    # ---------------------------------------------------------- catalogues

    async def refresh_catalogs(self) -> None:
        """Downloads every catalogue the offline mode searches.

        Each list replaces its copy only when it downloads completely, so
        a dropped connection halfway keeps the previous copy intact.
        """
        api = self._api
        downloads = (
            ("customers", lambda: api.customers(limit=CATALOG_LIMIT)),
            ("products", lambda: api.products(limit=CATALOG_LIMIT)),
            ("salespeople", lambda: api.salespeople(limit=CATALOG_LIMIT)),
            ("warehouses", lambda: api.warehouses(limit=CATALOG_LIMIT)),
            ("instruments",
             lambda: api.payment_instruments(limit=CATALOG_LIMIT)),
            ("banks", lambda: api.banks(limit=CATALOG_LIMIT)),
        )
        for kind, fetch in downloads:
            try:
                rows = await fetch()
            except ApiNetworkError:
                self.report_network_error()
                return
            except ApiError:
                continue
            self._store.replace_catalog(kind, rows)

    # -------------------------------------------------------------- outbox

    def save_offline(self, invoice_id: str, invoice: Invoice,
                     captured_at: str) -> None:
        self._store.add(invoice_id, database=self.database, invoice=invoice,
                        captured_at=captured_at)
        self._notify()
        if self.online:
            self._wake.set()

    async def send_pending(self) -> None:
        """Sends the outbox, oldest first, until it is empty or the
        connection drops. Only one run at a time."""
        if self._lock.locked():
            return
        async with self._lock:
            self.syncing = True
            self._notify()
            sent = held = 0
            try:
                for entry in self._store.entries((PENDING,)):
                    if entry.database_name and self.database and \
                            entry.database_name != self.database:
                        continue
                    outcome = await self._send(entry)
                    if outcome == "offline":
                        break
                    if outcome == "sent":
                        sent += 1
                    elif outcome == "held":
                        held += 1
                    self._notify()
            finally:
                self.syncing = False
                self._store.purge_synced()
                if sent or held:
                    parts = []
                    if sent:
                        parts.append(f"{sent} factura(s) guardada(s) "
                                     "enviada(s)")
                    if held:
                        parts.append(f"{held} requiere(n) revisión")
                    self.last_message = ". ".join(parts) + "."
                self._notify()

    async def _send(self, entry) -> str:
        try:
            result = await self._api.create_invoice(entry.payload, entry.id)
        except ApiNetworkError as exc:
            self._store.mark_failed_attempt(entry.id, str(exc))
            self.report_network_error()
            return "offline"
        except ApiError as exc:
            if exc.code == CODE_IN_PROGRESS:
                # Another send of this same key is still running on the
                # server; its result will be replayed next round.
                self._store.mark_failed_attempt(entry.id, str(exc))
                return "retry"
            if exc.status >= 500:
                attempts = self._store.mark_failed_attempt(entry.id, str(exc))
                if attempts < MAX_SERVER_ERRORS:
                    return "retry"
            # Rejected for this invoice's own content (prices, stock,
            # credit, validation): the user decides.
            self._store.mark_held(entry.id, str(exc))
            return "held"
        self._store.mark_synced(entry.id, result)
        return "sent"


class Catalog:
    """The lists the screens search, online or not.

    Online, it asks the server and refreshes the local copy with what comes
    back. Offline, or when the server cannot be reached, it searches the
    local copy instead. Screens use this, never ApiClient, for catalogues.
    """

    def __init__(self, api: ApiClient, store: OfflineStore, sync: SyncService):
        self._api = api
        self._store = store
        self._sync = sync

    async def _get(self, kind: str, fetch, search: str, limit: int
                   ) -> list[dict]:
        if self._sync.online:
            try:
                rows = await fetch()
            except ApiNetworkError:
                self._sync.report_network_error()
            else:
                self._store.upsert_catalog(kind, rows)
                return rows
        return self._store.search(kind, search, limit)

    async def customers(self, search: str = "", limit: int = 100):
        return await self._get("customers",
                               lambda: self._api.customers(search, limit),
                               search, limit)

    async def products(self, search: str = "", limit: int = 100):
        return await self._get("products",
                               lambda: self._api.products(search, limit),
                               search, limit)

    async def salespeople(self, search: str = "", limit: int = 100):
        return await self._get("salespeople",
                               lambda: self._api.salespeople(search, limit),
                               search, limit)

    async def warehouses(self, limit: int = 100):
        return await self._get("warehouses",
                               lambda: self._api.warehouses(limit), "", limit)

    async def payment_instruments(self, limit: int = 500):
        return await self._get(
            "instruments", lambda: self._api.payment_instruments(limit),
            "", limit)

    async def banks(self, limit: int = 500):
        return await self._get("banks", lambda: self._api.banks(limit),
                               "", limit)

    async def serials(self, product_code: str, warehouse: str) -> list[str]:
        """Serials cannot be reserved offline, so there is no local copy."""
        if not self._sync.online:
            raise ApiError("Los seriales solo se pueden elegir con conexión.")
        try:
            return await self._api.serials(product_code, warehouse)
        except ApiNetworkError:
            self._sync.report_network_error()
            raise


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
