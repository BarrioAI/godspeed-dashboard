"""
Godspeed lead-quality rules — the single source of truth.

Pure functions only (no Google, no network), so the dashboard, super_clean.py
and the tests all classify a store the same way.

A store gets a *fit flag*:
    OK           qualified independent streetwear / sneaker / boutique lead
    chain        national chain or department store
    mono-brand   a clothing brand's own store (Nike, Supreme, Lululemon, ...)
    mismatch     the name does not belong to the website / Instagram on the row
    junk         not a clothing retailer at all (restaurant, dealership, ...)
    not-a-store  a scraped article, directory page, post or page title
    low-fit      no streetwear signal anywhere in the row
    broken-data  no usable store name
Flags combine with '+', e.g. 'chain+low-fit'.

Matching is deliberately conservative: chains and brand stores are detected
from the STORE NAME only, on word boundaries. Notes like "carries Chrome
Hearts / Supreme" describe what a store stocks and must never get it flagged.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable, Optional
from urllib.parse import urlparse

# ─────────────────────────────────────────
#  LISTS
# ─────────────────────────────────────────

# Unambiguous chain names — matched anywhere in the store name.
CHAINS = [
    # sneaker / streetwear chains
    "foot locker", "footlocker", "kids foot locker", "footaction", "foot action",
    "finish line", "finishline", "hibbett", "dtlr", "snipes", "jd sports",
    "champs sports", "shoe palace", "shiekh", "jimmy jazz", "city gear",
    "shoe carnival", "famous footwear", "dsw", "journeys", "eastbay", "zappos",
    "shoe dept", "rack room shoes", "payless", "kith", "zumiez", "pacsun",
    "tillys", "tilly's", "hot topic", "spencer's", "rue21", "aeropostale",
    "rainbow shops", "citi trends", "burlington", "flight club", "stadium goods",
    # department / big box
    "macy's", "macys", "nordstrom", "nordstrom rack", "saks fifth avenue",
    "saks off 5th", "neiman marcus", "bloomingdale's", "bloomingdales",
    "dillard's", "dillards", "jcpenney", "jc penney", "kohl's", "kohls",
    "walmart", "tj maxx", "tjmaxx", "t.j. maxx", "marshalls", "ross dress for less",
    "dick's sporting goods", "dicks sporting goods", "academy sports",
    "big 5 sporting goods", "sports authority", "modell's", "modells", "belk",
    # mainstream apparel chains
    "h&m", "h & m", "zara", "uniqlo", "old navy", "banana republic",
    "gap factory", "gap outlet", "j.crew", "j crew", "jcrew",
    "abercrombie", "hollister", "american eagle", "forever 21", "forever21",
    "primark", "topshop", "urban outfitters", "anthropologie", "free people",
    "madewell", "torrid", "lane bryant", "men's wearhouse", "express factory",
    # resale franchises (hundreds of locations)
    "plato's closet", "platos closet", "buffalo exchange", "uptown cheapskate",
    "goodwill", "salvation army", "savers", "value village", "crossroads trading",
]

# Brands whose own stores always start with the brand name ("Nike Well
# Collective", "Adidas Outlet Store", "Lululemon Brickell").
BRAND_PREFIXES = [
    "nike", "niketown", "adidas", "lululemon", "puma", "reebok", "asics",
    "under armour", "new balance", "converse", "skechers", "timberland",
    "the north face", "north face", "patagonia", "levi's", "levis",
    "tommy hilfiger", "calvin klein", "ralph lauren", "polo ralph lauren",
    "michael kors", "kate spade", "lacoste", "true religion", "armani exchange",
    "hugo boss", "burberry", "gucci", "louis vuitton", "prada", "balenciaga",
    "victoria's secret", "a bathing ape", "bape store", "house of hoops",
    "jordan brand", "off-white", "carhartt wip", "stussy", "stüssy",
    "chrome hearts", "palace skateboards", "billionaire boys club",
    "fear of god", "ugg", "crocs", "aime leon dore",
    "ovo", "october's very own",
]

# Words that are both a brand/chain AND a common word. Only flagged when the
# store name is essentially *just* this word (after removing the city and
# filler such as "store", "outlet", "NYC").
EXACT_ONLY = {
    # chains
    "gap": "chain", "target": "chain", "express": "chain", "ross": "chain",
    "champs": "chain", "sears": "chain", "buckle": "chain", "the buckle": "chain",
    "villa": "chain", "lids": "chain", "saks": "chain", "rei": "chain",
    "aerie": "chain", "burlington": "chain", "columbia": "chain",
    # brand stores
    "supreme": "mono-brand", "jordan": "mono-brand", "palace": "mono-brand",
    "bape": "mono-brand", "vans": "mono-brand", "pink": "mono-brand",
    "guess": "mono-brand", "coach": "mono-brand", "diesel": "mono-brand",
    "essentials": "mono-brand", "represent": "mono-brand", "amiri": "mono-brand",
    "rhude": "mono-brand", "hellstar": "mono-brand", "kith": "chain",
    "columbia sportswear": "mono-brand", "carhartt": "mono-brand",
    "the hundreds": "mono-brand", "huf": "mono-brand", "obey": "mono-brand",
    "diamond supply co": "mono-brand", "undefeated": "chain",
}

# Filler removed from a name before the EXACT_ONLY comparison.
_NAME_FILLER = {
    "store", "stores", "shop", "outlet", "factory", "flagship", "retail",
    "clearance", "official", "the", "usa", "us", "inc", "llc", "co", "company",
    "nyc", "ny", "la", "sf", "dc", "atl", "chi", "mia", "soho", "downtown",
    "mall", "plaza", "center", "centre", "galleria", "location", "kids",
    "mens", "men's", "womens", "women's", "brand", "at", "in", "of", "and",
    "north", "south", "east", "west", "new", "york", "los", "angeles",
    "miami", "chicago", "atlanta", "houston", "dallas", "brooklyn",
    "manhattan", "harlem", "beach", "city",
}

# Not a clothing retailer. Matched on word boundaries in the STORE NAME only
# (city names like "Burbank" or "Tacoma" must not trip "bank" / "taco").
JUNK_WORDS = [
    # auto
    "dealership", "automotive", "auto sales", "auto repair", "auto body",
    "auto group", "auto parts", "car wash", "car rental", "motors", "nissan",
    "gmc", "buick", "honda", "toyota", "chevrolet", "chevy", "hyundai",
    "tires", "mechanic", "transmission", "oil change", "collision",
    # food
    "restaurant", "cafe", "café", "coffee", "pizza", "pizzeria", "taqueria",
    "tacos", "sushi", "bakery", "diner", "eatery", "catering", "burger",
    "burgers", "donuts", "bbq", "barbeque", "barbecue", "ramen", "deli",
    "grill", "steakhouse", "bar & grill", "brewery", "liquor", "smoke shop",
    "vape", "dispensary", "grocery", "supermarket", "market deli",
    # health / beauty services
    "dental", "dentist", "dentistry", "clinic", "medical", "chiropractic",
    "pharmacy", "urgent care", "physical therapy", "hospital", "orthodontics",
    "nail salon", "nails", "hair salon", "barbershop", "barber shop",
    "med spa", "tattoo", "lashes",
    # services / institutions
    "real estate", "realty", "realtor", "mortgage", "bank", "credit union",
    "insurance", "attorney", "law firm", "law office", "elementary school",
    "high school", "university", "church", "ministry", "post office",
    "staffing", "storage", "laundromat", "dry cleaners", "cleaners",
    "plumbing", "roofing", "hvac", "hotel", "motel", "apartments", "gym",
    "fitness", "pawn", "cell phone repair", "furniture", "mattress",
    "hardware", "pet store", "veterinary", "daycare", "funeral",
    # other businesses and page titles that search results drag in
    "painting", "vending", "cannabis", "head shop", "meat", "appliances",
    "trailer sales", "towboats", "detailing", "party supplies", "printing",
    "sheds", "cheesy breads", "healthy kitchen", "health kitchen",
    "food company", "business brokers", "gas station", "cadillac",
    "car inventory", "townhomes", "new houses", "soccer club", "bookstore",
    "bookstores", "bike shop", "home decor", "home design", "fine jewelry",
    "dealer locator", "find a dealer", "dealer near you", "service centers",
    "company profile", "filing information", "customer service",
    "discount codes", "sitemap", "newsletter", "season passes", "stockists",
    "find a stockist", "fixture store", "bundt cakes",
]

# Evidence that this is the kind of door Godspeed sells into. Searched in
# every text field of the row.
# Brands a target store stocks. These only count when they appear in the NOTES
# ("carries Hellstar, Sp5der") — a business merely *named* "Supreme Motors" or a
# page titled "Hellstar hoodie" proves nothing.
BRAND_SIGNALS = [
    "hellstar", "rhude", "vale forever", "supreme", "denim tears", "sp5der",
    "spider worldwide", "gallery dept", "off-white", "off white", "fear of god",
    "bape", "amiri", "chrome hearts", "yeezy", "travis scott", "essentials",
    "vlone", "anti social social club", "assc", "stussy", "stüssy", "huf",
    "thrasher", "palace", "kith", "carhartt", "godspeed", "eric emanuel",
    "corteiz", "broken planet", "sicko", "warren lotas", "pleasures",
    "billionaire boys club", "bbc icecream", "mitchell & ness", "pro standard",
    "ksubi", "mnml", "jordan", "nike sb", "dunk", "new era", "purple brand",
    "lost hills", "bravest studios", "who decides war", "nike", "adidas",
    "new balance", "asics",
]

# What the store is. Counts anywhere in the row.
STREETWEAR_SIGNALS = [
    "streetwear", "street wear", "sneaker", "sneakers", "sneakerhead",
    "hypebeast", "hype", "skate", "skateboard", "skateshop", "kicks", "kickz",
    "sole", "soles", "laced", "consignment", "resell", "resale", "reseller",
    "vintage", "thrift", "boutique", "multi-brand", "multi brand", "multibrand",
    "designer", "urban wear", "urbanwear", "urban apparel", "menswear",
    "apparel", "clothing", "clothier", "fashion", "garments", "threads", "drip",
    "fits", "wardrobe", "closet", "collective", "supply", "luxury", "lifestyle",
    "select shop", "concept store", "premium",
]

# Fragments that count even inside a run-together name, handle or domain
# ("SoleFly", "@kicksusa", "sneakerpolitics.com").
COMPOUND_SIGNALS = [
    "sneaker", "kicks", "streetwear", "skate", "boutique", "vintage",
    "thrift", "hype", "sole", "laced", "drip", "consign", "resell", "kickz",
    "apparel", "clothing", "threads", "supply", "wear",
]

SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "fb.com", "tiktok.com", "twitter.com",
    "x.com", "youtube.com", "youtu.be", "linkedin.com", "pinterest.com",
    "linktr.ee", "linktree.com", "yelp.com", "google.com", "maps.google.com",
    "goo.gl", "g.page", "snapchat.com", "threads.net", "beacons.ai",
}

# Instagram path segments that are not profiles.
_IG_NON_PROFILE = {
    "p", "reel", "reels", "explore", "accounts", "stories", "tv", "about",
    "developer", "legal", "directory", "share", "sharer", "web", "invites",
    "popular", "locations", "tags",
}

# How many rows sharing one website / Instagram make a store a chain.
CHAIN_LOCATION_THRESHOLD = 10


# ─────────────────────────────────────────
#  SMALL HELPERS
# ─────────────────────────────────────────

def s(value) -> str:
    """Sheet cell -> clean string (cells can arrive as int, float or None)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _compile(words: Iterable[str]) -> re.Pattern:
    alts = sorted({re.escape(w.lower()) for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")(?![a-z0-9])")


_CHAIN_RE = _compile(CHAINS)
_JUNK_RE = _compile(JUNK_WORDS)
_SIGNAL_RE = _compile(STREETWEAR_SIGNALS)
_BRAND_SIGNAL_RE = _compile(BRAND_SIGNALS)
_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:" + "|".join(
        sorted((re.escape(b) for b in BRAND_PREFIXES), key=len, reverse=True)
    ) + r")(?![a-z0-9])"
)
_WORD_RE = re.compile(r"[a-z0-9&'.+-]+")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("’", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _core_name(name: str, city: str, state: str) -> str:
    """Store name minus its city/state and filler words ('Supreme Los Angeles' -> 'supreme')."""
    drop = set(_NAME_FILLER)
    drop.update(_WORD_RE.findall(_norm(city)))
    drop.update(_WORD_RE.findall(_norm(state)))
    head = re.split(r"\s[-–—|@(/]\s?|\(", _norm(name))[0]
    words = [w.strip(".,'") for w in _WORD_RE.findall(head)]
    return " ".join(w for w in words if w and w not in drop)


# ─────────────────────────────────────────
#  CONTACT FIELDS
# ─────────────────────────────────────────

_IG_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")
_IG_URL_RE = re.compile(r"instagram\.com/([A-Za-z0-9._]{1,30})", re.I)


def normalize_instagram(raw) -> Optional[str]:
    """'@Shop', 'instagram.com/shop/?hl=en' -> 'shop'. None if not a valid handle."""
    text = s(raw)
    if not text:
        return None
    if "instagram.com" in text.lower():
        m = _IG_URL_RE.search(text)
        if not m:
            return None
        text = m.group(1)
    handle = text.lstrip("@").strip().rstrip("/").lower()
    if not _IG_HANDLE_RE.match(handle) or handle in _IG_NON_PROFILE:
        return None
    if handle.startswith(".") or handle.endswith(".") or ".." in handle:
        return None
    # scraper leftovers: file names, domains, coordinates ('rsrc.php', 'shop.com', '34.716')
    if re.search(r"\.(?:php|js|css|png|jpe?g|gif|svg|html?|com|con|net|org|io|kr|co|uk|ca|au)$", handle):
        return None
    if re.fullmatch(r"[\d._]+", handle):
        return None
    return handle


# US geographic area codes and the state each belongs to. Scraped rows often
# carry made-up numbers: one whose area code does not exist, or belongs to
# Canada or the Caribbean, is not a US store's phone, and one from the wrong
# state is suspect until the store's own website confirms it (see refresh.py).
AREA_CODE_STATE = dict(pair.split(":") for pair in """
    201:NJ 202:DC 203:CT 205:AL 206:WA 207:ME 208:ID 209:CA 210:TX 212:NY 213:CA 214:TX
    215:PA 216:OH 217:IL 218:MN 219:IN 220:OH 223:PA 224:IL 225:LA 227:MD 228:MS 229:GA
    231:MI 234:OH 235:MO 239:FL 240:MD 248:MI 251:AL 252:NC 253:WA 254:TX 256:AL 260:IN
    262:WI 267:PA 269:MI 270:KY 272:PA 274:WI 276:VA 279:CA 281:TX 283:OH 301:MD 302:DE
    303:CO 304:WV 305:FL 307:WY 308:NE 309:IL 310:CA 312:IL 313:MI 314:MO 315:NY 316:KS
    317:IN 318:LA 319:IA 320:MN 321:FL 323:CA 324:FL 325:TX 326:OH 327:AR 329:NY 330:OH
    331:IL 332:NY 334:AL 336:NC 337:LA 339:MA 341:CA 346:TX 347:NY 350:CA 351:MA 352:FL
    353:WI 360:WA 361:TX 363:NY 364:KY 369:CA 380:OH 385:UT 386:FL 401:RI 402:NE 404:GA
    405:OK 406:MT 407:FL 408:CA 409:TX 410:MD 412:PA 413:MA 414:WI 415:CA 417:MO 419:OH
    423:TN 424:CA 425:WA 430:TX 432:TX 434:VA 435:UT 440:OH 442:CA 443:MD 445:PA 447:IL
    448:FL 458:OR 463:IN 464:IL 469:TX 470:GA 472:NC 475:CT 478:GA 479:AR 480:AZ 484:PA
    501:AR 502:KY 503:OR 504:LA 505:NM 507:MN 508:MA 509:WA 510:CA 512:TX 513:OH 515:IA
    516:NY 517:MI 518:NY 520:AZ 530:CA 531:NE 534:WI 539:OK 540:VA 541:OR 551:NJ 557:MO
    559:CA 561:FL 562:CA 563:IA 564:WA 567:OH 570:PA 571:VA 572:OK 573:MO 574:IN 575:NM
    580:OK 582:PA 585:NY 586:MI 601:MS 602:AZ 603:NH 605:SD 606:KY 607:NY 608:WI 609:NJ
    610:PA 612:MN 614:OH 615:TN 616:MI 617:MA 618:IL 619:CA 620:KS 623:AZ 626:CA 628:CA
    629:TN 630:IL 631:NY 636:MO 640:NJ 641:IA 645:FL 646:NY 650:CA 651:MN 656:FL 657:CA
    659:AL 660:MO 661:CA 662:MS 667:MD 669:CA 678:GA 680:NY 681:WV 682:TX 686:VA 689:FL
    701:ND 702:NV 703:VA 704:NC 706:GA 707:CA 708:IL 712:IA 713:TX 714:CA 715:WI 716:NY
    717:PA 718:NY 719:CO 720:CO 724:PA 725:NV 726:TX 727:FL 728:FL 730:IL 731:TN 732:NJ
    734:MI 737:TX 738:CA 740:OH 743:NC 747:CA 748:CO 754:FL 757:VA 760:CA 762:GA 763:MN
    765:IN 769:MS 770:GA 771:DC 772:FL 773:IL 774:MA 775:NV 779:IL 781:MA 785:KS 786:FL
    801:UT 802:VT 803:SC 804:VA 805:CA 806:TX 808:HI 810:MI 812:IN 813:FL 814:PA 815:IL
    816:MO 817:TX 818:CA 820:CA 821:SC 826:VA 828:NC 830:TX 831:CA 832:TX 835:PA 838:NY
    839:SC 840:CA 843:SC 845:NY 847:IL 848:NJ 850:FL 854:SC 856:NJ 857:MA 858:CA 859:KY
    860:CT 862:NJ 863:FL 864:SC 865:TN 870:AR 872:IL 878:PA 901:TN 903:TX 904:FL 906:MI
    907:AK 908:NJ 909:CA 910:NC 912:GA 913:KS 914:NY 915:TX 916:CA 917:NY 918:OK 919:NC
    920:WI 925:CA 928:AZ 929:NY 930:IN 931:TN 934:NY 936:TX 937:OH 938:AL 940:TX 941:FL
    943:GA 945:TX 947:MI 948:VA 949:CA 951:CA 952:MN 954:FL 956:TX 959:CT 970:CO 971:OR
    972:TX 973:NJ 975:MO 978:MA 979:TX 980:NC 983:CO 984:NC 985:LA 986:ID 989:MI
""".split())
TOLL_FREE_CODES = frozenset({"800", "833", "844", "855", "866", "877", "888"})
US_AREA_CODES = frozenset(AREA_CODE_STATE) | TOLL_FREE_CODES

# Brands whose presence on a store's own site says "this door sells what
# Godspeed sells". Generic words (Essentials, Palace, Jordan) are left out, and
# "Supreme" only counts next to another of these (see peer_brands).
PEER_BRANDS = [
    "Hellstar", "Rhude", "Vale Forever", "Denim Tears", "Sp5der", "Gallery Dept",
    "Fear of God", "Off-White", "BAPE", "Amiri", "Chrome Hearts", "Stussy", "Kith",
    "Supreme",
]
_PEER_BY_KEY = {re.sub(r"[^a-z0-9]", "", b.lower()): b for b in PEER_BRANDS}


def peer_brands(names: Iterable[str]) -> list[str]:
    """The peer brands among `names`, in PEER_BRANDS order. Supreme alone does not count."""
    found = {_PEER_BY_KEY.get(re.sub(r"[^a-z0-9]", "", s(n).lower())) for n in names} - {None}
    if found == {"Supreme"}:
        return []
    return [b for b in PEER_BRANDS if b in found]


def normalize_phone(raw) -> Optional[str]:
    """Any US formatting -> 10 digits. None if it is not a dialable US number."""
    text = s(raw)
    if not text:
        return None
    text = re.split(r"(?i)\s*(?:ext\.?|x)\s*\d+\s*$", text)[0]
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    if digits[0] in "01" or digits[3] in "01":      # invalid area code / exchange
        return None
    if len(set(digits)) == 1 or digits[3:6] == "555":
        return None
    if digits[:3] not in US_AREA_CODES:
        return None
    return digits


def format_phone(digits: str) -> str:
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def normalize_website(raw) -> Optional[str]:
    """'shop.com' -> 'https://shop.com'. None if it is not a URL."""
    text = s(raw)
    if not text or " " in text or "@" in text.split("/")[0]:
        return None
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text.lstrip("/")
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(:\d+)?$", host):
        return None
    return text


def website_domain(raw) -> Optional[str]:
    url = normalize_website(raw)
    if not url:
        return None
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_social_link(raw) -> bool:
    domain = website_domain(raw)
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in SOCIAL_DOMAINS)


