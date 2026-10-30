"""SQLite storage. One connection, every access under one re-entrant lock."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from . import aisles

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS categories (
  name TEXT PRIMARY KEY, sort INTEGER NOT NULL DEFAULT 0, hint TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS shopping_lists (
  name TEXT PRIMARY KEY, sort INTEGER NOT NULL DEFAULT 0, hint TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  list TEXT NOT NULL REFERENCES shopping_lists(name) ON UPDATE CASCADE,
  notes TEXT NOT NULL DEFAULT '',
  added_by TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  bought_at TEXT, bought_by TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_items_open ON items(bought_at, list, position);
CREATE TABLE IF NOT EXISTS stores (
  name TEXT PRIMARY KEY, sort INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'Inbox' REFERENCES categories(name) ON UPDATE CASCADE,
  priority INTEGER NOT NULL DEFAULT 2 CHECK (priority BETWEEN 0 AND 3),
  assignee TEXT,
  schedule_kind TEXT NOT NULL DEFAULT 'none' CHECK (schedule_kind IN ('none','rrule','interval')),
  rrule TEXT,
  anchor_date TEXT,
  interval_n INTEGER,
  interval_unit TEXT CHECK (interval_unit IS NULL OR interval_unit IN ('days','weeks','months','years')),
  flex TEXT NOT NULL DEFAULT 'exact' CHECK (flex IN ('exact','weekend')),
  due_time TEXT,
  cursor TEXT,
  nominal_due TEXT,
  due TEXT,
  snoozed_until TEXT,
  last_done_at TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','archived')),
  source TEXT NOT NULL DEFAULT '',
  added_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_tasks_open_due ON tasks(status, due);
CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source);
CREATE TABLE IF NOT EXISTS completions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  kind TEXT NOT NULL CHECK (kind IN ('done','skip')),
  done_at TEXT NOT NULL,
  nominal_due TEXT,
  done_by TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  undo TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_completions_task ON completions(task_id, done_at);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL,
  bucket TEXT NOT NULL,
  channel TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  ok INTEGER NOT NULL DEFAULT 1,
  detail TEXT NOT NULL DEFAULT '',
  UNIQUE (task_id, kind, bucket, channel));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS voice_lines (
  day TEXT NOT NULL, task_id INTEGER NOT NULL, kind TEXT NOT NULL, step INTEGER NOT NULL, text TEXT NOT NULL,
  PRIMARY KEY (day, task_id, kind, step));
CREATE TABLE IF NOT EXISTS telegram_messages (
  message_id INTEGER PRIMARY KEY, kind TEXT, bucket TEXT, task_ids TEXT, sent_at TEXT, buttons TEXT);
CREATE TABLE IF NOT EXISTS staples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, norm TEXT NOT NULL UNIQUE,
  default_product_id INTEGER,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staple_products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  staple_id INTEGER NOT NULL REFERENCES staples(id) ON DELETE CASCADE,
  label TEXT NOT NULL, norm_label TEXT NOT NULL,
  code TEXT, catalogue_name TEXT, brand TEXT, size TEXT, image TEXT, link TEXT,
  confidence REAL, linked_at TEXT, auto INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE (staple_id, norm_label));
CREATE TABLE IF NOT EXISTS price_obs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL, banner TEXT NOT NULL, observed_at TEXT NOT NULL,
  price_cents INTEGER, regular_cents INTEGER, unit_cents INTEGER, unit_qty REAL, unit TEXT,
  on_sale INTEGER NOT NULL DEFAULT 0, sale_ends TEXT,
  deal_type TEXT, deal_text TEXT, deal_cents INTEGER, deal_ends TEXT,
  points INTEGER, points_ends TEXT, member_cents INTEGER,
  in_stock INTEGER NOT NULL DEFAULT 1, suspect INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_price_obs ON price_obs(code, banner, observed_at);
"""

