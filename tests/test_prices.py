"""Loblaw prices: parsing, catalogue matching, the refresh, the list's quotes and the API.

Offline: the PC Express client runs against httpx.MockTransport, the service
against a fake client. Products, codes and store ids are invented.
Run in the image: python -m unittest discover tests
"""
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.config import Config, Person
from app.pcx import Pcx, PcxBlocked, parse_product
from app.prices import Prices, multibuy, next_slot, parse_slot, pick, pick_plain, size_of
from app.shopping import Shopping
from app.store import Store
from app.tasks import TaskError

TZ = ZoneInfo("UTC")
TOKEN = "t" * 32
STORES = (("superstore", "1001"), ("nofrills", "2002"))


def raw(code, name, brand, size, price, *, was=None, ends=None, unit=(0.15, 100, "ml"), deal=None, deal_price=None,
        points=None, stock="OK"):
    """A product as the search endpoint returns it (the fields we read)."""
    badges = {"dealBadge": None, "loyaltyBadge": None}
    if deal:
        badges["dealBadge"] = {"type": deal[0], "text": deal[1], "expiryDate": "2026-10-28T00:00:00Z"}
    if points:
        badges["loyaltyBadge"] = {"type": "LOYALTY", "text": "PC Optimum Offer", "points": points,
                                  "expiryDate": "2026-10-28T23:59:59Z"}
    return {"code": code, "name": name, "brand": brand, "packageSize": size, "stockStatus": stock,
            "dealPrice": deal_price, "badges": badges, "link": f"/p/{code}",
            "imageAssets": [{"mediumUrl": f"https://img.example/{code}.png"}],
            "prices": {"price": {"value": price, "type": "SPECIAL" if ends else "REGULAR",
                                 "expiryDate": f"{ends}T00:00" if ends else "9999-12-31T00:00"},
                       "wasPrice": {"value": was, "type": "WAS"} if was else None,
                       "comparisonPrices": [{"value": unit[0], "quantity": unit[1], "unit": unit[2]}],
                       "memberOnlyPrice": None}}


def as_detail(p: dict) -> dict:
    """The same product as the lookup by code returns it (prices and badges in offers[0])."""
    offer = {**p["prices"], "badges": p["badges"], "stockStatus": p["stockStatus"]}
    return {k: v for k, v in p.items() if k not in ("prices", "badges", "stockStatus", "dealPrice")} | {"offers": [offer]}


MILK_A = raw("1001_EA", "2% Regular Milk", "Valley Farm", "4 l", 5.81)
MILK_B = raw("1002_EA", "Natrel Fine-Filtered 2% Milk", "Natrel", "4 l", 6.29)
MILK_B_SMALL = raw("1003_EA", "Natrel Fine-Filtered 2% Milk", "Natrel", "2 l", 4.49)
CHOC = raw("1004_EA", "Milk Chocolate Bar", "Choco Co", "100 g", 2.49, unit=(2.49, 100, "g"))
ATTA = raw("1005_EA", "Whole Wheat Flour", "Golden Mill", "9.07 kg", 18.0, unit=(0.2, 100, "g"))