def instagram_status(raw) -> str:
    if not s(raw):
        return "empty"
    return "format-ok" if normalize_instagram(raw) else "invalid-format"


def phone_status(raw) -> str:
    text = s(raw)
    if not text or text.startswith("#"):          # '#ERROR!' cells count as empty
        return "empty"
    return "format-ok" if normalize_phone(text) else "invalid-format"


def website_status(raw) -> str:
    if not s(raw):
        return "empty"
    if not normalize_website(raw):
        return "invalid-format"
    return "social-link" if is_social_link(raw) else "format-ok"


# ─────────────────────────────────────────
#  FIT CLASSIFICATION
# ─────────────────────────────────────────

TEXT_FIELDS = ("Store Name", "Notes", "Website", "Instagram")

# Words too generic to prove that a name and a website belong together.
_GENERIC_NAME_WORDS = {
    "store", "stores", "shop", "shops", "clothing", "clothes", "apparel",
    "boutique", "sneaker", "sneakers", "streetwear", "fashion", "mens", "men",
    "womens", "women", "wear", "official", "online", "home", "best", "with",
    "from", "your", "more", "sale", "outlet", "collection", "collections",
    "brand", "brands", "company", "supply", "the", "and", "for", "new", "usa",
    "luxury", "designer", "vintage", "premium", "shoes", "tees", "hoodie",
    "hoodies", "shirt", "shirts", "available", "location", "locations",
    "hellstar", "supreme", "rhude", "vale", "forever", "sp5der", "bape",
    "essentials", "jordan", "nike", "adidas", "yeezy", "kith", "stussy",
}


