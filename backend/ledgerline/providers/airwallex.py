"""Airwallex SANDBOX adapter. The base URL is fixed to the sandbox host.

Paths and payloads follow https://www.airwallex.com/docs/api (checked 2026-10-27):
  POST /authentication/login            headers x-client-id + x-api-key, no body -> {token, expires_at}
  POST /simulation/deposit/create       {global_account_id, amount, payer_name, reference}  (currency comes from the global account)
  POST /fx/quotes/create                {sell_currency, buy_currency, buy_amount, validity}
  POST /fx/conversions/create           {request_id, quote_id, sell_currency, buy_currency, buy_amount}
  GET  /fx/conversions/{conversion_id}, GET /fx/conversions?request_id=...  (status SCHEDULED|OVERDUE|SETTLED|CANCELLED)
  POST /transfers/create                {request_id, beneficiary_id, transfer_amount, transfer_currency, source_currency, transfer_method, reason, reference}
  GET  /transfers?request_id=...        look up an ambiguous create before any retry
  GET  /transfers/{id}
  POST /simulation/transfers/{id}/transition  {next_status}
  POST /pa/payment_links/create         {title, reusable, amount, currency, reference}

Read-only authentication/accounts/balances have been exercised against the sandbox.
Money-action verification is tracked separately in docs/INTEGRATION_EVIDENCE.md.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..clock import parse_iso
from ..money import CURRENCY_EXPONENT, to_major, to_minor, validate_minor
from .base import (
    ConversionResult,
    PaymentLinkResult,
    ProviderAmbiguous,
    ProviderError,
    ProviderUnsupported,
    Quote,
    TransferResult,
    normalise_conversion_status,
    normalise_transfer_status,
)

SANDBOX_BASE_URL = "https://api.sandbox.airwallex.com/api/v1"
TOKEN_SAFETY_MARGIN = timedelta(seconds=120)


def _amount_str(amount_minor: int, currency: str) -> str:
    """Exact decimal string ("1250.00"): the transfer and conversion APIs document amounts as strings."""
    return f"{to_major(amount_minor, currency):.{CURRENCY_EXPONENT[currency]}f}"


def _json_amount(value: Decimal) -> float:
    """Encode a Decimal major amount as a JSON number without losing precision."""
    f = float(value)
    if Decimal(repr(f)) != value.normalize() and Decimal(repr(f)) != value:
        raise ValueError(f"amount {value} cannot be represented exactly")
    return f


class AirwallexSandbox:
    name = "airwallex_sandbox"
    label = "AIRWALLEX SANDBOX (test environment, no real money)"

    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        now_fn=lambda: datetime.now(timezone.utc),
    ) -> None:
        if not client_id or not api_key:
            raise ValueError("Airwallex sandbox credentials are required")
        self._client_id = client_id
        self._api_key = api_key
        self._http = httpx.Client(base_url=SANDBOX_BASE_URL, transport=transport, timeout=timeout)
        self._token: str | None = None
        self._token_expires: datetime | None = None
        self._lock = threading.Lock()
        self._now = now_fn

    # Auth ----------------------------------------------------------------
    def _bearer(self) -> str:
        with self._lock:
            if self._token and self._token_expires and self._now() < self._token_expires - TOKEN_SAFETY_MARGIN:
                return self._token
            resp = self._http.post(
                "/authentication/login",
                headers={"x-client-id": self._client_id, "x-api-key": self._api_key},
            )
            if resp.status_code >= 400:
                raise ProviderError(f"authentication failed: HTTP {resp.status_code}")
            body = resp.json()
            self._token = body["token"]
            self._token_expires = parse_iso(body["expires_at"]) if body.get("expires_at") else self._now() + timedelta(minutes=25)
            return self._token

    def _request(self, method: str, path: str, *, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None,
                 money_out: bool = False) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._bearer()}"}
        content = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(body)
        try:
            resp = self._http.request(method, path, headers=headers, content=content, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if money_out:
                raise ProviderAmbiguous(f"{method} {path}: {type(exc).__name__}") from exc
            raise ProviderError(f"{method} {path}: {type(exc).__name__}") from exc
        if resp.status_code >= 500 and money_out:
            raise ProviderAmbiguous(f"{method} {path}: HTTP {resp.status_code}")
        if resp.status_code >= 400:
            code = ""
            try:
                code = resp.json().get("code", "")
            except ValueError:
                pass
            raise ProviderError(f"{method} {path}: HTTP {resp.status_code} {code}".strip())
        return resp.json() if resp.content else {}

    def readiness(self) -> dict[str, Any]:
        """Read-only connection check from the Airwallex hackathon guide: authenticate, list global
        accounts, list current wallet balances. Moves no money and creates nothing."""
        self._bearer()
        accounts = self._request("GET", "/global_accounts", params={"page_size": 50})
        items = accounts.get("items", []) if isinstance(accounts, dict) else []
        balances = self._request("GET", "/balances/current")
        rows = balances if isinstance(balances, list) else balances.get("items", []) if isinstance(balances, dict) else []
        summaries = []
        for account in items:
            summary = {"id": account.get("id"), "currency": account.get("currency"), "status": account.get("status")}
            # Current multi-currency accounts report receiving currencies in supported_features.
            # https://www.airwallex.com/docs/accounts/get-started/global-accounts
            features = account.get("supported_features")
            if isinstance(features, list):
                summary["supported_currencies"] = sorted({
                    feature["currency"] for feature in features
                    if isinstance(feature, dict) and feature.get("type") in (None, "DEPOSIT")
                    and isinstance(feature.get("currency"), str)
                    and len(feature["currency"]) == 3 and feature["currency"].isascii()
                    and feature["currency"].isupper()
                })
            summaries.append(summary)
        return {
            "global_accounts": summaries,
            "balances": [{"currency": b.get("currency"), "available_amount": b.get("available_amount")} for b in rows],
        }

    # Deposits ------------------------------------------------------------
    def current_rate(self, sell_currency: str, buy_currency: str) -> dict[str, Any]:
        """Indicative client rate (GET /fx/rates/current). Display only: conversions always use a booked quote."""
        r = self._request("GET", "/fx/rates/current", params={"sell_currency": sell_currency, "buy_currency": buy_currency})
        rate, pair = r.get("rate"), r.get("currency_pair")
        if isinstance(rate, bool) or not isinstance(rate, (int, float, str)) or Decimal(str(rate)) <= 0:
            raise ProviderError("rate response had no positive numeric rate")
        # `rate` is quoted in market convention for `currency_pair` (BASEQUOTE: quote units per one base unit), so
        # GBP->EUR comes back as EURGBP 0.84. Normalise to buy units per sell unit, as quotes and the UI use.
        if pair == sell_currency + buy_currency:
            per_sell = Decimal(str(rate))
        elif pair == buy_currency + sell_currency:
            per_sell = Decimal(1) / Decimal(str(rate))
        else:
            raise ProviderError(f"rate response was for another currency pair {str(pair)[:12]!r}")
        return {"sell": sell_currency, "buy": buy_currency, "rate": str(per_sell.quantize(Decimal("0.000001"))),
                "pair": pair, "market_rate": str(Decimal(str(rate))), "as_of": r.get("created_at")}

    def list_deposits(self, *, page_num: int, page_size: int = 100) -> dict[str, Any]:
        """GET /deposits, one page. The sandbox requires page_num and page_size together."""
        r = self._request("GET", "/deposits", params={"page_num": page_num, "page_size": page_size})
        if not isinstance(r, dict) or not isinstance(r.get("items"), list):
            raise ProviderError("deposit list response had no items")
        return r

    # Beneficiaries -------------------------------------------------------------
    def beneficiary_schema(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/beneficiaries/schema", body=body)

    def validate_beneficiary(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """POST /beneficiaries/validate. Returns field errors ([] when valid); creates nothing."""
        headers = {"Authorization": f"Bearer {self._bearer()}", "Content-Type": "application/json"}
        resp = self._http.post("/beneficiaries/validate", headers=headers, content=json.dumps(body))
        if resp.status_code < 400:
            return []
        try:
            out = resp.json()
        except ValueError:
            out = {}
        errors = (out.get("details") or {}).get("errors") if isinstance(out, dict) else None
        if resp.status_code == 400 and isinstance(errors, list):
            return [{"field": str(e.get("source", "")), "code": str(e.get("code", ""))} for e in errors if isinstance(e, dict)]
        raise ProviderError(f"POST /beneficiaries/validate: HTTP {resp.status_code} {out.get('code', '') if isinstance(out, dict) else ''}".strip())

    def create_beneficiary(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/beneficiaries/create", body=body)

    def list_beneficiaries(self) -> list[dict[str, Any]]:
        r = self._request("GET", "/beneficiaries", params={"page_num": 0, "page_size": 100})
        return r.get("items", []) if isinstance(r, dict) else []

    def simulate_deposit(self, *, global_account_id: str, currency: str, amount_minor: int, payer_name: str,
                         reference: str) -> dict[str, Any]:
        validate_minor(amount_minor)
        amount = _json_amount(to_major(amount_minor, currency))
        if not isinstance(global_account_id, str) or not global_account_id or any(c not in
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in global_account_id):
            raise ProviderError("invalid global account id")
        # Verify BEFORE creating anything: Airwallex ignores a currency field on this API.
        account = self._request("GET", f"/global_accounts/{global_account_id}")
        if account.get("currency"):
            currencies = {account["currency"]}
        else:
            features = account.get("supported_features")
            currencies = {f.get("currency") for f in (features if isinstance(features, list) else [])
                          if isinstance(f, dict) and f.get("type") in (None, "DEPOSIT")
                          and isinstance(f.get("currency"), str)}
        if currencies != {currency}:
            raise ProviderError("deposit simulation requires a global account dedicated to the requested currency")
        # `currency` is NOT sent: the global account determines it. It is used only to format the amount.
        out = self._request("POST", "/simulation/deposit/create", body={
            "global_account_id": global_account_id,
            "amount": amount,
            "payer_name": payer_name,
            "reference": reference,
        })
        if out.get("currency") and out["currency"] != currency:
            raise ProviderError(f"global account {global_account_id} is {out['currency']}, expected {currency}")
        return out

    # Transfers -------------------------------------------------------------
    def get_deposit(self, deposit_id: str) -> dict[str, Any]:
        out = self._request("GET", f"/deposits/{deposit_id}")
        out.setdefault("id", out.get("deposit_id") or deposit_id)
        return out

    def _transfer(self, t: dict[str, Any]) -> TransferResult:
        return TransferResult(t["id"], t.get("request_id", ""), normalise_transfer_status(t.get("status", "")), t.get("status", ""))

    def create_transfer(self, *, request_id, amount_minor, currency, destination, reference, reason="refund") -> TransferResult:
        t = self._request("POST", "/transfers/create", money_out=True, body={
            "request_id": request_id,
            "beneficiary_id": destination,
            "transfer_amount": _amount_str(amount_minor, currency),
            "transfer_currency": currency,
            "source_currency": currency,
            "transfer_method": "LOCAL",
            "reason": reason,
            "reference": reference[:140],
        })
        return self._transfer(t)

    def find_transfer(self, request_id: str) -> TransferResult | None:
        out = self._request("GET", "/transfers", params={"request_id": request_id})
        items = out.get("items", [])
        matches = [i for i in items if i.get("request_id") == request_id]
        if len(matches) > 1:
            raise ProviderError(f"multiple transfers share request_id {request_id}")
        return self._transfer(matches[0]) if matches else None

    def get_transfer(self, provider_id: str) -> TransferResult:
        return self._transfer(self._request("GET", f"/transfers/{provider_id}"))

    def simulate_transfer_status(self, provider_id: str, next_status: str) -> TransferResult:
        return self._transfer(self._request("POST", f"/simulation/transfers/{provider_id}/transition",
                                            body={"next_status": next_status.upper()}))

    # FX (no x-api-version header is sent) ------------------------------------
    def create_quote(self, *, sell_currency, buy_currency, buy_amount_minor) -> Quote:
        q = self._request("POST", "/fx/quotes/create", body={
            "sell_currency": sell_currency,
            "buy_currency": buy_currency,
            "buy_amount": _json_amount(to_major(buy_amount_minor, buy_currency)),
            "validity": "MIN_1",
        })
        # Airwallex chooses `usage` (the sandbox returns MULTI_USE); single use is enforced locally when a
        # conversion consumes the quote, so a multi-use quote is never spent twice by Ledgerline.
        return Quote(
            provider_quote_id=q["quote_id"],
            sell_currency=sell_currency,
            buy_currency=buy_currency,
            sell_amount_minor=to_minor(q["sell_amount"], sell_currency),
            buy_amount_minor=to_minor(q["buy_amount"], buy_currency),
            # client_rate is quoted for the market pair (EURGBP even when selling GBP); the booked amounts give
            # buy units per sell unit in either direction. Display/record only: money uses the amounts themselves.
            rate=(Decimal(str(q["buy_amount"])) / Decimal(str(q["sell_amount"]))).quantize(Decimal("0.000001")),
            valid_to=parse_iso(q["valid_to_at"]),
            source="airwallex_sandbox",
        )

    def create_conversion(self, *, request_id, quote: Quote) -> ConversionResult:
        c = self._request("POST", "/fx/conversions/create", money_out=True, body={
            "request_id": request_id,
            "quote_id": quote.provider_quote_id,
            "sell_currency": quote.sell_currency,
            "buy_currency": quote.buy_currency,
            "buy_amount": _amount_str(quote.buy_amount_minor, quote.buy_currency),
        })
        return self._conversion(c)

    def _conversion(self, c: dict[str, Any]) -> ConversionResult:
        return ConversionResult(c.get("conversion_id", ""), c.get("request_id", ""), normalise_conversion_status(c.get("status", "")))

    def get_conversion(self, provider_id: str) -> ConversionResult:
        return self._conversion(self._request("GET", f"/fx/conversions/{provider_id}"))

    def find_conversion(self, request_id: str) -> ConversionResult | None:
        items = [i for i in self._request("GET", "/fx/conversions", params={"request_id": request_id}).get("items", [])
                 if i.get("request_id") == request_id]
        if len(items) > 1:
            raise ProviderError(f"multiple conversions share request_id {request_id}")
        return self._conversion(items[0]) if items else None

    # Payment links -----------------------------------------------------------
    def create_payment_link(self, *, title, amount_minor, currency, reference) -> PaymentLinkResult:
        try:
            out = self._request("POST", "/pa/payment_links/create", body={
                "title": title,
                "reusable": False,
                "amount": _json_amount(to_major(amount_minor, currency)),
                "currency": currency,
                "reference": reference,
            })
        except ProviderError as exc:
            if any(code in str(exc) for code in ("HTTP 401", "HTTP 403", "HTTP 404")):
                raise ProviderUnsupported(str(exc)) from exc
            raise
        if not out.get("url"):
            raise ProviderUnsupported("payment link response had no url")
        return PaymentLinkResult(out["id"], out["url"])

    def payment_link_paid(self, provider_id: str) -> bool:
        """A single-use link is paid when Airwallex says so or counts a successful payment. Anything else is not paid."""
        out = self._request("GET", f"/pa/payment_links/{provider_id}")
        return str(out.get("status", "")).upper() == "PAID" or (out.get("successful_payment_intent_count") or 0) > 0