class Parsing(unittest.TestCase):
    def test_regular_price(self):
        p = parse_product(MILK_A)
        self.assertEqual((p["price_cents"], p["regular_cents"], p["on_sale"], p["sale_ends"]), (581, 581, False, None))
        self.assertEqual((p["unit_cents"], p["unit_qty"], p["unit"]), (15, 100, "ml"))
        self.assertTrue(p["in_stock"])

    def test_sale_with_was_price_and_end_date(self):
        p = parse_product(raw("9_EA", "Milk", "X", "2 l", 5.50, was=6.05, ends="2026-10-28", deal=("SALE", "SAVE $0.55")))
        self.assertEqual((p["price_cents"], p["regular_cents"], p["on_sale"], p["sale_ends"]), (550, 605, True, "2026-10-28"))
        self.assertEqual((p["deal_type"], p["deal_text"], p["deal_cents"]), ("SALE", "SAVE $0.55", None))

    def test_multibuy_and_points(self):
        p = parse_product(raw("9_EA", "Shake", "X", "414 ml", 4.75, deal=("MULTI", "$4.00 MIN 2"), deal_price=4.0,
                              points=6000))
        self.assertEqual((p["deal_type"], p["deal_cents"], p["points"], p["points_ends"]), ("MULTI", 400, 6000, "2026-10-28"))
        self.assertEqual(multibuy(p["deal_text"], p["deal_cents"]), "2 for $8.00")

    def test_lookup_by_code_shape(self):
        p = parse_product(as_detail(raw("9_EA", "Milk", "X", "2 l", 5.50, was=6.05, ends="2026-10-28")))
        self.assertEqual((p["code"], p["price_cents"], p["regular_cents"], p["on_sale"]), ("9_EA", 550, 605, True))

    def test_out_of_stock(self):
        self.assertFalse(parse_product(raw("9_EA", "Milk", "X", "2 l", 5.5, stock="OUT_OF_STOCK"))["in_stock"])