HOSTED_PLATFORMS = (
    "square.site", "myshopify.com", "bigcartel.com", "wixsite.com",
    "squarespace.com", "business.site", "weebly.com", "godaddysites.com",
    "shopify.com", "carrd.co", "webflow.io", "storenvy.com",
)


def site_keys(row: dict) -> list[str]:
    """Compact identifiers of the row's own web presence: ['solefly', 'solefly']."""
    keys = []
    if not is_social_link(row.get("Website")):
        domain = website_domain(row.get("Website"))
        if domain:
            for host in HOSTED_PLATFORMS:               # shop.square.site -> shop
                if domain.endswith("." + host):
                    domain = domain[: -len(host) - 1] + ".x"
                    break
            labels = domain.split(".")
            # drop the public suffix: shop.co.uk -> shop, locations.dtlr.com -> dtlr
            core = labels[:-2] if len(labels) > 2 and len(labels[-2]) <= 3 and len(labels[-1]) == 2 else labels[:-1]
            if core:
                keys.append(re.sub(r"[^a-z0-9]", "", core[-1]))
    handle = normalize_instagram(row.get("Instagram"))
    if handle:
        keys.append(re.sub(r"[^a-z0-9]", "", handle))
    return [k for k in keys if len(k) >= 3]


def name_matches_site(row: dict, name: Optional[str] = None) -> Optional[bool]:
    """
    Does the store name belong to the website / Instagram on its row?
    None when the row has neither (nothing to compare against).
    """
    keys = site_keys(row)
    if not keys:
        return None
    name = s(row.get("Store Name")) if name is None else name
    compact = re.sub(r"[^a-z0-9]", "", _norm(name))
    words = [w for w in re.findall(r"[a-z0-9]+", _norm(name).replace("'", ""))]
    city_words = set(re.findall(r"[a-z0-9]+", _norm(s(row.get("City")))))
    strong = [w for w in words if len(w) >= 4 and w not in _GENERIC_NAME_WORDS and w not in city_words]
    acronym = "".join(w[0] for w in words)[:3]
    for key in keys:
        if len(compact) >= 4 and (compact in key or key in compact):
            return True
        if any(w in key for w in strong):
            return True
        if len(acronym) >= 3 and key.startswith(acronym):
            return True
        shared = 0
        for a, b in zip(compact, key):
            if a != b:
                break
            shared += 1
        if shared >= 6:                                # "94 Vintage•Sneakers" / 94vintagestore
            return True
        # short distinctive names: "HYP Miami" / hypmiami, "Tons" / tons-shop
        if words and len(words[0]) >= 3 and key.startswith(words[0]) and words[0] not in _GENERIC_NAME_WORDS:
            return True
    return False


