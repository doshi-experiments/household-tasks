"""Shopping lists and their items, plus the shared list/category management."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from .store import Store
from .tasks import TaskError

KEEP_BOUGHT_DAYS = 90

# Every item carries a category (groceries or not), a store and an aisle.
# Unknown categories coerce to Other; unknown stores are created on the fly
# ("buy tarp from home depot" via the bot adds Home Depot); unknown aisles
# coerce to '' against the item's store.
ITEM_CATEGORIES = ["Groceries", "Home Improvement", "Pharmacy & Health", "Pet Supplies", "Electronics", "Other"]
DEFAULT_CATEGORY = "Groceries"
DEFAULT_STORE = "Real Canadian Superstore"
AISLES = {
    "Real Canadian Superstore": ["Produce", "Bakery", "Deli", "Dairy & Eggs", "Meat & Seafood", "Frozen",
                                 "Pantry", "Snacks", "Beverages", "Health & Beauty", "Household", "Other"],
    "Costco": ["Produce", "Bakery", "Deli & Prepared", "Dairy", "Meat & Seafood", "Frozen", "Pantry & Snacks",
               "Beverages", "Health & Beauty", "Household", "Electronics", "Clothing", "Other"],
}
DEFAULT_AISLES = ["Food", "Household", "Health", "Other"]


def aisles_for(store: str) -> list[str]:
    return AISLES.get(store, DEFAULT_AISLES)


class Lists:
    """Named lists in one table (categories or shopping_lists)."""

    def __init__(self, store: Store, table: str, member_table: str, member_col: str, open_sql: str):
        self.store, self.table = store, table
        self.member_table, self.member_col, self.open_sql = member_table, member_col, open_sql

    def all(self, include_archived=False) -> list[dict]:
        sql = f"SELECT * FROM {self.table}" + ("" if include_archived else " WHERE archived=0") + " ORDER BY sort, name"
        return self.store.all(sql)

    def find(self, name: str) -> dict | None:
        return self.store.one(f"SELECT * FROM {self.table} WHERE lower(name)=lower(?)", ((name or "").strip(),))

    def create(self, name: str, hint: str = "", area: str | None = None) -> dict:
        """area (categories only): household (the default) or homelab."""
        name = (name or "").strip()
        if not name or "/" in name:
            raise TaskError(400, "A list name can't be empty or contain '/'.")
        if area not in (None, "", "household", "homelab"):
            raise TaskError(400, "Area is household or homelab.")
        found = self.find(name)
        if found and not found["archived"]:
            raise TaskError(409, f"{found['name']} already exists.")
        with self.store.tx() as db:
            if found:
                db.execute(f"UPDATE {self.table} SET archived=0 WHERE name=?", (found["name"],))
            else:
                top = db.execute(f"SELECT coalesce(max(sort),0)+1 FROM {self.table}").fetchone()[0]
                db.execute(f"INSERT INTO {self.table}(name, sort, hint) VALUES (?,?,?)", (name, top, hint or ""))
            if area:
                db.execute(f"UPDATE {self.table} SET area=? WHERE name=?", (area, found["name"] if found else name))
        return self.find(name)

    def update(self, name: str, new_name: str | None = None, hint: str | None = None) -> dict:
        found = self.find(name)
        if not found:
            raise TaskError(404, f"No list {name!r}.")
        with self.store.tx() as db:
            if hint is not None:
                db.execute(f"UPDATE {self.table} SET hint=? WHERE name=?", (hint, found["name"]))
            if new_name and new_name.strip() != found["name"]:
                new_name = new_name.strip()
                if "/" in new_name or self.find(new_name):
                    raise TaskError(409, f"Can't rename to {new_name!r}.")
                db.execute(f"UPDATE {self.table} SET name=? WHERE name=?", (new_name, found["name"]))
                found["name"] = new_name
        return self.find(found["name"])

    def archive(self, name: str) -> dict:
        found = self.find(name)
        if not found:
            raise TaskError(404, f"No list {name!r}.")
        n = self.store.one(f"SELECT count(*) AS n FROM {self.member_table} WHERE {self.member_col}=? AND {self.open_sql}",
                           (found["name"],))["n"]
        if n:
            raise TaskError(409, f"{found['name']} still has {n} open {'item' if n == 1 else 'items'}; move or finish them first.")
        with self.store.tx() as db:
            db.execute(f"UPDATE {self.table} SET archived=1 WHERE name=?", (found["name"],))
        return self.find(found["name"])


class Shopping:
    def __init__(self, store: Store, clock: Callable[[], datetime]):
        self.store, self.clock = store, clock
        self.lists = Lists(store, "shopping_lists", "items", "list", "bought_at IS NULL")

    def _now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    def _list(self, name) -> str:
        found = self.lists.find(name or "Groceries")
        if not found:
            raise TaskError(400, f"No shopping list {name!r}.")
        if found["archived"]:
            # A stale caller (the bot caches lists for a minute) naming an
            # archived list lands on the default list instead of failing.
            return self.lists.find("Groceries")["name"]
        return found["name"]

    def stores(self) -> list[dict]:
        return self.store.all("SELECT * FROM stores WHERE archived=0 ORDER BY sort, name")

    @staticmethod
    def _category(value) -> str:
        v = str(value or "").strip()
        if not v:
            return DEFAULT_CATEGORY
        return next((c for c in ITEM_CATEGORIES if c.lower() == v.lower()), "Other")

    def _store(self, db, value) -> str:
        """The matching store's name, creating the store when it's new."""
        v = str(value or "").strip()[:60]
        if not v:
            return DEFAULT_STORE
        hit = db.execute("SELECT name FROM stores WHERE lower(name)=lower(?)", (v,)).fetchone()
        if hit:
            return hit[0]
        top = db.execute("SELECT coalesce(max(sort),0)+1 FROM stores").fetchone()[0]
        db.execute("INSERT INTO stores(name, sort) VALUES (?,?)", (v, top))
        return v

    @staticmethod
    def _aisle(value, store: str) -> str:
        v = str(value or "").strip()
        return next((a for a in aisles_for(store) if a.lower() == v.lower()), "")

    def get(self, item_id: int) -> dict:
        row = self.store.one("SELECT * FROM items WHERE id=?", (item_id,))
        if not row:
            raise TaskError(404, f"No item {item_id}.")
        return row

    def items(self, list_name: str | None = None, bought: bool = False) -> list[dict]:
        sql = "SELECT * FROM items WHERE bought_at IS " + ("NOT NULL" if bought else "NULL")
        args = []
        if list_name:
            sql += " AND lower(list)=lower(?)"
            args.append(list_name)
        sql += " ORDER BY bought_at DESC" if bought else " ORDER BY list, position, id"
        return self.store.all(sql, args)

    def add(self, items: list[dict]) -> list[dict]:
        """Add items; an identical unbought item on the same list is returned instead of duplicated."""
        out = []
        now = self._now()
        with self.store.tx() as db:
            for it in items:
                title = str(it.get("title") or "").strip()
                if not title:
                    continue
                lst = self._list(it.get("list"))
                store = self._store(db, it.get("store"))
                dup = db.execute("SELECT * FROM items WHERE bought_at IS NULL AND list=? AND store=?"
                                 " AND lower(title)=lower(?)", (lst, store, title)).fetchone()
                if dup:
                    out.append({**dict(dup), "duplicate": True})
                    continue
                pos = db.execute("SELECT coalesce(max(position),0)+1 FROM items WHERE list=?", (lst,)).fetchone()[0]
                cur = db.execute("INSERT INTO items(title, list, notes, added_by, position, source, created_at,"
                                 " updated_at, category, store, aisle) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (title[:200], lst, str(it.get("notes") or ""), str(it.get("added_by") or ""), pos,
                                  str(it.get("source") or ""), now, now, self._category(it.get("category")), store,
                                  self._aisle(it.get("aisle"), store)))
                out.append({**dict(db.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone()),
                            "duplicate": False})
        return out

    def patch(self, item_id: int, body: dict) -> dict:
        row = self.get(item_id)
        updates = {}
        if "title" in body and str(body["title"] or "").strip():
            updates["title"] = str(body["title"]).strip()[:200]
        if "notes" in body:
            updates["notes"] = str(body["notes"] or "")
        if "list" in body:
            updates["list"] = self._list(body["list"])
        if "category" in body:
            updates["category"] = self._category(body["category"])
        with self.store.tx() as db:
            store = row["store"]
            if "store" in body:
                store = self._store(db, body["store"])
                updates["store"] = store
            if "aisle" in body:
                updates["aisle"] = self._aisle(body["aisle"], store)
            elif store != row["store"] and self._aisle(row["aisle"], store) != row["aisle"]:
                updates["aisle"] = ""   # the old aisle isn't one of the new store's
            if not updates:
                return row
            updates["updated_at"] = self._now()
            db.execute(f"UPDATE items SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), item_id))
        return self.get(item_id)

    def buy(self, item_id: int, by: str = "") -> dict:
        row = self.get(item_id)
        if row["bought_at"]:
            raise TaskError(409, "already bought", row)
        with self.store.tx() as db:
            db.execute("UPDATE items SET bought_at=?, bought_by=?, updated_at=? WHERE id=?",
                       (self._now(), by or "", self._now(), item_id))
        return self.get(item_id)

    def unbuy(self, item_id: int) -> dict:
        self.get(item_id)
        with self.store.tx() as db:
            db.execute("UPDATE items SET bought_at=NULL, bought_by='', updated_at=? WHERE id=?", (self._now(), item_id))
        return self.get(item_id)

    def delete(self, item_id: int) -> dict:
        row = self.get(item_id)
        with self.store.tx() as db:
            db.execute("DELETE FROM items WHERE id=?", (item_id,))
        return row

    def reorder(self, list_name: str, ids: list[int]) -> list[dict]:
        lst = self._list(list_name)
        with self.store.tx() as db:
            for pos, item_id in enumerate(ids, 1):
                db.execute("UPDATE items SET position=? WHERE id=? AND list=?", (pos, int(item_id), lst))
        return self.items(lst)

    def prune(self) -> int:
        cutoff = (self.clock() - timedelta(days=KEEP_BOUGHT_DAYS)).isoformat(timespec="seconds")
        with self.store.tx() as db:
            return db.execute("DELETE FROM items WHERE bought_at IS NOT NULL AND bought_at < ?", (cutoff,)).rowcount