class Matching(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(size_of("4 l"), (4000.0, "ml"))
        self.assertEqual(size_of("Natrel 2% 4L"), (4000.0, "ml"))
        self.assertEqual(size_of("2 litres"), (2000.0, "ml"))
        self.assertEqual(size_of("414 ml"), (414.0, "ml"))
        self.assertEqual(size_of("9.07 kg"), (9070.0, "g"))
        self.assertAlmostEqual(size_of("20 lb")[0], 9072.0)
        self.assertIsNone(size_of("natrel 2%"))

    def test_the_named_brand_wins(self):
        c, _ = pick("Natrel 2%", "milk", [parse_product(p) for p in (MILK_A, MILK_B, MILK_B_SMALL, CHOC)])
        self.assertEqual(c["code"], "1002_EA")

    def test_a_named_size_picks_that_size(self):
        c, _ = pick("Natrel 2% 2L", "milk", [parse_product(p) for p in (MILK_A, MILK_B, MILK_B_SMALL)])
        self.assertEqual(c["code"], "1003_EA")

    def test_a_brand_alone_can_match_without_the_staple_word(self):
        c, _ = pick("Golden Mill", "atta", [parse_product(ATTA)])
        self.assertEqual(c["code"], "1005_EA")

    def test_picking_for_a_plain_word(self):
        shake = parse_product(raw("1006_EA", "Vanilla Protein Shake Milk", "Shake Co", "414 ml", 4.75))
        dip = parse_product(raw("1007_EA", "Baba Ganoush Dip", "Mezze", "227 g", 4.99))
        milks = [shake, parse_product(MILK_B), parse_product(MILK_A)]
        self.assertEqual(pick_plain("milk", milks)["code"], "1001_EA")          # fewest other words
        self.assertEqual(pick_plain("Bana ganush", [dip])["code"], "1007_EA")    # typo and spacing
        self.assertIsNone(pick_plain("chips", milks))
        out = parse_product(raw("1008_EA", "Milk", "X", "1 l", 2.0, stock="OUT_OF_STOCK"))
        self.assertIsNone(pick_plain("milk", [out]))

    def test_unsure_is_no_match(self):
        cands = [parse_product(p) for p in (MILK_A, MILK_B, CHOC)]
        self.assertIsNone(pick("Organic Meadow", "milk", cands))
        self.assertIsNone(pick("Natrel 2% 1L", "milk", cands))     # no 1 l on offer

    def test_weekly_slot(self):
        mon = datetime(2026, 10, 19, 10, 0, tzinfo=TZ)
        self.assertEqual(next_slot(mon, "thu 07:00"), datetime(2026, 10, 22, 7, 0, tzinfo=TZ))
        self.assertEqual(next_slot(datetime(2026, 10, 22, 6, 0, tzinfo=TZ), "thu 07:00"), datetime(2026, 10, 22, 7, 0, tzinfo=TZ))
        self.assertEqual(next_slot(datetime(2026, 10, 22, 7, 0, tzinfo=TZ), "thu 07:00"), datetime(2026, 10, 29, 7, 0, tzinfo=TZ))
        with self.assertRaises(ValueError):
            parse_slot("thursday at 7")


class Client(unittest.TestCase):
    def client(self, handler):
        return Pcx("web-key", TZ, transport=httpx.MockTransport(handler), gap=0)

    def test_search_sends_the_day_as_ddmmyyyy_and_the_banner(self):
        seen = {}

        def handler(req):
            seen["body"], seen["headers"] = json.loads(req.content), req.headers
            return httpx.Response(200, json={"results": [MILK_A, MILK_B]})
        got = self.client(handler).search("nofrills", "2002", "milk")
        self.assertEqual([p["code"] for p in got], ["1001_EA", "1002_EA"])
        self.assertRegex(seen["body"]["date"], r"^\d{8}$")
        self.assertEqual(seen["body"]["date"], datetime.now(TZ).strftime("%d%m%Y"))
        self.assertEqual((seen["body"]["storeId"], seen["headers"]["site-banner"], seen["headers"]["x-apikey"]),
                         ("2002", "nofrills", "web-key"))

    def test_a_changed_key_stops_everything(self):
        pcx = self.client(lambda req: httpx.Response(401, json={}))
        with self.assertRaises(PcxBlocked):
            pcx.search("superstore", "1001", "milk")
        with self.assertRaises(PcxBlocked):
            self.client(lambda req: httpx.Response(403, text="no")).product("superstore", "1001", "1001_EA")

    def test_a_product_the_store_doesnt_list_is_none(self):
        self.assertIsNone(self.client(lambda req: httpx.Response(404, json={})).product("superstore", "1001", "x"))
        got = self.client(lambda req: httpx.Response(200, json=as_detail(MILK_A))).product("superstore", "1001", "1001_EA")
        self.assertEqual(got["price_cents"], 581)


class FakePcx:
    gap = 0

    def __init__(self, catalogue: dict):
        self.catalogue = catalogue   # banner -> code -> raw product
        self.fail = None
        self.calls = []

    def close(self):
        pass

    def search(self, banner, store_id, term, size=12):
        if self.fail:
            raise self.fail
        self.calls.append(("search", banner, term))
        return [parse_product(p) for p in self.catalogue[banner].values()]

    def product(self, banner, store_id, code):
        if self.fail:
            raise self.fail
        self.calls.append(("product", banner, code))
        p = self.catalogue[banner].get(code)
        return parse_product(as_detail(p)) if p else None


class Clock:
    def __init__(self, when):
        self.when = when

    def __call__(self):
        return self.when


def nofrills(p, price, **kw):
    return raw(p["code"], p["name"], p["brand"], p["packageSize"], price, **kw)


class Service(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "t.db"))
        self.clock = Clock(datetime(2026, 10, 22, 7, 0, tzinfo=TZ))
        self.shop = Shopping(self.store, self.clock)
        self.pcx = FakePcx({
            "superstore": {p["code"]: p for p in (MILK_A, MILK_B, ATTA)},
            "nofrills": {"1002_EA": nofrills(MILK_B, 5.99, was=6.29, ends="2026-10-28", deal=("SALE", "SAVE $0.30")),
                         "1005_EA": nofrills(ATTA, 22.99)}})
        self.prices = Prices(self.store, self.shop.staples, self.clock, self.pcx, STORES, split_min=0.1)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, title, product=""):
        items = self.shop.add([{"title": title, "product": product}])
        self.prices.link_pending(items)
        return self.shop.items()

    def test_a_learned_product_is_matched_and_priced_at_both_stores(self):
        [item] = self.add("milk", "Natrel 2%")
        self.assertEqual((item["store"], item["product"]["code"]), ("Real Canadian Superstore", "1002_EA"))
        q = self.prices.view(self.shop.items())["items"][str(item["id"])]
        self.assertEqual([s["banner"] for s in q["stores"]], ["nofrills", "superstore"])   # cheapest first
        self.assertEqual((q["cheapest"], q["saving_cents"], q["move_to"]), ("nofrills", 30, "No Frills"))
        self.assertEqual((q["stores"][0]["on_sale"], q["stores"][0]["sale_ends"]), (True, "2026-10-28"))

    def test_an_unsure_match_stays_unlinked_and_unpriced(self):
        [item] = self.add("milk", "Organic Meadow")
        self.assertFalse(item["product"]["linked"])
        self.assertTrue(item["product"]["tried"])
        view = self.prices.view(self.shop.items())
        self.assertEqual((view["pricable"], view["priced"]), (1, 0))

    def test_items_at_other_stores_are_left_alone(self):
        self.shop.add([{"title": "milk", "product": "Natrel 2%", "store": "Costco"}])
        self.prices.link_pending(self.shop.items())
        self.assertEqual(self.pcx.calls, [])

    def test_totals_and_the_split_trip(self):
        self.add("milk", "Natrel 2%")
        self.add("atta", "Golden Mill")
        view = self.prices.view(self.shop.items())
        self.assertEqual(view["totals"], {"superstore": 629 + 1800, "nofrills": 599 + 2299})
        # cheaper alone: Superstore 24.29; each where cheapest: 5.99 + 18.00 = 23.99
        self.assertEqual(view["split_saving_cents"], 30)

    def test_a_wild_jump_is_held_back_until_confirmed(self):
        p = parse_product(MILK_A)
        self.prices.record("superstore", p)
        self.prices.record("superstore", {**p, "price_cents": 99})
        self.assertEqual(self.prices.latest("1001_EA")["superstore"]["price_cents"], 581)
        self.prices.record("superstore", {**p, "price_cents": 100})
        self.assertEqual(self.prices.latest("1001_EA")["superstore"]["price_cents"], 100)

    def test_old_prices_are_not_shown(self):
        self.prices.record("superstore", parse_product(MILK_A))
        self.clock.when += timedelta(days=11)
        self.assertEqual(self.prices.latest("1001_EA"), {})

    def test_a_plain_item_gets_the_plainest_product_picked(self):
        [item] = self.add("Milk")
        self.assertEqual((item["staple"], item["product"]["code"], item["product"]["auto"]), ("Milk", "1001_EA", True))
        self.assertEqual(item["product"]["label"], "Valley Farm 2% Regular Milk")
        self.assertIn(str(item["id"]), self.prices.view(self.shop.items())["items"])

    def test_naming_a_product_replaces_a_pick_without_asking(self):
        [item] = self.add("milk")
        self.shop.buy(item["id"])
        [named] = self.add("milk", "Natrel 2%")
        self.assertTrue(named["product"]["code"] == "1002_EA")
        made = self.shop.add([{"title": "milk", "product": "Natrel 2%"}])   # the same again: nothing to ask
        self.assertTrue(made[0]["duplicate"])
        self.shop.buy(named["id"])
        self.assertEqual(self.add("milk")[0]["product"]["label"], "Natrel 2%")

    def test_nothing_fitting_is_not_searched_again_this_week(self):
        self.add("unicorn steaks")
        searches = [c for c in self.pcx.calls if c[0] == "search"]
        self.add("Unicorn steak")   # a second one, another day: still marked as tried
        self.assertEqual([c for c in self.pcx.calls if c[0] == "search"], searches)

    def test_refresh_checks_listed_products_at_every_store(self):
        self.add("milk", "Natrel 2%")
        self.clock.when += timedelta(hours=1)   # prices found while matching count as fresh for 30 minutes
        self.pcx.calls.clear()
        self.assertEqual(self.prices.refresh("list")["status"], "ok")
        self.assertEqual(sorted(c[1] for c in self.pcx.calls if c[0] == "product"), ["nofrills", "superstore"])
        self.assertTrue(self.prices.view([])["last_refresh"])

    def test_a_refused_refresh_pauses_prices(self):
        self.add("milk", "Natrel 2%")
        self.clock.when += timedelta(hours=1)
        self.pcx.fail = PcxBlocked("HTTP 401")
        self.assertEqual(self.prices.refresh("all")["status"], "blocked")
        self.assertIn("401", self.prices.view([])["status"]["blocked"]["why"])

    def test_the_button_waits_an_hour(self):
        self.prices._set("prices.last_manual", self.clock().isoformat())
        with self.assertRaises(TaskError) as e:
            self.prices.start()
        self.assertEqual(e.exception.status, 429)

    def test_off_without_a_client(self):
        off = Prices(self.store, self.shop.staples, self.clock, None, STORES)
        self.assertFalse(off.view([])["enabled"])
        with self.assertRaises(TaskError):
            off.start()


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "t.db"))
        self.cfg = Config(tz_name="UTC", db_path=":memory:", api_token=TOKEN, ha_url="", ha_token="", ha_tasks_user_id="",
                          bot_url="", bot_token="", people=(Person("alex", "Alex", "notify_alex"),), device_people={},
                          pcx_api_key="web-key", pcx_stores=STORES)
        self.pcx = FakePcx({"superstore": {p["code"]: p for p in (MILK_A, MILK_B, MILK_B_SMALL)},
                            "nofrills": {"1002_EA": nofrills(MILK_B, 5.99)}})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_teach_ask_correct_and_price(self):
        from fastapi.testclient import TestClient
        from app.web import create_app
        app = create_app(cfg=self.cfg, store=self.store, clock=lambda: datetime(2026, 10, 22, 7, 0, tzinfo=TZ),
                         start_scheduler=False, pcx=self.pcx)
        auth = {"Authorization": f"Bearer {TOKEN}"}
        with TestClient(app) as c:
            [a] = c.post("/api/shopping", json={"items": [{"title": "milk", "product": "Natrel 2%"}]}, headers=auth).json()["items"]
            self.assertTrue(a["learned"])
            self.assertEqual(a["product"]["catalogue_name"], "Natrel Fine-Filtered 2% Milk")
            staples = c.get("/api/staples", headers=auth).json()["staples"]
            self.assertEqual(staples[0]["usual"]["label"], "Natrel 2%")
            prices = c.get("/api/prices", headers=auth).json()
            self.assertEqual(prices["items"][str(a["id"])]["move_to"], "No Frills")
            self.assertTrue(c.get("/api/bootstrap", headers=auth).json()["prices"]["enabled"])
            # a correction to the usual relinks it, to the 2 l
            fixed = c.post(f"/api/shopping/{a['id']}/product", json={"product": "Natrel 2% 2L"}, headers=auth).json()["item"]
            self.assertTrue(fixed["usual_changed"])
            self.assertEqual(fixed["product"]["code"], "1003_EA")
            c.post(f"/api/shopping/{a['id']}/buy", json={}, headers=auth)
            # a different one asks; the same catalogue product written differently doesn't
            [d] = c.post("/api/shopping", json={"items": [{"title": "Milk", "product": "Valley Farm"}]}, headers=auth).json()["items"]
            self.assertEqual(d["ask_usual"]["new"], "Valley Farm")
            c.post(f"/api/shopping/{d['id']}/buy", json={}, headers=auth)
            [same] = c.post("/api/shopping", json={"items": [{"title": "milk", "product": "natrel 2% milk 2 litres"}]},
                            headers=auth).json()["items"]
            self.assertIsNone(same["ask_usual"])
            ok = c.post(f"/api/staples/{d['ask_usual']['staple_id']}/usual", json={"product_id": d["ask_usual"]["product_id"]},
                        headers=auth).json()["staple"]
            self.assertEqual(ok["usual"]["label"], "Valley Farm")
            self.assertEqual(c.post("/api/prices/refresh", headers=auth).status_code, 200)
            self.assertEqual(c.post("/api/prices/refresh", headers=auth).status_code, 429)
            for _ in range(100):   # let the background check finish before the database closes
                if not app.state.prices.running:
                    break
                time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