# Stores held out by a business decision rather than by a rule. Lower-case
# names; remove a line and press Rebuild to bring the store back.
EXCLUDED_STORES = {
    "backdoor miami": "held out for now — not a confirmed account, Miami is saturated",
}


def classify(row: dict, locations: int = 1) -> tuple[str, list[str]]:
    """
    Returns (flag, reasons). `locations` is how many rows in the database share
    this store's website or Instagram (see count_locations).
    """
    name = s(row.get("Store Name"))
    if len(name) < 2 or name.upper() in ("N/A", "NA", "UNDEFINED", "NULL", "NONE"):
        return "broken-data", ["missing or invalid store name"]

    lname = _norm(name)
    flags: list[str] = []
    reasons: list[str] = []

    def add(flag: str, reason: str):
        if flag not in flags:
            flags.append(flag)
            reasons.append(reason)

    carries_godspeed = s(row.get("Carries Godspeed")).lower() in ("yes", "true", "1", "y")

    for excluded, why in EXCLUDED_STORES.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(excluded) + r"(?![a-z0-9])", lname):
            add("excluded", why)

    m = _CHAIN_RE.search(lname)
    if m:
        add("chain", f"chain: '{m.group(0)}'")

    m = _PREFIX_RE.search(lname)
    if m:
        add("mono-brand", f"brand's own store: '{m.group(0).strip()}'")

    core = _core_name(name, s(row.get("City")), s(row.get("State")))
    if core in EXACT_ONLY:
        add(EXACT_ONLY[core], f"{'chain' if EXACT_ONLY[core] == 'chain' else 'brand store'}: '{core}'")

    if locations >= CHAIN_LOCATION_THRESHOLD:
        add("chain", f"{locations} locations share its website/Instagram")

    m = _JUNK_RE.search(lname)
    if m:
        add("junk", f"not a clothing retailer: '{m.group(0)}'")

    for flag, reason in name_flags(name) + website_flags(row):
        add(flag, reason)

    if name_matches_site(row) is False:
        add("mismatch", "name doesn't match its website/Instagram — looks like a search result, not a store")

    text = _norm(" ".join(s(row.get(f)) for f in TEXT_FIELDS))
    compact = _norm(" ".join(s(row.get(f)) for f in ("Store Name", "Website", "Instagram")))
    notes = _norm(s(row.get("Notes")))
    has_signal = (bool(_SIGNAL_RE.search(text))
                  or any(c in compact for c in COMPOUND_SIGNALS)
                  or bool(_BRAND_SIGNAL_RE.search(notes)))
    if not carries_godspeed and not has_signal:
        add("low-fit", "no streetwear signal in name, notes, website or Instagram")

    return ("+".join(flags) if flags else "OK"), reasons


