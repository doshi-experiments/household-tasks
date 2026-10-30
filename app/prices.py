"""Loblaw prices for the shopping list. Never sends anything.

- link(): a staple's product ("Natrel 2%" for milk) is matched once to a
  product in Loblaw's catalogue by searching the first store and scoring the
  results (brand, the label's words, the staple's word, the size when given).
  An unsure match stays unlinked rather than wrong.
- autopick(): an item at a Loblaw store that nobody named a product for gets
  one picked (pick_plain: the plainest product carrying its word, "2% Regular
  Milk" for milk), which becomes the word's usual until someone names another.
- refresh(): the linked products' prices at every configured store, by code,
  weekly (PRICES_REFRESH, Thursday morning when the flyer week starts) and
  from the Shopping tab's button (the list only, at most hourly).
- view(): for each item on the list, its price at each store, the cheapest
  and the saving; per-store totals over items priced everywhere; and whether
  splitting the trip saves at least PRICES_SPLIT_MIN.

Observations are only ever added (price_obs), so later phases can tell a real
sale from a routine one. A price more than 50% off the previous one for the
same code and store is kept but marked suspect, and is left out until the next
check agrees with it. Tested offline in tests/test_prices.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from .pcx import Pcx, PcxBlocked, PcxError
from .staples import Staples, allowed_edits, distance, norm
from .store import Store
from .tasks import TaskError

log = logging.getLogger("tasks.prices")

BANNERS = {"superstore": "Real Canadian Superstore", "nofrills": "No Frills", "wholesaleclub": "Wholesale Club"}
SHORT = {"superstore": "Superstore", "nofrills": "No Frills", "wholesaleclub": "Wholesale Club"}
STORE_BANNER = {name: banner for banner, name in BANNERS.items()}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FRESH = timedelta(days=10)          # older prices aren't shown
RECENT = timedelta(weeks=8)         # the weekly refresh covers what was bought this recently
COOLDOWN = timedelta(hours=1)       # between button presses
CATCH_UP = timedelta(days=7)        # refresh on start-up when the last one is older
SUSPECT_JUMP = 0.5
LINK_BUDGET = 8.0                   # seconds an add waits for its products to be matched

_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|millilitres?|l|litres?|liters?|kg|kilos?|g|grams?|lbs?|pounds?|oz)\b", re.I)
_UNITS = {"ml": ("ml", 1), "l": ("ml", 1000), "kg": ("g", 1000), "g": ("g", 1), "lb": ("g", 453.6), "oz": ("g", 28.35)}


# ------------------------------------------------------------ pure helpers
def parse_slot(text: str) -> tuple[int, int, int]:
    """'thu 07:00' -> (3, 7, 0). Raises ValueError for anything else."""
    m = re.fullmatch(r"\s*([a-z]{3})[a-z]*\s+([01]\d|2[0-3]):([0-5]\d)\s*", (text or "").lower())
    if not m or m.group(1) not in DAYS:
        raise ValueError(f"{text!r} isn't like 'thu 07:00'")
    return DAYS.index(m.group(1)), int(m.group(2)), int(m.group(3))


def next_slot(now: datetime, slot: str) -> datetime:
    """The next time (after now) the weekly slot comes round, in now's zone."""
    day, hh, mm = parse_slot(slot)
    at = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=(day - now.weekday()) % 7)
    return at if at > now else at + timedelta(days=7)


def size_of(text: str) -> tuple[float, str] | None:
    """The first size in a text, in ml or g: '4 l' -> (4000, 'ml'), '9.07 kg' -> (9070, 'g'), '20 lb' -> (9072, 'g')."""
    m = _SIZE.search(text or "")
    if not m:
        return None
    unit = m.group(2).lower()
    if unit == "ml" or unit.startswith("milli"):
        key = "ml"
    elif unit.startswith(("lb", "pound")):
        key = "lb"
    elif unit.startswith("l"):
        key = "l"
    elif unit.startswith("k"):
        key = "kg"
    else:
        key = "oz" if unit == "oz" else "g"
    base, factor = _UNITS[key]
    return round(float(m.group(1).replace(",", ".")) * factor, 3), base