CATEGORIES = [
    ("Repairs & Maintenance", "Fixing things, servicing appliances, filters, gutters, the car"),
    ("Installs & Setup", "New things to install, mount, assemble or set up"),
    ("Cleaning & Recycling", "Cleaning, tidying, decluttering, recycling and garbage runs"),
    ("Yard & Garden", "Weeding, mowing, plants, watering, the yard and garden"),
    ("Dogs", "The dogs: meds, grooming, vet, food"),
    ("Errands & Admin", "Appointments, paperwork, calls, address changes, pick-ups"),
    ("Finances", "Bills, account checks, taxes, statements"),
    ("Inbox", "Anything that doesn't fit elsewhere yet"),
]
# Homelab projects: software to build, update or host. These never remind anyone.
HOMELAB_PROJECTS = [
    ("Home Assistant", "Automations, dashboards, scripts, integrations and voice in Home Assistant"),
    ("Tasks app", "This tasks service: its pages, reminders, schedules and integrations"),
    ("Ingest bot", "The Telegram bot: what it understands, its lists and its replies"),
    ("Portfolio site", "The personal website and portfolio"),
    ("Infrastructure", "Docker hosts, containers, networking, Tailscale, backups, updates and security"),
    ("New projects", "Ideas for new apps or services to build or self-host"),
]
SHOPPING_LISTS = [
    ("Groceries", "Everything we need to buy, from any store"),
]
# Seed stores (the default and each category's usual one); anyone naming a
# new store on an item adds it on the fly.
STORES = ["Real Canadian Superstore", "Costco", "Home Depot", "IKEA", "Best Buy"]