def count_locations(rows: list[dict]) -> list[int]:
    """For each row, how many rows share its website domain or Instagram handle."""
    domains = Counter()
    handles = Counter()
    keys = []
    for row in rows:
        d = None if is_social_link(row.get("Website")) else website_domain(row.get("Website"))
        h = normalize_instagram(row.get("Instagram"))
        keys.append((d, h))
        if d:
            domains[d] += 1
        if h:
            handles[h] += 1
    return [max(domains.get(d, 1) if d else 1, handles.get(h, 1) if h else 1) for d, h in keys]


def is_qualified(flag: str) -> bool:
    return flag == "OK"


# ─────────────────────────────────────────
#  WEBSITE-BASED RULES
#  The scraped rows often have a useless page title for a name, so the website
#  a row points at is the most reliable evidence of what it really is.
# ─────────────────────────────────────────

CHAIN_DOMAINS = {
    "dtlr.com", "finishline.com", "hibbett.com", "shoepalace.com", "jdsports.com",
    "footlocker.com", "champssports.com", "footaction.com", "hottopic.com",
    "citygear.com", "cititrends.com", "culturekings.com", "hollisterco.com",
    "abercrombie.com", "saksfifthavenue.com", "saksoff5th.com", "dillards.com",
    "nordstrom.com", "nordstromrack.com", "macys.com", "bloomingdales.com",
    "neimanmarcus.com", "zumiez.com", "urbanoutfitters.com", "walmart.com",
    "target.com", "rallyhouse.com", "stadiumgoods.com", "flightclub.com",
    "impossiblekicks.com", "snipesusa.com", "shiekh.com", "jimmyjazz.com",
    "pacsun.com", "tillys.com", "journeys.com", "dsw.com", "famousfootwear.com",
    "shoecarnival.com", "ae.com", "gap.com", "oldnavy.com", "hm.com", "zara.com",
    "uniqlo.com", "forever21.com", "platoscloset.com", "buffaloexchange.com",
    "uptowncheapskate.com", "lids.com", "buckle.com", "dickssportinggoods.com",
    "academy.com", "kohls.com", "jcpenney.com", "tjmaxx.tjx.com", "tjmaxx.com",
    "marshalls.com", "burlington.com", "rossstores.com", "kith.com", "goat.com",
    "stockx.com", "simon.com", "villa.com", "ruvilla.com", "expressurbanwear.com",
    "rh.com", "verabradley.com", "bootbarn.com", "popshelf.com", "gamestop.com",
    "fleetfeet.com", "fit2run.com", "modells.com", "shopwss.com", "overland.com",
    "harborfreight.com", "7-eleven.com", "starbucks.com", "nothingbundtcakes.com",
    "budgetblinds.com", "onepeloton.com", "trekbikes.com",
}