def _same_size(a: tuple[float, str], b: tuple[float, str]) -> bool:
    return a[1] == b[1] and abs(a[0] - b[0]) <= 0.05 * max(a[0], b[0])


def score(label: str, staple: str, cand: dict) -> float | None:
    """How well a catalogue product fits the household's words for it, or None
    when it doesn't fit. It must carry at least 60% of the label's words (sizes
    aside) and either the brand or the staple's word; a size in the label must
    match. Ties go to Loblaw's own order."""
    want_size = size_of(label)
    words = norm(_SIZE.sub(" ", label)).split()
    have = set(norm(f"{cand.get('brand', '')} {cand.get('name', '')}").split())
    brand = norm(cand.get("brand") or "").split()
    staple_words = norm(staple).split()
    cover = sum(w in have for w in words) / len(words) if words else 0.0
    brand_hit = bool(brand) and brand[0] in words
    staple_hit = bool(staple_words) and all(w in have for w in staple_words)
    size_hit = False
    if want_size:
        got = size_of(cand.get("size") or "") or size_of(cand.get("name") or "")
        if not got or not _same_size(want_size, got):
            return None
        size_hit = True
    if words and cover < 0.6:
        return None
    if not (brand_hit or staple_hit) or (not words and not size_hit):
        return None
    return round(2 * cover + brand_hit + staple_hit + size_hit, 3)


def pick(label: str, staple: str, cands: list[dict]) -> tuple[dict, float] | None:
    best = None
    for c in cands:
        s = score(label, staple, c)
        if s is not None and (best is None or s > best[1]):
            best = (c, s)
    return best


def _near(a: str, b: str) -> bool:
    return bool(a and b) and a[0] == b[0] and distance(a, b) <= allowed_edits(min(len(a), len(b)))


def _covers(words: list[str], have: list[str]) -> bool:
    """Every word of the title is in the product's words, typos allowed, or the
    whole title is (spaces aside: "bana ganush" in "Baba Ganoush")."""
    flat = "".join(words)
    if any(_near(flat, "".join(have[i:i + n])) for i in range(len(have)) for n in (1, 2, 3)):
        return True
    return all(any(_near(w, h) for h in have) for w in words)


def pick_plain(title: str, cands: list[dict]) -> dict | None:
    """For a word nobody named a product for ("milk"): the in-stock product
    carrying it with the fewest other words in its name ("2% Regular Milk"
    before "Vanilla Protein Shake Milk"), Loblaw's order on a tie."""
    words = norm(title).split()
    best = None
    for i, c in enumerate(cands):
        if not words or not c.get("in_stock", True) or c.get("price_cents") is None:
            continue
        name = norm(c.get("name") or "").split()
        if not _covers(words, norm(f"{c.get('brand') or ''} {c.get('name') or ''}").split()):
            continue
        key = (sum(not any(_near(w, n) for w in words) for n in name), i)
        if best is None or key < best[0]:
            best = (key, c)
    return best[1] if best else None


def multibuy(deal_text: str | None, deal_cents: int | None) -> str | None:
    """'$4.00 MIN 2' -> '2 for $8.00'."""
    m = re.search(r"MIN\s*(\d+)", deal_text or "", re.I)
    if not (m and deal_cents):
        return None
    n = int(m.group(1))
    return f"{n} for ${n * deal_cents / 100:.2f}"


