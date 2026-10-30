"""Pure shopping rules: which department an item's title belongs to, the
category and usual store that follow from it, and the aisle each store keeps
it in. No I/O; unit-tested in tests/test_aisles.py.

`classify("Buy shrubs")` is "garden": category Garden, usual store Home Depot,
aisle Garden Centre there (Home & Garden at Superstore, Garden at a store
with no layout of its own).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from itertools import product

DEFAULT_CATEGORY = "Groceries"
DEFAULT_STORE = "Real Canadian Superstore"
CATEGORIES = ["Groceries", "Household", "Pharmacy & Health", "Pet Supplies", "Home Improvement", "Garden",
              "Furniture & Decor", "Electronics", "Clothing", "Other"]
# Where a category's things are bought unless someone names a store.
CATEGORY_STORES = {"Home Improvement": "Home Depot", "Garden": "Home Depot", "Furniture & Decor": "IKEA",
                   "Electronics": "Best Buy"}

# department: (category, the words and phrases in a title that put it there).
# Plurals match their singular ("shrubs", "berries", "tomatoes").
DEPARTMENTS = {
    "produce": ("Groceries", """
        fruit, veggie, vegetable, salad, apple, banana, orange, lemon, lime, grape, grapefruit, berry, strawberry,
        blueberry, raspberry, blackberry, cherry, peach, pear, plum, mango, pineapple, watermelon, melon,
        cantaloupe, kiwi, avocado, pomegranate, papaya, guava, coconut, date, tomato, potato, sweet potato, onion,
        shallot, garlic, ginger, carrot, celery, cucumber, lettuce, romaine, spinach, kale, cabbage, broccoli,
        cauliflower, bell pepper, capsicum, jalapeno, chilli, chili, green chilli, zucchini, eggplant, brinjal,
        okra, bhindi, mushroom, corn, green bean, asparagus, beet, radish, squash, pumpkin, cilantro, coriander,
        parsley, mint, basil, dill, chive, herb, scallion, green onion, spring onion, leek, sprout, bok choy,
        methi, curry leaf, lemongrass, tofu, red pepper, green pepper, yellow pepper"""),
    "bakery": ("Groceries", """
        bread, loaf, bun, bagel, baguette, croissant, muffin, english muffin, naan, pita, tortilla, wrap,
        dinner roll, cake, donut, doughnut, sourdough, brioche, ciabatta, roti, chapati, pie"""),
    "deli": ("Groceries", """
        hummus, baba ganoush, babaganoush, ganoush, ghanoush, tzatziki, dip, guacamole, pesto, kimchi,
        sauerkraut, rotisserie chicken, deli meat, salami, ham, prosciutto, pepperoni, sushi, egg bite,
        falafel, dosa batter, idli batter"""),
    "dairy": ("Groceries", """
        milk, almond milk, oat milk, soy milk, oatmilk, cream, half and half, whipping cream, sour cream, butter,
        cheese, cheddar, mozzarella, parmesan, feta, brie, cream cheese, cottage cheese, yogurt, yoghurt, dahi,
        curd, paneer, lassi, kefir, egg, margarine"""),
    "meat": ("Groceries", """
        meat, chicken, chicken breast, chicken thigh, thigh, drumstick, wing, rib, burger, patty, beef, ground beef, steak, pork,
        bacon, sausage, hot dog, lamb, goat, mutton, turkey, fish, salmon, cod, tilapia, shrimp, prawn, seafood,
        mince"""),
    "frozen": ("Groceries", """
        frozen, ice cream, gelato, sorbet, popsicle, ice, pizza, fry, french fry, nugget, dumpling,
        potsticker, gyoza, samosa, paratha, edamame, acai, fried rice, waffle, perogy, pierogi,
        meatball, fish stick, spring roll"""),
    "pantry": ("Groceries", """
        rice, basmati, pasta, spaghetti, penne, macaroni, mac and cheese, noodle, flour, sugar, salt, pepper,
        black pepper, oil, olive oil, vinegar, soy sauce, sauce, ketchup, mustard, mayo, mayonnaise, hot sauce,
        sriracha, honey, jam, maple syrup, syrup, peanut butter, nutella, cereal, oat, oatmeal, granola, canned,
        bean, chickpea, lentil, tuna, soup, broth, stock, coconut milk, tomato paste, spice, cumin, turmeric,
        paprika, cinnamon, oregano, chili flake, chilli flake, powder, seasoning, sesame seed, chia seed,
        flax seed, pumpkin seed, sunflower seed, baking soda, baking powder, yeast, vanilla,
        cornstarch, arrowroot, cocoa, chocolate chip, quinoa, couscous, breadcrumbs, panko, olive, pickle,
        salsa, tahini, bouillon"""),
    "international": ("Groceries", """
        atta, besan, maida, sooji, suji, rava, semolina, dal, daal, dhal, toor, moong, masoor, urad, chana,
        rajma, poha, jaggery, ghee, masala, garam masala, hing, asafoetida, ajwain, jeera, papad, papadum, achar,
        ramen, miso, nori, seaweed, gochujang, fish sauce, oyster sauce, hoisin, curry, curry paste, tamarind,
        rice paper, rose water"""),
    "snacks": ("Groceries", """
        snack, chip, crisp, cracker, cookie, biscuit, chocolate, candy, gum, popcorn, pretzel, nut, almond,
        cashew, peanut, pistachio, walnut, trail mix, granola bar, protein bar, namkeen, bhujia, rusk,
        dried fruit, raisin, jerky, chocolate bark"""),
    "beverages": ("Groceries", """
        water, sparkling water, bubly, bubbly, juice, pop, soda, coke, pepsi, ginger ale, coffee, tea, chai,
        kombucha, beer, wine, coffee bean, coconut water, energy drink, gatorade, lemonade, drink"""),
    "health": ("Pharmacy & Health", """
        shampoo, conditioner, body wash, soap, toothpaste, toothbrush, floss, mouthwash, deodorant, razor,
        shaving cream, lotion, sunscreen, moisturizer, vitamin, multivitamin, supplement, tylenol, advil,
        ibuprofen, acetaminophen, medicine, cough syrup, band aid, bandaid, bandage, first aid, tampon, pad,
        contact solution, cotton pad, q tip, makeup, nail polish, prescription, allergy, antacid, melatonin,
        thermometer"""),
    "household": ("Household", """
        paper towel, toilet paper, tissue, kleenex, napkin, garbage bag, trash bag, bin bag, ziploc, ziplock,
        sandwich bag, foil, plastic wrap, cling wrap, parchment paper, dish soap, dishwasher tablet,
        dishwasher pod, detergent, laundry detergent, fabric softener, dryer sheet, bleach, cleaner, windex,
        wipe, sponge, mop, broom, battery, air freshener, hand soap, diaper, toilet brush, stain remover"""),
    "kitchenware": ("Household", """
        frying pan, saucepan, pan, cooking pot, baking sheet, knife, cutting board, chopping board, mug, plate, bowl,
        cup, cutlery, utensil, spatula, tupperware, food container, storage container, water bottle, kettle,
        toaster, blender, air fryer, rice cooker, instant pot"""),
    "pet": ("Pet Supplies", """
        pet, dog, puppy, cat, kitten, dog food, cat food, kibble, dog treat, cat treat, litter, cat litter,
        poop bag, leash, collar, chew, dog toy, cat toy, flea, puppy pad"""),
    "garden": ("Garden", """
        shrub, bush, hedge, plant, tree, flower, bulbs, seed, soil, potting soil, potting mix, mulch, compost,
        fertilizer, manure, planter, flower pot, plant pot, hose, garden hose, sprinkler, rake, shovel, spade,
        trowel, pruner, shears, garden gloves, lawn, grass seed, weed killer, bark, landscape fabric, edging,
        raised bed, trellis, bird seed, bird feeder, peat moss, perlite, succulent, cactus, hydrangea, rose,
        tulip, lawn mower, leaf blower, wheelbarrow"""),
    "building": ("Home Improvement", """
        lumber, wood, plywood, 2x4, board, drywall, concrete, cement, fence, fencing, fence post, deck, decking,
        gravel, sand, paver, brick, insulation, grout, siding, shingle, roofing, gutter"""),
    "paint": ("Home Improvement", """
        paint, primer, paint brush, paint roller, roller, painters tape, caulk, sealant, stain, varnish,
        sandpaper, drop cloth, spackle, putty, wood filler"""),
    "hardware": ("Home Improvement", """
        screw, nail, bolt, washer, anchor, wall anchor, hook, hinge, drill, drill bit, hammer, screwdriver,
        wrench, plier, saw, tape measure, level, ladder, toolbox, tool, glue, super glue, wd 40, duct tape,
        zip tie, padlock, lock, door handle, knob, bracket, shelf bracket, chain, rope, bungee, tarp, step stool,
        utility knife, stud finder, allen key, sander, mouse trap"""),
    "plumbing": ("Home Improvement", """
        faucet, pipe, pvc, plunger, drain, toilet, toilet seat, shower head, showerhead, flapper, wax ring,
        plumbers tape, teflon tape, water filter, sink"""),
    "electrical": ("Home Improvement", """
        light bulb, led bulb, extension cord, power bar, power strip, outlet, light switch, dimmer, wire,
        electrical tape, smoke detector, smoke alarm, carbon monoxide detector, fuse, breaker, motion sensor"""),
    "lighting": ("Furniture & Decor", """
        lamp, lampshade, lamp shade, floor lamp, table lamp, pendant light, chandelier, light fixture, sconce,
        string light, fairy light, night light"""),
    "furniture": ("Furniture & Decor", """
        furniture, table, dining table, coffee table, center table, centre table, side table, end table, desk,
        chair, stool, bar stool, bench, sofa, couch, sectional, loveseat, ottoman, pouf, armchair, recliner, bed,
        bed frame, mattress, crib, dresser, nightstand, bedside table, wardrobe, bookshelf, bookcase, shelf,
        shelving, cabinet, tv stand, media console, sideboard, patio furniture, patio set, hammock,
        futon, headboard"""),
    "textiles": ("Furniture & Decor", """
        rug, area rug, runner, curtain, curtain rod, blind, drape, cushion, throw pillow, pillow, throw, blanket,
        duvet, comforter, bedding, sheet, bed sheet, pillowcase, towel, bath towel, bath mat, shower curtain,
        doormat"""),
    "decor": ("Furniture & Decor", """
        decor, decoration, mirror, frame, picture frame, vase, art, wall art, artwork, poster, candle, clock,
        basket"""),
    "electronics": ("Electronics", """
        charger, phone charger, cable, usb, usb c, hdmi, adapter, headphone, earbud, airpods, speaker, tv,
        television, monitor, laptop, computer, keyboard, mouse, webcam, router, modem, hard drive, ssd, sd card,
        memory card, printer, ink, toner, camera, ipad, tablet, phone, phone case, screen protector, power bank,
        smart plug, video game, game controller, nintendo switch"""),
    "clothing": ("Clothing", """
        sock, shirt, t shirt, tshirt, pant, jean, short, jacket, coat, sweater, hoodie, underwear, bra, shoe,
        sneaker, boot, slipper, sandal, hat, glove, mitten, scarf, pajama, pyjama, dress, legging, belt,
        raincoat"""),
}

# Each store's aisles in walking order, with the departments each one holds.
# A store with no layout here uses GENERIC_LAYOUT.
LAYOUTS = {
    "Real Canadian Superstore": [
        ("Produce", "produce"), ("Bakery", "bakery"), ("Deli", "deli"), ("Dairy & Eggs", "dairy"),
        ("Meat & Seafood", "meat"), ("Frozen", "frozen"), ("Pantry", "pantry"), ("International", "international"),
        ("Snacks", "snacks"), ("Beverages", "beverages"), ("Health & Beauty", "health"),
        ("Household", "household kitchenware"), ("Pet", "pet"),
        ("Home & Garden", "garden furniture textiles decor lighting building paint hardware plumbing electrical"),
        ("Electronics", "electronics"), ("Clothing", "clothing"), ("Other", "")],
    "Costco": [
        ("Produce", "produce"), ("Bakery", "bakery"), ("Deli & Prepared", "deli"), ("Dairy", "dairy"),
        ("Meat & Seafood", "meat"), ("Frozen", "frozen"), ("Pantry & Snacks", "pantry international snacks"),
        ("Beverages", "beverages"), ("Health & Beauty", "health"), ("Household", "household kitchenware pet"),
        ("Home & Garden", "garden furniture textiles decor lighting building paint hardware plumbing electrical"),
        ("Electronics", "electronics"), ("Clothing", "clothing"), ("Other", "")],
    "Home Depot": [
        ("Garden Centre", "garden"), ("Lumber & Building", "building"), ("Paint", "paint"),
        ("Hardware & Tools", "hardware"), ("Plumbing", "plumbing"), ("Electrical", "electrical"),
        ("Lighting", "lighting"), ("Flooring & Decor", "textiles decor"), ("Kitchen & Bath", "kitchenware"),
        ("Storage & Cleaning", "household"), ("Patio & Furniture", "furniture"), ("Other", "")],
    "IKEA": [
        ("Showroom", "furniture"), ("Cooking & Eating", "kitchenware"), ("Textiles & Rugs", "textiles"),
        ("Lighting", "lighting"), ("Decoration", "decor garden"), ("Storage & Organisation", "household"),
        ("Self Serve", ""), ("Other", "")],
}
GENERIC_LAYOUT = [
    ("Produce", "produce"), ("Bakery", "bakery"), ("Deli", "deli"), ("Dairy & Eggs", "dairy"),
    ("Meat & Seafood", "meat"), ("Frozen", "frozen"), ("Pantry", "pantry international"), ("Snacks", "snacks"),
    ("Beverages", "beverages"), ("Health & Beauty", "health"), ("Household", "household kitchenware"),
    ("Pet", "pet"), ("Garden", "garden"), ("Home Improvement", "building paint hardware plumbing electrical"),
    ("Furniture & Decor", "furniture textiles decor lighting"), ("Electronics", "electronics"),
    ("Clothing", "clothing"), ("Other", "")]

# A title is read up to its first of these ("planters along the fence" is planters).
_CUT = {"for", "from", "at", "along", "with", "to", "in", "on", "near", "by"}


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return [w for w in re.split(r"[^a-z0-9]+", text.replace("&", " and ")) if w]


def _forms(w: str) -> list[str]:
    """A title word and the singulars it might be ("berries", "cookies",
    "tomatoes", "shoes", "shelves"); the word lists are written singular."""
    out = [w]
    if len(w) > 4 and w.endswith("ies"):
        out += [w[:-3] + "y", w[:-1]]
    elif len(w) > 4 and w.endswith("ves"):
        out += [w[:-3] + "f", w[:-3] + "fe", w[:-1]]
    elif len(w) > 3 and w.endswith("es"):
        out += [w[:-2], w[:-1]]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us")):
        out.append(w[:-1])
    return out


_PHRASES: dict[tuple[str, ...], str] = {}
for _dept, (_cat, _text) in DEPARTMENTS.items():
    for _phrase in _text.split(","):
        _PHRASES.setdefault(tuple(_words(_phrase)), _dept)
_SINGLE = sorted(p[0] for p in _PHRASES if len(p) == 1)
_LONGEST = max(len(p) for p in _PHRASES)


def _match(forms: list[list[str]]) -> str | None:
    """The department of the last word or phrase that names one (the head
    noun comes last: "tomato sauce" is a sauce), the longer phrase on a tie."""
    best = None
    for end in range(1, len(forms) + 1):
        for n in range(1, min(_LONGEST, end) + 1):
            dept = next((_PHRASES[p] for p in product(*forms[end - n:end]) if p in _PHRASES), None)
            if dept and (not best or (end, n) > best[:2]):
                best = (end, n, dept)
    return best[2] if best else None


def classify(title: str) -> str | None:
    """The department an item belongs to, or None when the title says nothing we know."""
    words = _words(title)
    if "frozen" in words:
        return "frozen"
    forms = [_forms(w) for w in words]
    head = next((i for i, w in enumerate(words) if w in _CUT), len(words))
    found = (_match(forms[:head]) if head else None) or _match(forms)
    if found:
        return found
    for w in (f for fs in forms for f in fs if len(f) >= 5):   # a near miss ("mozarella", "ganush")
        close = difflib.get_close_matches(w, _SINGLE, n=1, cutoff=0.85)
        if close:
            return _PHRASES[(close[0],)]
    return None


def category_of(dept: str | None) -> str:
    return DEPARTMENTS[dept][0] if dept in DEPARTMENTS else DEFAULT_CATEGORY


def store_for(category: str) -> str:
    return CATEGORY_STORES.get(category, DEFAULT_STORE)


def layout(store: str) -> list[tuple[str, str]]:
    return LAYOUTS.get(store, GENERIC_LAYOUT)


def aisles_for(store: str) -> list[str]:
    return [name for name, _ in layout(store)]


def aisle_for(dept: str | None, store: str) -> str:
    """The store's aisle for a department, or '' when it has none."""
    return next((name for name, depts in layout(store) if dept and dept in depts.split()), "")


def department_in(aisle: str, store: str) -> str | None:
    """The first department a store's aisle holds (to find it at another store)."""
    depts = next((d.split() for name, d in layout(store) if name.lower() == (aisle or "").lower()), [])
    return depts[0] if depts else None


AISLES = {store: aisles_for(store) for store in LAYOUTS}
DEFAULT_AISLES = aisles_for("")
