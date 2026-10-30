"""Staples: the household's words to products, case, plurals and typos included.

Run in the image: python -m unittest discover tests
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.shopping import Shopping
from app.staples import closest, distance, norm
from app.store import Store
from app.tasks import TaskError

TZ = ZoneInfo("UTC")


class Words(unittest.TestCase):
    def test_norm_folds_case_accents_plurals_and_punctuation(self):
        self.assertEqual(norm("MILK"), norm("milks!"))
        self.assertEqual(norm("Natrel 2 %"), norm("natrel 2%"))
        self.assertEqual(norm("Açaí packs"), norm("acai pack"))
        self.assertEqual(norm("berries"), norm("Berry"))
        self.assertEqual(norm("tomatoes"), norm("tomato"))
        self.assertEqual(norm("cheeses"), norm("cheese"))
        self.assertEqual(norm("eggs"), norm("egg"))

    def test_a_swap_of_neighbours_is_one_edit(self):
        self.assertEqual(distance("mlik", "milk"), 1)
        self.assertEqual(distance("milk", "milk"), 0)
        self.assertEqual(distance("banaganush", "babaganoush"), 2)

    def test_near_misses_find_the_staple(self):
        names = {norm("milk"): 1, norm("babaganoush"): 2, norm("mozzarella"): 3, norm("tea"): 4}
        self.assertEqual(closest(norm("mlik"), names), 1)
        self.assertEqual(closest(norm("bana ganush"), names), 2)
        self.assertEqual(closest(norm("baba ganoush"), names), 2)
        self.assertEqual(closest(norm("mozarella"), names), 3)

    def test_other_things_and_short_words_dont(self):
        names = {norm("milk"): 1, norm("tea"): 4}
        self.assertIsNone(closest(norm("milk chocolate"), names))
        self.assertIsNone(closest(norm("chocolate milk"), names))
        self.assertIsNone(closest(norm("2% milk"), names))     # a different first letter is never a typo
        self.assertIsNone(closest(norm("tee"), names))         # three letters: exact only
        self.assertIsNone(closest(norm("silk"), names))

    def test_two_equally_close_staples_are_no_match(self):
        self.assertIsNone(closest(norm("pastw"), {norm("pasta"): 1, norm("paste"): 2}))


class Teaching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "t.db"))
        clock = lambda: datetime(2026, 10, 19, 10, 0, tzinfo=TZ)
        self.shop = Shopping(self.store, clock)
        self.staples = self.shop.staples

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, title, product=""):
        return self.shop.add([{"title": title, "product": product}])[0]

    def teach(self):
        item = self.add("milk", "Natrel 2%")
        self.shop.buy(item["id"])
        return item

    def test_naming_a_product_teaches_the_staple(self):
        a = self.add("milk", "Natrel 2%")
        self.assertTrue(a["learned"])
        self.assertEqual((a["staple"], a["product"]["label"]), ("milk", "Natrel 2%"))
        self.shop.buy(a["id"])
        b = self.add("Milk")
        self.assertEqual(b["product"]["label"], "Natrel 2%")
        self.assertFalse(b["learned"])
        self.assertIsNone(b["read_as"])
        self.assertEqual(b["title"], "Milk")    # the word as said

    def test_a_typo_reads_as_the_staple_and_says_so(self):
        self.teach()
        c = self.add("mlik")
        self.assertEqual((c["title"], c["read_as"], c["product"]["label"]), ("milk", "mlik", "Natrel 2%"))

    def test_the_usual_written_differently_is_still_the_usual(self):
        a = self.teach()
        b = self.add("milk", "natrel 2 %")
        self.assertIsNone(b["ask_usual"])
        self.assertEqual(b["product_id"], a["product_id"])

    def test_a_different_product_goes_on_the_item_and_asks(self):
        self.teach()
        d = self.add("milk", "Dairyland")
        self.assertEqual(d["product"]["label"], "Dairyland")
        self.assertEqual({k: d["ask_usual"][k] for k in ("staple", "current", "new")},
                         {"staple": "milk", "current": "Natrel 2%", "new": "Dairyland"})
        self.shop.buy(d["id"])
        self.assertEqual(self.add("milk")["product"]["label"], "Natrel 2%")   # still the usual

    def test_make_it_usual(self):
        self.teach()
        d = self.add("milk", "Dairyland")
        self.shop.buy(d["id"])
        self.staples.make_usual(d["ask_usual"]["staple_id"], d["ask_usual"]["product_id"])
        self.assertEqual(self.add("milk")["product"]["label"], "Dairyland")
        with self.assertRaises(TaskError):
            self.staples.make_usual(d["ask_usual"]["staple_id"], 999)

    def test_a_plain_item_stays_plain(self):
        x = self.add("chips")
        self.assertIsNone(x["staple"])
        self.assertIsNone(x["product"])

    def test_correcting_the_usual_changes_the_usual(self):
        a = self.add("milk", "Natrel 2%")
        r = self.staples.set_product(a["id"], "Natrel 2% 4L")
        self.assertTrue(r["usual_changed"])
        self.assertEqual(r["product"]["label"], "Natrel 2% 4L")
        self.shop.buy(a["id"])
        self.assertEqual(self.add("milk")["product"]["label"], "Natrel 2% 4L")

    def test_correcting_a_one_off_changes_only_that_item(self):
        self.teach()
        d = self.add("milk", "Dairyland")
        r = self.staples.set_product(d["id"], "Dairyland 4L")
        self.assertFalse(r["usual_changed"])
        self.shop.buy(d["id"])
        self.assertEqual(self.add("milk")["product"]["label"], "Natrel 2%")

    def test_correcting_a_plain_item_teaches_it(self):
        x = self.add("chips")
        self.assertTrue(self.staples.set_product(x["id"], "Lay's Classic")["usual_changed"])
        self.shop.buy(x["id"])
        self.assertEqual(self.add("Chips")["product"]["label"], "Lay's Classic")

    def test_a_correction_needs_a_product(self):
        x = self.add("chips")
        with self.assertRaises(TaskError):
            self.staples.set_product(x["id"], "  ")

    def test_naming_the_product_of_a_listed_item_attaches_it(self):
        self.add("milk")
        again = self.add("milk", "Natrel 2%")
        self.assertTrue(again["duplicate"])
        self.assertTrue(again["learned"])
        [only] = self.shop.items()
        self.assertEqual(only["product"]["label"], "Natrel 2%")

    def test_same_catalogue_product_settles_the_question(self):
        a = self.teach()
        with self.store.tx() as db:
            db.execute("UPDATE staple_products SET code='X1_EA' WHERE id=?", (a["product_id"],))
        d = self.add("milk", "Natrel two percent")
        self.assertTrue(d["ask_usual"])
        with self.store.tx() as db:
            db.execute("UPDATE staple_products SET code='X1_EA' WHERE id=?", (d["product_id"],))
        settled = self.staples.settle(d)
        self.assertIsNone(settled["ask_usual"])
        self.assertEqual(settled["product_id"], a["product_id"])


if __name__ == "__main__":
    unittest.main()