# ------------------------------------------------------------ the service
class Prices:
    def __init__(self, store: Store, staples: Staples, clock: Callable[[], datetime], pcx: Pcx | None,
                 stores: tuple[tuple[str, str], ...], slot: str = "thu 07:00", split_min: float = 10.0):
        self.store, self.staples, self.clock, self.pcx = store, staples, clock, pcx
        self.stores, self.slot, self.split_min_cents = tuple(stores), slot, round(split_min * 100)
        self._refresh_lock = threading.Lock()
        self.running = False

    @property
    def enabled(self) -> bool:
        return bool(self.pcx and self.stores)

    def _utc(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat(timespec="seconds")

    # ---------------------------------------------------------- settings
    def _get(self, key: str, default=None):
        row = self.store.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def _set(self, key: str, value):
        with self.store.tx() as db:
            db.execute("INSERT INTO settings(key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE"
                       " SET value=excluded.value, updated_at=excluded.updated_at", (key, json.dumps(value), self._utc()))

    def _note(self, banner: str | None, ok: bool, error: str = ""):
        status = self._get("prices.status", {"blocked": None, "stores": {}})
        if banner:
            status["stores"][banner] = {"ok": ok, "at": self._utc(), "error": error}
        self._set("prices.status", status)

    def _blocked(self, why: str):
        status = self._get("prices.status", {"blocked": None, "stores": {}})
        status["blocked"] = {"at": self._utc(), "why": why}
        self._set("prices.status", status)
        log.warning("prices paused: Loblaw refused us (%s); check PCX_API_KEY", why)

    # ---------------------------------------------------------- observations
    def record(self, banner: str, p: dict) -> None:
        if not p.get("code") or p.get("price_cents") is None:
            return
        with self.store.tx() as db:
            prev = db.execute("SELECT price_cents FROM price_obs WHERE code=? AND banner=? ORDER BY observed_at DESC, id DESC"
                              " LIMIT 1", (p["code"], banner)).fetchone()
            suspect = bool(prev and prev[0] and abs(p["price_cents"] - prev[0]) / prev[0] > SUSPECT_JUMP)
            db.execute("INSERT INTO price_obs(code, banner, observed_at, price_cents, regular_cents, unit_cents, unit_qty,"
                       " unit, on_sale, sale_ends, deal_type, deal_text, deal_cents, deal_ends, points, points_ends,"
                       " member_cents, in_stock, suspect) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (p["code"], banner, self._utc(), p["price_cents"], p["regular_cents"], p["unit_cents"],
                        p["unit_qty"], p["unit"], int(bool(p["on_sale"])), p["sale_ends"], p["deal_type"], p["deal_text"],
                        p["deal_cents"], p["deal_ends"], p["points"], p["points_ends"], p["member_cents"],
                        int(bool(p["in_stock"])), int(suspect)))

    def latest(self, code: str) -> dict[str, dict]:
        """The newest trusted, recent, in-stock price per store for a code."""
        since = (self.clock() - FRESH).astimezone(timezone.utc).isoformat(timespec="seconds")
        out = {}
        for banner, _ in self.stores:
            row = self.store.one("SELECT * FROM price_obs WHERE code=? AND banner=? AND suspect=0 AND observed_at>=?"
                                 " ORDER BY observed_at DESC, id DESC LIMIT 1", (code, banner, since))
            if row and row["in_stock"]:
                out[banner] = row
        return out

    # ---------------------------------------------------------- linking
    def link(self, product_id: int) -> dict | None:
        """Match one staple product to the catalogue and record its prices; the match, or None."""
        p = self.staples.product(product_id)
        if not (self.enabled and p):
            return None
        staple = self.store.one("SELECT name FROM staples WHERE id=?", (p["staple_id"],))["name"]
        banner, sid = self.stores[0]
        cands = self.pcx.search(banner, sid, f"{p['label']} {staple}")
        best = pick(p["label"], staple, cands)
        with self.store.tx() as db:
            if best:
                c, s = best
                db.execute("UPDATE staple_products SET code=?, catalogue_name=?, brand=?, size=?, image=?, link=?,"
                           " confidence=?, linked_at=? WHERE id=?",
                           (c["code"], c["name"], c["brand"], c["size"], c["image"], c["link"], s, self._utc(), product_id))
            else:
                db.execute("UPDATE staple_products SET code=NULL, confidence=0, linked_at=? WHERE id=?",
                           (self._utc(), product_id))
        if not best:
            log.info("no catalogue match for %r (%s)", p["label"], staple)
            return None
        c = best[0]
        self.record(banner, c)
        for other, osid in self.stores[1:]:
            got = self.pcx.product(other, osid, c["code"])
            if got:
                self.record(other, got)
        return c

    def _link_all(self, product_ids: list[int]):
        for pid in product_ids:
            try:
                self.link(pid)
            except PcxBlocked as e:
                self._blocked(str(e))
                return
            except PcxError as e:
                log.warning("couldn't match product %s yet: %s", pid, e)   # retried at the next refresh
            except Exception:
                log.exception("matching product %s failed", pid)

    # ---------------------------------------------------------- picking for plain items
    def _needs_pick(self, items: list[dict]) -> list[int]:
        """Open items at a Loblaw store with no product, unless nothing fitted their word this past week."""
        tried = self._get("prices.unpicked", {})
        since = (self.clock() - CATCH_UP).astimezone(timezone.utc).isoformat(timespec="seconds")
        return [i["id"] for i in items if not i.get("bought_at") and not i.get("product_id")
                and i.get("store") in STORE_BANNER and tried.get(norm(i["title"]), "") < since]

    def autopick(self, item_id: int) -> dict | None:
        """Pick a catalogue product for a plain item and price it; the pick, or None."""
        item = self.store.one("SELECT * FROM items WHERE id=?", (item_id,))
        if not (self.enabled and item) or item["product_id"]:
            return None
        banner, sid = self.stores[0]
        c = pick_plain(item["title"], self.pcx.search(banner, sid, item["title"]))
        if not c:
            tried = self._get("prices.unpicked", {})
            tried[norm(item["title"])] = self._utc()
            self._set("prices.unpicked", tried)
            log.info("nothing in the catalogue fits %r", item["title"])
            return None
        pid = self.staples.adopt(item_id, c)
        p = self.staples.product(pid)
        if p and p["code"] == c["code"]:
            self.record(banner, c)
            for other, osid in self.stores[1:]:
                got = self.pcx.product(other, osid, c["code"])
                if got:
                    self.record(other, got)
        log.info("picked %r for %r", c["name"], item["title"])
        return c

    def _work(self, product_ids: list[int], item_ids: list[int]):
        self._link_all(product_ids)
        for iid in item_ids:
            try:
                self.autopick(iid)
            except PcxBlocked as e:
                self._blocked(str(e))
                return
            except PcxError as e:
                log.warning("couldn't pick for item %s yet: %s", iid, e)
            except Exception:
                log.exception("picking for item %s failed", iid)

    def link_pending(self, items: list[dict], budget: float = LINK_BUDGET) -> None:
        """Match the never-tried products of items at a Loblaw store, and pick one
        for items without, waiting up to budget seconds; anything slower
        finishes in the background."""
        if not self.enabled or self._get("prices.status", {}).get("blocked"):
            return
        ids = list(dict.fromkeys(i["product_id"] for i in items if i.get("product_id") and i.get("store") in STORE_BANNER))
        todo = [pid for pid in ids if (p := self.staples.product(pid)) and not p["linked_at"]]
        picks = self._needs_pick(items)
        if not (todo or picks):
            return
        t = threading.Thread(target=self._work, args=(todo, picks), daemon=True, name="prices-link")
        t.start()
        t.join(budget)

    # ---------------------------------------------------------- refreshing
    def _codes(self, scope: str) -> list[str]:
        open_sql = ("SELECT DISTINCT sp.code FROM items i JOIN staple_products sp ON sp.id=i.product_id"
                    " WHERE i.bought_at IS NULL AND sp.code IS NOT NULL")
        codes = [r["code"] for r in self.store.all(open_sql)]
        if scope == "all":
            since = (self.clock() - RECENT).isoformat(timespec="seconds")
            codes += [r["code"] for r in self.store.all(
                "SELECT DISTINCT sp.code FROM items i JOIN staple_products sp ON sp.id=i.product_id"
                " WHERE i.bought_at>=? AND sp.code IS NOT NULL", (since,))]
            codes += [r["code"] for r in self.store.all(
                "SELECT DISTINCT sp.code FROM staples s JOIN staple_products sp ON sp.id=s.default_product_id"
                " WHERE sp.code IS NOT NULL")]
        return list(dict.fromkeys(codes))

    def refresh(self, scope: str = "all") -> dict:
        """Check every relevant product's price at every store. Returns counts."""
        if not self.enabled:
            return {"status": "off"}
        if not self._refresh_lock.acquire(blocking=False):
            return {"status": "busy"}
        self.running = True
        try:
            status = self._get("prices.status", {"blocked": None, "stores": {}})
            status["blocked"] = None   # a new attempt; set again if Loblaw still refuses
            self._set("prices.status", status)
            unlinked = [r["id"] for r in self.store.all(
                "SELECT DISTINCT sp.id FROM items i JOIN staple_products sp ON sp.id=i.product_id"
                " WHERE i.bought_at IS NULL AND sp.linked_at IS NULL AND i.store IN (%s)" % ",".join("?" * len(BANNERS)),
                tuple(BANNERS.values()))]
            self._work(unlinked, self._needs_pick(self.store.all("SELECT * FROM items WHERE bought_at IS NULL")))
            if self._get("prices.status", {}).get("blocked"):
                return {"status": "blocked", "why": self._get("prices.status")["blocked"]["why"]}
            codes = self._codes(scope)
            got = {b: 0 for b, _ in self.stores}
            failed = {b: "" for b, _ in self.stores}
            recent = (self.clock() - timedelta(minutes=30)).astimezone(timezone.utc).isoformat(timespec="seconds")
            for code in codes:
                for banner, sid in self.stores:
                    if self.store.one("SELECT 1 FROM price_obs WHERE code=? AND banner=? AND observed_at>=?",
                                      (code, banner, recent)):
                        got[banner] += 1   # just priced while matching or picking
                        continue
                    try:
                        p = self.pcx.product(banner, sid, code)
                    except PcxBlocked as e:
                        self._blocked(str(e))
                        return {"status": "blocked", "why": str(e)}
                    except PcxError as e:
                        failed[banner] = str(e)
                        continue
                    if p:
                        self.record(banner, p)
                        got[banner] += 1
            for banner, _ in self.stores:
                ok = not codes or got[banner] > 0
                self._note(banner, ok, "" if ok else failed[banner] or "no prices came back")
            self._set("prices.last_refresh", self._utc())
            if scope == "all":
                self._set("prices.last_full", self._utc())
            log.info("prices refreshed: %d products, %d stores (%s)", len(codes), len(self.stores),
                     ", ".join(f"{SHORT[b]} {n}" for b, n in got.items()))
            return {"status": "ok", "products": len(codes), "prices": sum(got.values())}
        finally:
            self.running = False
            self._refresh_lock.release()

    def start(self) -> dict:
        """The Shopping tab's Check prices: the list only, in the background, at most hourly."""
        if not self.enabled:
            raise TaskError(400, "Prices are off (no PCX_API_KEY or PCX_STORES).")
        last = self._get("prices.last_manual")
        if last:
            ago = self.clock() - datetime.fromisoformat(last)
            if ago < COOLDOWN:
                mins = max(1, int(ago.total_seconds() // 60))
                raise TaskError(429, f"Checked {mins} minute{'s' if mins != 1 else ''} ago; try again in "
                                     f"{int((COOLDOWN - ago).total_seconds() // 60) + 1} minutes.")
        if self.running:
            raise TaskError(409, "Already checking prices.")
        self._set("prices.last_manual", self._utc())
        n = len(self._codes("list")) + len(self._needs_pick(self.store.all("SELECT * FROM items WHERE bought_at IS NULL")))
        threading.Thread(target=self._safe_refresh, args=("list",), daemon=True, name="prices-refresh").start()
        return {"started": True, "products": n, "eta_seconds": round(n * len(self.stores) * (self.pcx.gap + 0.5))}

    def _safe_refresh(self, scope: str):
        try:
            self.refresh(scope)
        except Exception:
            log.exception("price refresh failed")

    async def run(self):
        """The weekly refresh, apart from the reminder tick so it can never delay one."""
        if not self.enabled:
            return
        status = self._get("prices.status", {"blocked": None, "stores": {}})
        if status.get("blocked"):   # a restart usually follows a new PCX_API_KEY: try again
            status["blocked"] = None
            self._set("prices.status", status)
        await asyncio.sleep(120)
        last = self._get("prices.last_full")
        if not last or self.clock() - datetime.fromisoformat(last) > CATCH_UP:
            await asyncio.to_thread(self._safe_refresh, "all")
        while True:
            now = self.clock()
            await asyncio.sleep(max(1.0, (next_slot(now, self.slot) - now).total_seconds()))
            await asyncio.to_thread(self._safe_refresh, "all")

    # ---------------------------------------------------------- the list's view
    def _store_quote(self, banner: str, row: dict) -> dict:
        return {"banner": banner, "store": BANNERS[banner], "short": SHORT[banner], "price_cents": row["price_cents"],
                "regular_cents": row["regular_cents"], "on_sale": bool(row["on_sale"]), "sale_ends": row["sale_ends"],
                "unit_cents": row["unit_cents"], "unit_qty": row["unit_qty"], "unit": row["unit"],
                "deal": {"type": row["deal_type"], "text": row["deal_text"], "ends": row["deal_ends"],
                         "multibuy": multibuy(row["deal_text"], row["deal_cents"])} if row["deal_type"] else None,
                "points": {"points": row["points"], "ends": row["points_ends"]} if row["points"] else None,
                "member_cents": row["member_cents"], "checked_at": row["observed_at"]}

    def view(self, items: list[dict]) -> dict:
        status = self._get("prices.status", {"blocked": None, "stores": {}})
        out = {"enabled": self.enabled, "running": self.running,
               "stores": [{"banner": b, "store": BANNERS[b], "short": SHORT[b]} for b, _ in self.stores],
               "items": {}, "pricable": 0, "priced": 0, "complete": 0, "totals": {}, "split_saving_cents": 0,
               "last_refresh": self._get("prices.last_refresh"), "status": status}
        if not self.enabled:
            return out
        totals = {b: 0 for b, _ in self.stores}
        split = 0
        for i in items:
            if i.get("bought_at") or i.get("store") not in STORE_BANNER:
                continue
            out["pricable"] += 1
            p = i.get("product") or {}
            if not p.get("code"):
                continue
            rows = self.latest(p["code"])
            if not rows:
                continue
            here = STORE_BANNER[i["store"]]
            best = min(rows, key=lambda b: (rows[b]["price_cents"], b != here))
            saving = rows[here]["price_cents"] - rows[best]["price_cents"] if here in rows else 0
            out["items"][str(i["id"])] = {
                "stores": [self._store_quote(b, rows[b]) for b in sorted(rows, key=lambda b: rows[b]["price_cents"])],
                "cheapest": best, "here": here if here in rows else None,
                "saving_cents": max(0, saving), "move_to": BANNERS[best] if saving > 0 else None}
            out["priced"] += 1
            if len(rows) == len(self.stores):
                out["complete"] += 1
                for b in rows:
                    totals[b] += rows[b]["price_cents"]
                split += rows[best]["price_cents"]
        if out["complete"]:
            out["totals"] = totals
            saving = min(totals.values()) - split
            out["split_saving_cents"] = saving if saving >= self.split_min_cents else 0
        return out
