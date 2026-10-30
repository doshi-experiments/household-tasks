"""Loblaw's PC Express web API, anonymously: product search and lookups by code
for Superstore, No Frills and Wholesale Club stores.

This is the undocumented API behind the chains' own websites, called with the
static key their pages ship (PCX_API_KEY), no login. Loblaw's terms don't allow
automated use; this is household use at one request every 2 s. A 401 (the key
changed) or 403 (refused) stops everything (PcxBlocked) and is never retried.

Prices, sales and stock are per store. Product codes ("21424991_EA") are the
same at every chain. parse_product() turns either response shape (search
results, or a product's offers[0]) into one flat dict; tested offline in
tests/test_prices.py.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.pcexpress.ca/pcx-bff/api/v1"
GAP = 2.0       # seconds between requests
TIMEOUT = 10.0


class PcxBlocked(Exception):
    """Loblaw refused us (401: the web key changed; 403: blocked). Stop, don't retry."""


class PcxError(Exception):
    """Any other failure: a 5xx, a timeout, a body that isn't the shape we know."""


def _cents(v) -> int | None:
    try:
        return None if v is None else round(float(v) * 100)
    except (TypeError, ValueError):
        return None


def _day(v) -> str | None:
    """'2026-11-04T00:00' -> '2026-11-04'; the open-ended 9999 date -> None."""
    v = str(v or "")[:10]
    return v if v and not v.startswith("9999") else None


def parse_product(p: dict) -> dict:
    """One product, from a search result or a lookup by code (its offers[0])."""
    offer = (p.get("offers") or [None])[0] or {}
    prices = p.get("prices") or offer
    badges = p.get("badges") or offer.get("badges") or {}
    price, was = prices.get("price") or {}, prices.get("wasPrice") or {}
    unit = (prices.get("comparisonPrices") or [{}])[0] or {}
    deal, loyalty = badges.get("dealBadge") or {}, badges.get("loyaltyBadge") or {}
    member = prices.get("memberOnlyPrice") or {}
    image = (p.get("imageAssets") or [{}])[0] or {}
    price_cents = _cents(price.get("value"))
    was_cents = _cents(was.get("value"))
    return {
        "code": p.get("code"),
        "name": (p.get("name") or "").strip(),
        "brand": (p.get("brand") or "").strip(),
        "size": (p.get("packageSize") or "").strip(),
        "link": p.get("link") or "",
        "image": image.get("mediumUrl") or image.get("smallUrl") or "",
        "price_cents": price_cents,
        "regular_cents": was_cents or price_cents,
        "on_sale": bool(was_cents and price_cents is not None and price_cents < was_cents),
        "sale_ends": _day(price.get("expiryDate")) if price.get("type") == "SPECIAL" else None,
        "unit_cents": _cents(unit.get("value")),
        "unit_qty": unit.get("quantity"),
        "unit": unit.get("unit"),
        "deal_type": deal.get("type"),
        "deal_text": deal.get("text"),
        "deal_cents": _cents(p.get("dealPrice")) if deal.get("type") == "MULTI" else None,
        "deal_ends": _day(deal.get("expiryDate")),
        "points": loyalty.get("points"),
        "points_ends": _day(loyalty.get("expiryDate")),
        "member_cents": _cents(member.get("value")),
        "in_stock": (p.get("stockStatus") or offer.get("stockStatus") or "OK") == "OK",
    }


class Pcx:
    def __init__(self, api_key: str, tz: ZoneInfo, transport: httpx.BaseTransport | None = None,
                 gap: float = GAP, timeout: float = TIMEOUT):
        self.api_key, self.tz, self.gap = api_key, tz, gap
        self.http = httpx.Client(base_url=BASE, timeout=timeout, transport=transport)
        self._lock = threading.Lock()   # one request at a time, GAP apart, from any thread
        self._last = 0.0
        self.requests = 0

    def close(self):
        self.http.close()

    def _headers(self, banner: str) -> dict:
        return {"Accept": "application/json", "Accept-Language": "en", "Site-Banner": banner, "baseSiteId": banner,
                "Business-User-Agent": "PCXWEB", "x-channel": "web", "x-application-type": "Web",
                "x-loblaw-tenant-id": "ONLINE_GROCERIES", "x-apikey": self.api_key,
                "User-Agent": "Mozilla/5.0 (household price check)"}

    def _date(self) -> str:
        # DDMMYYYY: an ISO date gets a 200 with stale or empty results
        return datetime.now(self.tz).strftime("%d%m%Y")

    def _call(self, method: str, path: str, banner: str, **kw) -> dict:
        with self._lock:
            wait = self.gap - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.http.request(method, path, headers=self._headers(banner), **kw)
            except httpx.HTTPError as e:
                raise PcxError(f"{type(e).__name__}: {e}") from e
            finally:
                self._last = time.monotonic()
                self.requests += 1
        if r.status_code in (401, 403):
            raise PcxBlocked(f"HTTP {r.status_code}" + (" (the web key has probably changed)" if r.status_code == 401 else ""))
        if r.status_code == 404:
            return {}
        if r.status_code != 200:
            raise PcxError(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise PcxError("not JSON") from e

    def search(self, banner: str, store_id: str, term: str, size: int = 12) -> list[dict]:
        body = {"pagination": {"from": 0, "size": size}, "banner": banner, "cartId": str(uuid.uuid4()),
                "lang": "en", "date": self._date(), "storeId": str(store_id), "pcId": None, "pickupType": "STORE",
                "offerType": "ALL", "term": term, "userData": {"domainUserId": "", "sessionId": ""}}
        js = self._call("POST", "/products/search", banner, json=body)
        return [parse_product(p) for p in (js.get("results") or []) if p.get("code")]

    def product(self, banner: str, store_id: str, code: str) -> dict | None:
        """One product's price at one store; None when the store doesn't list it."""
        js = self._call("GET", f"/products/{code}", banner, params={
            "lang": "en", "date": self._date(), "pickupType": "STORE", "storeId": str(store_id), "banner": banner})
        if not js.get("code") or not js.get("offers"):
            return None
        out = parse_product(js)
        return out if out["price_cents"] is not None else None
