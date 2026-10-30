"""The shopping rules in app/aisles.py: titles to departments, departments to
categories, stores and aisles. Pure functions, no database."""
import unittest

from app import aisles
from app.aisles import aisle_for, category_of, classify, department_in, store_for


class Classify(unittest.TestCase):
    def test_titles(self):
        cases = {
            "Shrubs for the yard": "garden", "buy potting soil": "garden", "planters along the deck": "garden",
            "Dining chairs": "furniture", "coffee table": "furniture", "area rug": "textiles", "table lamp": "lighting",
            "greek yogurt": "dairy", "Eggs": "dairy", "chocolate milk": "dairy", "milk chocolate": "snacks",
            "tomato sauce": "pantry", "peanut butter": "pantry", "coconut milk": "pantry", "basmati rice": "pantry",
            "hot dog buns": "bakery", "garlic bread": "bakery", "rotisserie chicken": "deli",
            "chicken thighs": "meat", "chicken nuggets": "frozen", "frozen peas": "frozen", "fried rice": "frozen",
            "nuts and bolts": "hardware", "paint for the fence": "paint", "light bulbs": "electrical",
            "tulip bulbs": "garden", "paper towels": "household", "dish soap": "household", "shampoo": "health",
            "cat litter": "pet", "phone charger": "electronics", "t-shirts": "clothing", "mac & cheese": "pantry",
            "atta": "international", "curry leaves": "produce", "berries": "produce", "cookies": "snacks",
            "shelves": "furniture", "knives": "kitchenware", "tomatoes": "produce", "shoes": "clothing",
        }
        self.assertEqual({t: classify(t) for t in cases}, cases)

    def test_accents_typos_and_unknowns(self):
        self.assertEqual(classify("Açaí purée"), "frozen")
        self.assertEqual(classify("mozarella"), "dairy")
        self.assertEqual(classify("baba ganush"), "deli")
        self.assertIsNone(classify("Something new"))
        self.assertIsNone(classify(""))


class Placement(unittest.TestCase):
    def test_category_and_store(self):
        self.assertEqual((category_of("garden"), store_for("Garden")), ("Garden", "Home Depot"))
        self.assertEqual((category_of("dairy"), store_for("Groceries")), ("Groceries", aisles.DEFAULT_STORE))
        self.assertEqual(category_of(None), aisles.DEFAULT_CATEGORY)
        self.assertEqual(set(aisles.CATEGORY_STORES) - set(aisles.CATEGORIES), set())
        self.assertEqual({c for c, _ in aisles.DEPARTMENTS.values()} - set(aisles.CATEGORIES), set())

    def test_aisles(self):
        self.assertEqual(aisle_for("dairy", "Costco"), "Dairy")
        self.assertEqual(aisle_for("dairy", "Home Depot"), "")      # not everywhere sells everything
        self.assertEqual(aisle_for("garden", "Shop Nobody Mapped"), "Garden")
        self.assertEqual(aisle_for(None, "Costco"), "")
        self.assertEqual(department_in("pantry & snacks", "Costco"), "pantry")
        self.assertIsNone(department_in("Other", "Costco"))
        # the default store, Costco and any unmapped store have an aisle for every department
        for store in (aisles.DEFAULT_STORE, "Costco", ""):
            self.assertEqual([d for d in aisles.DEPARTMENTS if not aisle_for(d, store)], [], store)
        for store, rows in aisles.LAYOUTS.items():
            named = [d for _, ds in rows for d in ds.split()]
            self.assertEqual(set(named) - set(aisles.DEPARTMENTS), set(), store)
            self.assertEqual(len(named), len(set(named)), store)   # one aisle per department


if __name__ == "__main__":
    unittest.main()
