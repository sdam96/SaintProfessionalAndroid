"""Async HTTP client for the Saint Professional API.

Async throughout because Flet 1.0 runs event handlers on the asyncio loop
and updates the page automatically when a handler returns.
"""

import httpx
from typing import Any

# Shared secret compiled into the server as well. It ships inside the APK
# and can be recovered from either binary; it keeps casual callers out, not
# a determined one.
API_KEY = "SaintPro-2026-0f3a91c7d4e85b62"
API_KEY_HEADER = "X-API-Key"

# Opening the connection fails fast when the host is unreachable; reading
# keeps the longer limit because issuing an invoice can take a while.
CONNECT_TIMEOUT = 8.0

# Header carrying the invoice's UUID. The server keeps the result of every
# key it has processed, so sending the same invoice again (a retry after a
# timeout, or the offline queue) returns that result instead of issuing a
# second invoice. Name as in the IETF draft "The Idempotency-Key HTTP
# Header Field".
IDEMPOTENCY_HEADER = "Idempotency-Key"


class ApiError(Exception):
    """Carries the message the server sent back, not the raw HTTP status.

    `code` is the machine-readable reason the server may add next to the
    message ({"error": "...", "code": "REVIEW"}); empty when it sent none.
    """

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class ApiNetworkError(ApiError):
    """The server could not be reached, or did not answer in time.

    Unlike other ApiErrors this says nothing about the request itself: the
    server may never have received it, or may have processed it and the
    answer was lost. That is why an invoice is always sent with its
    idempotency key: resending it is then safe in both cases.
    """


def _named(rows: list[dict]) -> list[dict]:
    """Drops rows with no code or no name.

    A record without a name cannot be invoiced, so it never reaches the
    pickers rather than showing up as an unselectable placeholder.
    """
    return [r for r in rows
            if (r.get("code") or "").strip()
            and (r.get("name") or "").strip()]


def _with_code(rows: list[dict]) -> list[dict]:
    """Keeps rows with a code; name may be blank. Trims both.

    Used for catalogues where the code alone is a valid value even when the
    name is empty (payment instruments, banks).
    """
    result = []
    for row in rows:
        code = (row.get("code") or "").strip()
        if code:
            result.append({**row, "code": code,
                           "name": (row.get("name") or "").strip()})
    return result


def _describe(exc: httpx.RequestError) -> str:
    """A message for whoever is setting up the connection."""
    if isinstance(exc, httpx.ConnectTimeout):
        return ("El servidor no respondió. Verifique la dirección, el puerto "
                "y que el firewall del servidor permita la conexión.")
    if isinstance(exc, httpx.ReadTimeout):
        return "El servidor tardó demasiado en responder."
    if isinstance(exc, httpx.ConnectError):
        return f"No se pudo conectar con el servidor: {exc}"
    return f"Error de comunicación con el servidor: {exc}"


class ApiClient:
    def __init__(self, base_url: str = "", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    async def _request(self, method: str, path: str,
                       timeout: httpx.Timeout | None = None,
                       **kwargs) -> Any:
        headers = kwargs.pop("headers", {})
        headers[API_KEY_HEADER] = API_KEY
        try:
            async with httpx.AsyncClient(
                    timeout=timeout or self.timeout) as client:
                response = await client.request(
                    method, self._url(path), headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise ApiNetworkError(_describe(exc)) from exc

        if response.status_code >= 400:
            # The API answers errors as {"error": "...", "code": "..."} in
            # Spanish; "code" is optional.
            code = ""
            try:
                body = response.json()
                detail = body.get("error", response.text)
                code = str(body.get("code") or "")
            except (ValueError, AttributeError):
                detail = response.text
            raise ApiError(
                detail or f"El servidor respondió {response.status_code}.",
                response.status_code, code)

        # Something other than this API may be answering on that address
        # (a router page, another program on the same port, a proxy).
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(
                "La dirección responde, pero no es el servidor de Saint "
                f"Professional (respuesta {response.status_code} sin JSON).",
                response.status_code) from exc

    async def status(self, quick: bool = False) -> dict:
        """The server's /status. `quick` uses short limits, for the
        connection checks that run in the background."""
        timeout = httpx.Timeout(4.0, connect=3.0) if quick else None
        return await self._request("GET", "/status", timeout=timeout)

    async def customers(self, search: str = "", limit: int = 100) -> list[dict]:
        params = {
            "fields": "code,name,taxId,address,phone,priceList,creditDays,"
                      "creditLimit,salesperson",
            "limit": limit,
        }
        if search:
            params["name[like]"] = search
        rows = (await self._request("GET", "/customers", params=params))["data"]
        return _named(rows)

    async def create_customer(self, payload: dict) -> dict:
        return await self._request("POST", "/customers", json=payload)

    async def products(self, search: str = "", limit: int = 100) -> list[dict]:
        params = {
            "fields": "code,name,unit,price1,price2,price3,stock,stock2,"
                      "stock3,stock4,stock5,taxRate,exempt,inventoryType,"
                      "usesSerial",
            "limit": limit,
        }
        if search:
            params["name[like]"] = search
        rows = (await self._request("GET", "/products", params=params))["data"]
        return _named(rows)

    async def serials(self, product_code: str, warehouse: str,
                      limit: int = 500) -> list[str]:
        """Serials on hand for a product in one warehouse.

        Every row ivserial holds is available: Saint deletes them as they
        are sold rather than flagging them.
        """
        params = {"warehouse": warehouse, "limit": limit}
        rows = (await self._request(
            "GET", f"/products/{product_code}/serials", params=params))["data"]
        return [r["serial"] for r in rows if (r.get("serial") or "").strip()]

    async def salespeople(self, search: str = "", limit: int = 100) -> list[dict]:
        params = {"fields": "code,name,phone", "limit": limit}
        if search:
            params["name[like]"] = search
        rows = (await self._request("GET", "/salespeople", params=params))["data"]
        return _named(rows)

    async def warehouses(self, limit: int = 100) -> list[dict]:
        params = {"fields": "code,name,manager", "limit": limit}
        rows = (await self._request("GET", "/warehouses", params=params))["data"]
        return _named(rows)

    async def payment_instruments(self, limit: int = 500) -> list[dict]:
        """Payment instruments (the "Tipo" picker) defined in cfinstru.

        The endpoint returns fixed keys (code, name, function, class,
        withholdingRate, taxRate, deferredDays) and ignores ?fields=, so
        only the page size is sent.

        Unlike the other catalogues, a row without a name is kept: NOMBRE
        is optional in cfinstru and the code alone is still a valid
        instrument.
        """
        params = {"limit": limit}
        rows = (await self._request(
            "GET", "/payment-instruments", params=params))["data"]
        return _with_code(rows)

    async def banks(self, limit: int = 500) -> list[dict]:
        """Banks (the "Banco" picker) defined in the bancos table.

        Like payment instruments, a row without a name is kept: the code
        alone is a valid bank. Codes are trimmed to match what the server
        stores in dcheader.CODBANCO.
        """
        params = {"limit": limit}
        rows = (await self._request("GET", "/banks", params=params))["data"]
        return _with_code(rows)

    async def create_invoice(self, payload: dict,
                             idempotency_key: str) -> dict:
        """Issues an invoice. The same key always yields the same invoice:
        the server answers a repeated key with the stored result."""
        return await self._request(
            "POST", "/invoices", json=payload,
            headers={IDEMPOTENCY_HEADER: idempotency_key})