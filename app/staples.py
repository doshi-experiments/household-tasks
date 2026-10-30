"""Staples: the product the household means by each of its usual words.

Naming a product once teaches it: an item added as "milk" with product
"Natrel 2%" makes Natrel 2% the usual milk, and plain "milk" means it from
then on. Words match whatever their case, accents, plural or small typo
("MILK", "Mlik", "bana ganush" for babaganoush). Naming a different product
later puts that one on the item only and asks (via the caller) whether it
should become the usual. Tested in tests/test_staples.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from .aisles import _words
from .store import Store
from .tasks import TaskError


def _stem(w: str) -> str:
    """A key a word's singular and plural share ("berry"/"berries",
    "cheese"/"cheeses", "tomato"/"tomatoes"). Only ever compared, never shown."""
    if len(w) <= 3 or w.endswith(("ss", "us", "is")):
        return w
    if w.endswith("ies"):
        return w[:-3] + "i"
    if w.endswith("y"):
        return w[:-1] + "i"
    for suffix in ("es", "s", "e"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[:-len(suffix)]
    return w


def norm(text: str) -> str:
    """Case, accents, punctuation, spacing and plurals folded away: "Milks!",
    "milk" and "MILK" are all "milk"; "Natrel 2 %" and "natrel 2%" match."""
    return " ".join(_stem(w) for w in _words(text))


def distance(a: str, b: str) -> int:
    """Edits between a and b, a swap of neighbours counting as one ("mlik" is
    one edit from "milk")."""
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def allowed_edits(n: int) -> int:
    """Typos forgiven for a word this long: none up to 3 letters, one up to 5, two beyond."""
    return 0 if n <= 3 else 1 if n <= 5 else 2


def closest(key: str, names: dict[str, int]) -> int | None:
    """The id whose normalized name is within the typos allowed of key (spaces
    ignored, same first letter), or None when nothing is, or two are equally close."""
    flat = key.replace(" ", "")
    best, tie, best_d = None, False, None
    for name, sid in names.items():
        other = name.replace(" ", "")
        if not flat or not other or flat[0] != other[0]:
            continue
        d = distance(flat, other)
        if d > allowed_edits(min(len(flat), len(other))):
            continue
        if best_d is None or d < best_d:
            best, tie, best_d = sid, False, d
        elif d == best_d and sid != best:
            tie = True
    return None if tie else best


class Staples:
    def __init__(self, store: Store, clock: Callable[[], datetime]):
        self.store, self.clock = store, clock

    def _now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    # ------------------------------------------------------------ reads
    def all(self) -> list[dict]:
        staples = self.store.all("SELECT * FROM staples ORDER BY lower(name)")
        products = self.store.all("SELECT * FROM staple_products ORDER BY id")
        for s in staples:
            s["products"] = [p for p in products if p["staple_id"] == s["id"]]
            s["usual"] = next((p for p in s["products"] if p["id"] == s["default_product_id"]), None)
        return staples

    def find(self, db, title: str) -> tuple[dict | None, bool]:
        """The staple a title names and whether it was read as a near miss."""
        key = norm(title)
        if not key:
            return None, False
        hit = db.execute("SELECT * FROM staples WHERE norm=?", (key,)).fetchone()
        if hit:
            return dict(hit), False
        names = {r["norm"]: r["id"] for r in db.execute("SELECT id, norm FROM staples")}
        sid = closest(key, names)
        if sid is None:
            return None, False
        return dict(db.execute("SELECT * FROM staples WHERE id=?", (sid,)).fetchone()), True

    def product(self, product_id: int | None) -> dict | None:
        return self.store.one("SELECT * FROM staple_products WHERE id=?", (product_id,)) if product_id else None

    @staticmethod
    def view(p: dict | None) -> dict | None:
        """What an item shows of its product."""
        if not p:
            return None
        return {"id": p["id"], "label": p["label"], "code": p["code"], "catalogue_name": p["catalogue_name"],
                "size": p["size"], "linked": bool(p["code"]), "tried": bool(p["linked_at"])}

    def decorate(self, rows: list[dict]) -> list[dict]:
        """Items with their staple's name and product attached."""
        ids = {r.get("product_id") for r in rows if r.get("product_id")}
        sids = {r.get("staple_id") for r in rows if r.get("staple_id")}
        products = {p["id"]: p for p in self.store.all(
            f"SELECT * FROM staple_products WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))} if ids else {}
        names = {s["id"]: s["name"] for s in self.store.all(
            f"SELECT id, name FROM staples WHERE id IN ({','.join('?' * len(sids))})", tuple(sids))} if sids else {}
        return [{**r, "staple": names.get(r.get("staple_id")), "product": self.view(products.get(r.get("product_id")))}
                for r in rows]

    # ------------------------------------------------------------ writes (inside the caller's transaction)
    def _product_for(self, db, staple_id: int, label: str) -> int:
        """The staple's product with this label (the same once normalized), made if new."""
        key = norm(label)
        hit = db.execute("SELECT id FROM staple_products WHERE staple_id=? AND norm_label=?", (staple_id, key)).fetchone()
        if hit:
            return hit[0]
        cur = db.execute("INSERT INTO staple_products(staple_id, label, norm_label, created_at) VALUES (?,?,?,?)",
                         (staple_id, label.strip()[:80], key, self._now()))
        return cur.lastrowid

    def _staple_for(self, db, title: str) -> dict:
        now = self._now()
        cur = db.execute("INSERT INTO staples(name, norm, created_at, updated_at) VALUES (?,?,?,?)",
                         (title.strip()[:80], norm(title), now, now))
        return dict(db.execute("SELECT * FROM staples WHERE id=?", (cur.lastrowid,)).fetchone())

    def _set_usual(self, db, staple_id: int, product_id: int):
        db.execute("UPDATE staples SET default_product_id=?, updated_at=? WHERE id=?", (product_id, self._now(), staple_id))

    def resolve(self, db, title: str, product: str = "") -> dict:
        """What an item added as title (and maybe a named product) becomes:
        {title, staple_id, product_id, read_as, learned, ask_usual}."""
        product = str(product or "").strip()
        out = {"title": title, "staple_id": None, "product_id": None, "read_as": None,
               "learned": False, "ask_usual": None}
        if product and not norm(product):
            product = ""
        staple, fuzzy = self.find(db, title)
        if fuzzy:
            out["title"], out["read_as"] = staple["name"], title
        if not staple:
            if not product:
                return out
            staple = self._staple_for(db, title)
        out["staple_id"] = staple["id"]
        usual = staple["default_product_id"]
        if not product:
            out["product_id"] = usual
            return out
        pid = self._product_for(db, staple["id"], product)
        out["product_id"] = pid
        if not usual:
            self._set_usual(db, staple["id"], pid)
            out["learned"] = True
        elif pid != usual:
            cur = db.execute("SELECT label FROM staple_products WHERE id=?", (usual,)).fetchone()[0]
            out["ask_usual"] = {"staple_id": staple["id"], "product_id": pid, "staple": staple["name"],
                                "current": cur, "new": product}
        return out

    # ------------------------------------------------------------ corrections and choices
    def set_product(self, item_id: int, product: str) -> dict:
        """A correction ("no, Dairyland 4L"). An item on the usual product (or
        the one that just taught it) changes the usual too; an item that was a
        deliberate one-off changes alone. An item with no staple teaches one."""
        product = str(product or "").strip()
        if not norm(product):
            raise TaskError(400, "Say which product.")
        with self.store.tx() as db:
            item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not item:
                raise TaskError(404, f"No item {item_id}.")
            item = dict(item)
            staple = None
            if item["staple_id"]:
                row = db.execute("SELECT * FROM staples WHERE id=?", (item["staple_id"],)).fetchone()
                staple = dict(row) if row else None
            if not staple:
                staple, _ = self.find(db, item["title"])
            if not staple:
                staple = self._staple_for(db, item["title"])
            pid = self._product_for(db, staple["id"], product)
            usual_changed = not staple["default_product_id"] or item["product_id"] in (None, staple["default_product_id"])
            if usual_changed:
                self._set_usual(db, staple["id"], pid)
            db.execute("UPDATE items SET staple_id=?, product_id=?, updated_at=? WHERE id=?",
                       (staple["id"], pid, self._now(), item_id))
            row = dict(db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())
        return {**self.decorate([row])[0], "usual_changed": usual_changed}

    def settle(self, item: dict) -> dict:
        """After catalogue matching: a named product that turned out to be the
        usual one (the same Loblaw code, "natrel 2% milk 4l" for "Natrel 2%")
        is the usual, so there's nothing to ask."""
        ask = item.get("ask_usual")
        if not ask:
            return item
        new = self.product(ask["product_id"])
        staple = self.store.one("SELECT default_product_id FROM staples WHERE id=?", (ask["staple_id"],))
        usual = self.product(staple and staple["default_product_id"])
        if not (new and usual and new["code"] and new["code"] == usual["code"]):
            return item
        with self.store.tx() as db:
            db.execute("UPDATE items SET product_id=? WHERE id=?", (usual["id"], item["id"]))
        return {**item, "product_id": usual["id"], "product": self.view(usual), "ask_usual": None}

    def make_usual(self, staple_id: int, product_id: int) -> dict:
        with self.store.tx() as db:
            ok = db.execute("SELECT 1 FROM staple_products WHERE id=? AND staple_id=?", (product_id, staple_id)).fetchone()
            if not ok:
                raise TaskError(404, "That product isn't one of this staple's.")
            self._set_usual(db, staple_id, product_id)
        return next(s for s in self.all() if s["id"] == staple_id)