class Store:
    def __init__(self, path: str):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        with self.tx():
            for i, (name, hint) in enumerate(CATEGORIES):
                self.db.execute("INSERT OR IGNORE INTO categories(name, sort, hint) VALUES (?,?,?)", (name, i, hint))
            for i, (name, hint) in enumerate(HOMELAB_PROJECTS, 100):
                self.db.execute("INSERT OR IGNORE INTO categories(name, sort, hint, area) VALUES (?,?,?,'homelab')",
                                (name, i, hint))
            for i, (name, hint) in enumerate(SHOPPING_LISTS):
                self.db.execute("INSERT OR IGNORE INTO shopping_lists(name, sort, hint) VALUES (?,?,?)", (name, i, hint))
            for i, name in enumerate(STORES):
                self.db.execute("INSERT OR IGNORE INTO stores(name, sort) VALUES (?,?)", (name, i))

    def _migrate(self):
        """2026-10-19: priorities are High/Medium/Low (1-3) plus an alarm flag
        (the old P0 = High + alarm), and the board keeps a manual order.
        2026-10-19: tasks belong to an area (household, or homelab with a
        progress stage); a category's area decides its tasks' area.
        2026-10-24: a completion keeps the task fields it changed (JSON), so the
        newest done or skip can be undone.
        2026-10-25: one shopping list; Everything Else merges into Groceries
        (its items categorised Other) and items carry category, store and aisle.
        2026-10-26: a Telegram message keeps the buttons it still offers (JSON), so
        a task closed elsewhere can be taken off it.
        2026-10-26: a task can nag (repeat its reminder every N minutes on the day
        it's due) and escalate (critical pushes to more people from a set time).
        2026-10-27: voice_lines (a new table, so CREATE IF NOT EXISTS covers it)
        holds the day's HA-written reminder lines for one-off tasks.
        2026-10-29 (user_version 1): items that took the defaults get the
        category, store and aisle their title implies (_fill_aisles).
        2026-10-29: staples, staple_products and price_obs (new tables, so
        CREATE IF NOT EXISTS covers them); an item points at its staple and
        product (staple_id, product_id; NULL for a plain item).
        2026-10-29: staple_products.auto marks a product Tasks picked itself
        from the catalogue for a word nobody had named a product for."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}
        tg_cols = {r[1] for r in self.db.execute("PRAGMA table_info(telegram_messages)")}
        cat_cols = {r[1] for r in self.db.execute("PRAGMA table_info(categories)")}
        done_cols = {r[1] for r in self.db.execute("PRAGMA table_info(completions)")}
        item_cols = {r[1] for r in self.db.execute("PRAGMA table_info(items)")}
        with self.tx() as db:
            if "buttons" not in tg_cols:
                db.execute("ALTER TABLE telegram_messages ADD COLUMN buttons TEXT")
            if "undo" not in done_cols:
                db.execute("ALTER TABLE completions ADD COLUMN undo TEXT NOT NULL DEFAULT ''")
            if "area" not in cat_cols:
                db.execute("ALTER TABLE categories ADD COLUMN area TEXT NOT NULL DEFAULT 'household'")
            if "area" not in cols:
                db.execute("ALTER TABLE tasks ADD COLUMN area TEXT NOT NULL DEFAULT 'household'")
                db.execute("ALTER TABLE tasks ADD COLUMN stage TEXT")
            if "alarm" not in cols:
                db.execute("ALTER TABLE tasks ADD COLUMN alarm INTEGER NOT NULL DEFAULT 0")
                db.execute("UPDATE tasks SET alarm=1, priority=1 WHERE priority=0")
            if "position" not in cols:
                db.execute("ALTER TABLE tasks ADD COLUMN position REAL")
                rows = db.execute("SELECT id FROM tasks ORDER BY priority, coalesce(due, '9999'), lower(title)").fetchall()
                for i, (tid,) in enumerate(rows, 1):
                    db.execute("UPDATE tasks SET position=? WHERE id=?", (i * 1024.0, tid))
            if "nag_every" not in cols:
                db.execute("ALTER TABLE tasks ADD COLUMN nag_every INTEGER")
                db.execute("ALTER TABLE tasks ADD COLUMN escalate_at TEXT")
                db.execute("ALTER TABLE tasks ADD COLUMN escalate_every INTEGER")
                db.execute("ALTER TABLE tasks ADD COLUMN escalate_to TEXT NOT NULL DEFAULT ''")
            if "category" not in item_cols:
                db.execute("ALTER TABLE items ADD COLUMN category TEXT NOT NULL DEFAULT 'Groceries'")
                db.execute("ALTER TABLE items ADD COLUMN store TEXT NOT NULL DEFAULT 'Real Canadian Superstore'")
                db.execute("ALTER TABLE items ADD COLUMN aisle TEXT NOT NULL DEFAULT ''")
                db.execute("UPDATE items SET category='Other' WHERE list='Everything Else'")
                off = db.execute("SELECT coalesce(max(position),0) FROM items WHERE list='Groceries'").fetchone()[0]
                db.execute("UPDATE items SET list='Groceries', position=position+? WHERE list='Everything Else'", (off,))
                db.execute("UPDATE shopping_lists SET archived=1 WHERE name='Everything Else'")
                db.execute("UPDATE shopping_lists SET hint='Everything we need to buy, from any store'"
                           " WHERE name='Groceries'")
            if "staple_id" not in item_cols:
                db.execute("ALTER TABLE items ADD COLUMN staple_id INTEGER")
                db.execute("ALTER TABLE items ADD COLUMN product_id INTEGER")
            if "auto" not in {r[1] for r in db.execute("PRAGMA table_info(staple_products)")}:
                db.execute("ALTER TABLE staple_products ADD COLUMN auto INTEGER NOT NULL DEFAULT 0")
            if db.execute("PRAGMA user_version").fetchone()[0] < 1:
                self._fill_aisles(db)
                db.execute("PRAGMA user_version=1")

    @staticmethod
    def _fill_aisles(db):
        """Once: until 2026-10-29 nothing set an aisle and every item without a
        named store went to the default one. Re-read each title: a Groceries or
        Other item takes the category its title implies, an item at the default
        store moves to that category's store, and a blank aisle is filled in.
        A category, store or aisle someone chose (anything else) is kept."""
        for i, name in enumerate(STORES):
            db.execute("INSERT OR IGNORE INTO stores(name, sort) VALUES (?,?)", (name, i))
        rows = db.execute("SELECT id, title, category, store, aisle FROM items").fetchall()
        for item_id, title, category, store, aisle in rows:
            dept = aisles.classify(title)
            if not dept:
                continue
            if category in ("Groceries", "Other"):
                category = aisles.category_of(dept)
            if store == aisles.DEFAULT_STORE:
                store = aisles.store_for(category)
            aisle = aisle or aisles.aisle_for(dept, store)
            db.execute("UPDATE items SET category=?, store=?, aisle=? WHERE id=?", (category, store, aisle, item_id))

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    def all(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
            return dict(r) if r else None

    def close(self):
        with self.lock:
            self.db.close()