BRAND_DOMAINS = {
    "rh-ude.com", "rhude.com", "hellstar.com", "supreme.com", "supremenewyork.com",
    "valeforever.com", "stussy.com", "noahny.com", "louisvuitton.com", "dior.com",
    "gucci.com", "prada.com", "balenciaga.com", "nike.com", "adidas.com",
    "jordan.com", "puma.com", "newbalance.com", "converse.com", "vans.com",
    "reebok.com", "asics.com", "underarmour.com", "lululemon.com", "bape.com",
    "us.bape.com", "off---white.com", "fearofgod.com", "amiri.com",
    "chromehearts.com", "palaceskateboards.com", "carhartt-wip.com",
    "carhartt.com", "denimtears.com", "gallerydept.com", "kingspider.co",
    "sp5der.com", "essentials.com", "asrv.com", "thehundreds.com",
    "bbcicecream.com", "aimeleondore.com", "levi.com", "ralphlauren.com",
    "tommy.com", "calvinklein.us", "lacoste.com", "truereligion.com",
    "patagonia.com", "thenorthface.com", "columbia.com", "octobersveryown.com",
    "representclo.com", "ericemanuel.com", "godspeednewyork.com",
    "rhone.com", "jamesperse.com", "jacquemus.com", "rickowens.eu",
    "goldengoose.com", "valentino.com", "buckmason.com", "mizzenandmain.com",
    "lafayette148ny.com", "roddandgunn.com",
}

