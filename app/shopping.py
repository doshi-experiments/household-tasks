"""Shopping lists and their items, plus the shared list/category management."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from .store import Store
from .tasks import TaskError

KEEP_BOUGHT_DAYS = 90


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
        if not found or found["archived"]:
            raise TaskError(400, f"No shopping list {name!r}.")
        return found["name"]

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
                dup = db.execute("SELECT * FROM items WHERE bought_at IS NULL AND list=? AND lower(title)=lower(?)",
                                 (lst, title)).fetchone()
                if dup:
                    out.append({**dict(dup), "duplicate": True})
                    continue
                pos = db.execute("SELECT coalesce(max(position),0)+1 FROM items WHERE list=?", (lst,)).fetchone()[0]
                cur = db.execute("INSERT INTO items(title, list, notes, added_by, position, source, created_at, updated_at)"
                                 " VALUES (?,?,?,?,?,?,?,?)",
                                 (title[:200], lst, str(it.get("notes") or ""), str(it.get("added_by") or ""), pos,
                                  str(it.get("source") or ""), now, now))
                out.append({**dict(db.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone()),
                            "duplicate": False})
        return out

    def patch(self, item_id: int, body: dict) -> dict:
        self.get(item_id)
        updates = {}
        if "title" in body and str(body["title"] or "").strip():
            updates["title"] = str(body["title"]).strip()[:200]
        if "notes" in body:
            updates["notes"] = str(body["notes"] or "")
        if "list" in body:
            updates["list"] = self._list(body["list"])
        if not updates:
            return self.get(item_id)
        updates["updated_at"] = self._now()
        with self.store.tx() as db:
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
