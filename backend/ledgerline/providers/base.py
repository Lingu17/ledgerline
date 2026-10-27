"""Bank provider interface. Amounts cross this boundary as integer minor units."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

# Statuses we normalise provider transfer states into. SENT is not final.
TRANSFER_FINAL_SUCCESS = {"paid"}
TRANSFER_FINAL_FAILURE = {"failed", "cancelled"}


class ProviderError(Exception):
    """Definitive rejection: the provider did not and will not execute this request."""


class ProviderAmbiguous(Exception):
    """We do not know whether the provider executed the request (timeout, 5xx after send).
    The operation must be reconciled by request_id before any retry."""


class ProviderUnsupported(Exception):
    """The capability is not enabled for this account (e.g. payment links)."""


@dataclass
class TransferResult:
    provider_id: str
    request_id: str
    status: str  # processing | sent | paid | failed | cancelled
    raw_status: str


@dataclass
class Quote:
    provider_quote_id: str
    sell_currency: str
    buy_currency: str
    sell_amount_minor: int
    buy_amount_minor: int
    rate: Decimal  # buy units per sell unit
    valid_to: datetime
    source: str


@dataclass
class ConversionResult:
    provider_id: str
    request_id: str
    status: str


@dataclass
class PaymentLinkResult:
    provider_id: str
    url: str


class BankProvider(Protocol):
    name: str
    label: str

    def create_transfer(
        self, *, request_id: str, amount_minor: int, currency: str, destination: str, reference: str
    ) -> TransferResult: ...

    def find_transfer(self, request_id: str) -> TransferResult | None: ...

    def get_transfer(self, provider_id: str) -> TransferResult: ...

    def simulate_transfer_status(self, provider_id: str, next_status: str) -> TransferResult: ...

    def create_quote(self, *, sell_currency: str, buy_currency: str, buy_amount_minor: int) -> Quote: ...

    def create_conversion(
        self, *, request_id: str, quote: Quote
    ) -> ConversionResult: ...

    def get_conversion(self, provider_id: str) -> ConversionResult: ...

    def find_conversion(self, request_id: str) -> ConversionResult | None: ...

    def create_payment_link(
        self, *, title: str, amount_minor: int, currency: str, reference: str
    ) -> PaymentLinkResult: ...


def normalise_transfer_status(raw: str) -> str:
    raw_u = (raw or "").upper()
    if raw_u in {"PAID"}:
        return "paid"
    if raw_u in {"SENT"}:
        return "sent"
    if raw_u in {"FAILED"}:
        return "failed"
    if raw_u in {"CANCELLED", "APPROVAL_REJECTED", "APPROVAL_RECALLED"}:
        # Rejected or recalled in Airwallex's approval flow: never funded, nothing left the wallet.
        return "cancelled"
    # IN_APPROVAL, APPROVAL_BLOCKED, SCHEDULED, PROCESSING, OVERDUE, CANCELLATION_REQUESTED, ... are still in flight.
    return "processing"


def normalise_conversion_status(raw: str) -> str:
    """Airwallex conversions: SCHEDULED | OVERDUE | SETTLED | CANCELLED. Only SETTLED moves cash."""
    raw_u = (raw or "").upper()
    if raw_u == "SETTLED":
        return "settled"
    if raw_u in {"CANCELLED", "FAILED"}:
        return "failed"
    return "processing"