# Media, marketplaces, directories, maps, social: a row pointing here is a
# search result, not a store.
NOT_STORE_DOMAINS = {
    "hypebeast.com", "highsnobiety.com", "complex.com", "gq.com", "vogue.com",
    "timeout.com", "nextdoor.com", "linkedin.com", "wanderlog.com", "yelp.com",
    "tripadvisor.com", "reddit.com", "quora.com", "medium.com", "ebay.com",
    "amazon.com", "etsy.com", "poshmark.com", "depop.com", "grailed.com",
    "mercari.com", "fivestars.com", "yellowpages.com", "mapquest.com",
    "foursquare.com", "apple.com", "google.com", "bing.com", "wikipedia.org",
    "designscene.net", "greyhound.com", "facebook.com", "tiktok.com",
    "youtube.com", "twitter.com", "x.com", "pinterest.com", "threads.net",
    "bbb.org", "chamberofcommerce.com", "manta.com", "loc8nearme.com",
    "shopify.com", "faire.com", "joor.com", "thrillist.com", "eater.com",
    "sneakernews.com", "solecollector.com", "nicekicks.com", "footwearnews.com",
    "wwd.com", "businessinsider.com", "forbes.com", "nytimes.com", "latimes.com",
    "miaminewtimes.com", "visitflorida.com", "aadl.org", "issuu.com",
    "scribd.com", "glassdoor.com", "indeed.com", "ziprecruiter.com",
    "cylex.us.com", "cylex-usa.com", "storefound.org", "mallscenters.com",
    "outletbound.com", "shopping-canada.com", "placer.ai",
    # delivery, listings, business data, stock photos, jobs
    "leafly.com", "weedmaps.com", "postmates.com", "doordash.com", "ubereats.com",
    "trustpilot.com", "dnb.com", "homeadvisor.com", "zillow.com", "realtor.com",
    "homes.com", "bizprofile.net", "rocketreach.co", "procore.com",
    "gettyimages.com", "alamy.com", "cbre.com", "joincheckmate.com", "shop.app",
    "locally.com", "store2be.com", "hypemaps.com", "attic.city", "mindtrip.ai",
    "encyclopedia.com", "fanac.org", "idahogeology.org",
    # media and guides
    "yahoo.com", "elle.com", "adweek.com", "substack.com", "lemon8-app.com",
    "metrotimes.com", "tulsapeople.com", "405magazine.com", "bocamag.com",
    "insidehook.com", "secretmiami.com", "thescoutguide.com", "unation.com",
    "thespaces.com", "trippin.world", "fashionsauce.com", "backwardfashion.com",
    "culturehoney.com", "newyorksocialdiary.com", "littlerocksoiree.com",
    "greaterseattleonthecheap.com", "luxiere.co", "nbktimes.com",
    "theghettoflower.com", "thelocalartisanguide.com", "atriummag.org",
    # online-only retailers and resale sites
    "mrporter.com", "endclothing.com", "giglio.com",
    # companies that are not clothing retailers
    "garmin.com", "suunto.com", "rivian.com", "valero.com", "valley.com",
    "ecolab.com", "shimano.com", "thalesgroup.com", "masonite.com",
    "baxterhealthcare.com.au", "carrier.com", "volvoce.com", "vcahospitals.com",
    "vale.com", "valetliving.com", "sixflags.com", "valehealthykitchen.com",
    "valepainting.com", "cadex-cycling.com", "fabricut.com",
}

GENERIC_PAGE_TITLES = {
    "stockists", "stockist", "contact us", "contact", "shop all", "shop",
    "store locator", "stores", "store", "faq", "faqs", "products", "product",
    "home", "homepage", "about us", "about", "locations", "our stores",
    "collections", "all products", "new arrivals", "sale", "men", "women",
    "mens", "womens", "clothing", "sneakers", "shoes", "apparel", "search",
    "cart", "login", "account", "blog", "news", "careers", "press", "terms",
    "privacy policy", "returns", "shipping", "instagram", "facebook",
    "page not found", "404", "untitled", "welcome", "menu", "retailers",
    "find a store", "where to buy", "wholesale", "gift cards",
}

_ARTICLE_PATH_RE = re.compile(
    r"/(?:20\d\d/\d{1,2}/|blog/|blogs/|news/|article/|articles/|magazine/|"
    r"guide/|guides/|story/|stories/|wiki/|best-|top-\d+)", re.I)
_LISTICLE_RE = re.compile(
    r"^(?:the\s+)?(?:\d+\s+)?(?:best|top)\s+(?:\d+\s+)?\S+.*\b(?:in|near|of)\b", re.I)
_ARTICLE_TITLE_RE = re.compile(
    r"^\d+\s+\S.*\b(?:brands|stores|shops|boutiques|places|spots|things)\b"
    r"|\b(?:where to (?:shop|buy)|guide to|you (?:must|should|need to)|things to do|"
    r"reviews?$|how to|a look inside|take a look|opens? in|opening in|is now open|"
    r"now open|coming soon|grand opening)\b", re.I)
_FILE_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|png|jpe?g|gif)$", re.I)
_IG_POST_RE = re.compile(
    r"instagram\.com/(?:(?:p|reel|reels|tv|explore|stories|popular|locations|tags)/|[^/?#]+/(?:p|reel|reels)/)", re.I)
# Sites named after a hype brand ("blackhellstarhoodie.com") are unofficial
# single-brand web shops, not multi-brand retailers.
_BRAND_SQUAT_RE = re.compile(
    r"hellstar|sp5der|spider-?hoodie|rhude|valeforever|denimtears|gallerydept|"
    r"chromehearts|essentialshoodie|corteiz|bapehoodie|trapstar|syna-?world")
_PLACE_RE = re.compile(
    r"(?<![a-z])(?:mall|shops at|shopping center|shopping centre|outlets|town center|"
    r"tourism|chamber of commerce|visitors bureau|farmers market|flea market)(?![a-z])")
_CAPTION_RE = re.compile(r"(?i)\bdm (?:me|us)\b|!!!|#\w+.*#\w+|\blink in bio\b")


def _domain_in(domain: Optional[str], group: set) -> bool:
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in group)


def website_flags(row: dict) -> list[tuple[str, str]]:
    """Flags derived from the Website cell: [(flag, reason), ...]."""
    raw = s(row.get("Website"))
    out: list[tuple[str, str]] = []
    if not raw:
        return out
    if _IG_POST_RE.search(raw):
        out.append(("not-a-store", "website is an Instagram post, not a store"))
        return out
    domain = website_domain(raw)
    if domain and domain.endswith(".gov"):
        out.append(("not-a-store", f"government website: {domain}"))
    elif _domain_in(domain, CHAIN_DOMAINS):
        out.append(("chain", f"chain website: {domain}"))
    elif _domain_in(domain, BRAND_DOMAINS):
        out.append(("mono-brand", f"brand's own website: {domain}"))
    elif _domain_in(domain, NOT_STORE_DOMAINS):
        out.append(("not-a-store", f"media / marketplace / directory page: {domain}"))
    elif _BRAND_SQUAT_RE.search(domain or ""):
        out.append(("mono-brand", f"single-brand web shop: {domain}"))
    elif _ARTICLE_PATH_RE.search(urlparse(normalize_website(raw) or "").path or ""):
        out.append(("not-a-store", "website is an article or blog page"))
    return out


def name_flags(name: str) -> list[tuple[str, str]]:
    """Flags for names that are page titles or post captions rather than stores."""
    lname = _norm(name)
    if lname.strip(" .:-|") in GENERIC_PAGE_TITLES:
        return [("not-a-store", f"name is a page title: '{name}'")]
    if _FILE_RE.search(lname):
        return [("not-a-store", "name is a file, not a store")]
    if _LISTICLE_RE.search(lname) or _ARTICLE_TITLE_RE.search(lname):
        return [("not-a-store", "name is an article or listing title, not a store")]
    if _PLACE_RE.search(re.split(r"[(\[]", lname)[0]):
        return [("not-a-store", "name is a mall, market or tourism page, not a store")]
    if len(name) > 80 or _CAPTION_RE.search(name):
        return [("not-a-store", "name is a caption or page text, not a store name")]
    return []


# ─────────────────────────────────────────
#  EMAIL / STATE
# ─────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-z0-9][a-z0-9._%+-]*@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}$")
_EMAIL_JUNK_RE = re.compile(
    r"(?:\.(?:png|jpe?g|gif|svg|webp|js|css|ico)$|@\dx|@\d|sentry|wixpress|"
    r"example\.|domain\.com|email\.com$|yourname|your-?email|john\.?doe|"
    r"jane\.?doe|noreply|no-reply|test@|user@|name@)", re.I)


def normalize_email(raw) -> Optional[str]:
    text = s(raw).lower().rstrip(".,;")
    if text.startswith("mailto:"):
        text = text[7:]
    if not _EMAIL_RE.match(text) or _EMAIL_JUNK_RE.search(text):
        return None
    return text


US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}
_US_ABBR = set(US_STATES.values())


def normalize_state(raw) -> str:
    text = s(raw)
    if text.lower() in US_STATES:
        return US_STATES[text.lower()]
    if text.upper() in _US_ABBR:
        return text.upper()
    return text


def is_us_state(state: str) -> bool:
    return state in _US_ABBR


# ─────────────────────────────────────────
#  LEAD SCORE  (Goldie's weights from score_leads.py)
# ─────────────────────────────────────────

BRAND_POINTS = [
    ("hellstar", "Hellstar", 25), ("rhude", "Rhude", 20),
    ("vale forever", "Vale Forever", 20), ("supreme", "Supreme", 15),
    ("denim tears", "Denim Tears", 15), ("sp5der", "Sp5der", 15),
    ("gallery dept", "Gallery Dept", 15),
]


def score(row: dict) -> tuple[int, str, list[str]]:
    """Returns (score, tier, brands). Contact points only count validated fields."""
    text = _norm(" ".join(s(row.get(f)) for f in ("Store Name", "Notes")))
    points = 0
    brands = []
    for needle, label, pts in BRAND_POINTS:
        if needle in text:
            points += pts
            brands.append(label)
    if normalize_instagram(row.get("Instagram")):
        points += 10
    if normalize_email(row.get("Email")):
        points += 10
    if normalize_phone(row.get("Phone")):
        points += 5
    if normalize_website(row.get("Website")) and not is_social_link(row.get("Website")):
        points += 5
    tier = "Hot" if points >= 40 else "Strong" if points >= 20 else "Warm" if points >= 1 else "Cold"
    return points, tier, brands


# ─────────────────────────────────────────
#  REVIEW BUCKETS  (what the dashboard shows)
# ─────────────────────────────────────────

UNCERTAIN_FLAGS = {"low-fit", "mismatch"}


def bucket(flag: str, review: str = "") -> str:
    """
    qualified  ready to pitch
    review     looks like a real store but nothing confirms the fit yet
    rejected   chain / brand store / not a store
    A person's decision in the Review column ('Approved' / 'Rejected') always wins.
    """
    decision = s(review).lower()
    if decision.startswith("approv"):
        return "qualified"
    if decision.startswith("reject"):
        return "rejected"
    parts = set(s(flag).split("+")) if s(flag) else {"OK"}
    if parts == {"OK"}:
        return "qualified"
    if parts <= UNCERTAIN_FLAGS:
        return "review"
    return "rejected"
