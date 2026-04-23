"""
Wilmar Barrios -- Godspeed Master Database Cleaner
Cleans MASTER DATABASE sheet -> master_clean.csv
"""

import csv
import re
import os
from collections import defaultdict

INPUT_CSV  = '/Users/elbarrio/.openclaw/workspace/godspeed-dashboard/data/raw_master.csv'
OUTPUT_CSV = '/Users/elbarrio/.openclaw/workspace/godspeed-dashboard/data/master_clean.csv'
REPORT_MD  = '/Users/elbarrio/.openclaw/workspace/godspeed-dashboard/data/wilmar-clean-report.md'

# ----------------------------------------------------------------
# TERRITORY MAP
# ----------------------------------------------------------------
TERRITORY_MAP = {
    'FL':'Southeast','GA':'Southeast','NC':'Southeast','SC':'Southeast',
    'TN':'Southeast','AL':'Southeast','MS':'Southeast','LA':'Southeast','AR':'Southeast',
    'NY':'Northeast','NJ':'Northeast','CT':'Northeast','MA':'Northeast',
    'RI':'Northeast','VT':'Northeast','NH':'Northeast','ME':'Northeast',
    'PA':'Northeast','DE':'Northeast','MD':'Northeast','DC':'Northeast',
    'OH':'Midwest','MI':'Midwest','IN':'Midwest','IL':'Midwest',
    'WI':'Midwest','MN':'Midwest','IA':'Midwest','MO':'Midwest',
    'ND':'Midwest','SD':'Midwest','NE':'Midwest','KS':'Midwest',
    'TX':'Southwest','OK':'Southwest','NM':'Southwest','AZ':'Southwest',
    'CA':'West','NV':'West','OR':'West','WA':'West',
    'ID':'West','MT':'West','WY':'West','CO':'West','UT':'West',
    'VA':'Mid-Atlantic','WV':'Mid-Atlantic','KY':'Mid-Atlantic',
    'HI':'West','AK':'West',
}

STATE_NAME_TO_ABBR = {
    'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA',
    'colorado':'CO','connecticut':'CT','delaware':'DE','florida':'FL','georgia':'GA',
    'hawaii':'HI','idaho':'ID','illinois':'IL','indiana':'IN','iowa':'IA','kansas':'KS',
    'kentucky':'KY','louisiana':'LA','maine':'ME','maryland':'MD','massachusetts':'MA',
    'michigan':'MI','minnesota':'MN','mississippi':'MS','missouri':'MO','montana':'MT',
    'nebraska':'NE','nevada':'NV','new hampshire':'NH','new jersey':'NJ',
    'new mexico':'NM','new york':'NY','north carolina':'NC','north dakota':'ND',
    'ohio':'OH','oklahoma':'OK','oregon':'OR','pennsylvania':'PA','rhode island':'RI',
    'south carolina':'SC','south dakota':'SD','tennessee':'TN','texas':'TX','utah':'UT',
    'vermont':'VT','virginia':'VA','washington':'WA','west virginia':'WV',
    'wisconsin':'WI','wyoming':'WY','district of columbia':'DC',
}

KNOWN_COUNTRIES = {
    'usa','us','united states','u.s.a.','u.s.','canada','france','japan',
    'south korea','korea','netherlands','australia','italy','united kingdom',
    'uk','russia','germany','spain','israel','hong kong','dominican republic',
    'brazil','mexico','belgium','switzerland','austria','sweden','denmark',
    'norway','finland','new zealand','singapore','uae','china',
}

# ----------------------------------------------------------------
# CHAIN PATTERNS (regex, case-insensitive)
# ----------------------------------------------------------------
CHAIN_PATTERNS = [
    r'\bdtlr\b', r'\bsnipes\b', r'\bshoe gallery\b', r'\bfoot locker\b',
    r'\bbanana\s+republic\b', r'\bgamestop\b',
    r'\bfinish line\b', r'\bchamps sports\b', r'\bjd sports\b',
    r"dick'?s sporting", r'\bdicks sporting\b', r'\bacademy sports\b',
    r'\bhibbett\b', r'\bfootaction\b', r'\bshoe carnival\b',
    r'\bshoe palace\b', r'\bnike store\b', r'\bnike factory\b',
    r'\bnike\s+redmond\b', r'\bnike\s+town\b',
    r'\badidas store\b', r'\bnordstrom\b', r'\bbloomingdale\b',
    r'\bneiman marcus\b', r'\bsaks fifth\b', r'\bsaks houston\b',
    r'\bbarneys\b', r"\bdillard'?s?\b", r'\bmacy\b', r'\btarget\b',
    r'\bwalmart\b', r'\bross store\b', r'\btj maxx\b', r'\bmarshalls\b',
    r'\burban outfitters\b', r'\bzumiez\b', r'\bpacsun\b',
    r'\bforever 21\b', r'\bh&m\b', r'\bzara\b', r'\buniqlo\b',
    r'\bthe gap\b', r'\bold navy\b', r'\bstadium goods\b',
    r'\bculture kings\b', r'\bkith\b', r'\bthe real real\b',
    r'\btherealreal\b', r'\bssense\b', r'\bdover street market\b',
    r'\bbape store\b',  # BAPE flagship = brand, not a boutique
    r'\bflight club\b',  # consignment, not a wholesale boutique
    r'\bundefeated\b',   # brand-affiliated chain
]

# ----------------------------------------------------------------
# CAR / NON-APPAREL PATTERNS
# ----------------------------------------------------------------
NON_APPAREL_BUSINESS_PATTERNS = [
    r'\bhair\s+(&\s+)?beauty\b',
    r'\bbeauty\s+supply\b',
    r'\bbarber\b',
    r'\bsalon\b',
    r'\bnail\s+(bar|salon|spa)\b',
    r'\bdental\b',
    r'\bclinic\b',
    r'\bpharmacy\b',
    r'\bfitness\b(?!\s+brand)',
    r'\byoga\b',
    r'\btatoo\b',
    r'\btattoo\b',
    r'\bhealthy\s+kitchen\b',
    r'\bclasspass\.com\b',
    r'\bvagaro\.com\b',
    r'\biruntexas\b',
    r'\brunning\s+(store|shop|club)\b',
    r'\bthespaces\.com\b',
    r'^peek\s+inside\b',
    r'^in-store\s+and\s+always\s+online\b',
    r'#\d{4}space\b',
]

CAR_PATTERNS = [
    r'\bdealership\b', r'\bchevrolet\b', r'\bnissan\b', r'\bgmc\b',
    r'\bford\b(?!\s+worth)',  # "Ford Worth" is a city typo but "Ford" dealer is bad
    r'\btoyota\b', r'\bhonda\b', r'\bbmw\b', r'\bmercedes\b',
    r'\bvolkswagen\b', r'\bhyundai\b', r'\bkia\b', r'\bdodge\b',
    r'\bchrysler\b', r'\bjeep\b', r'\bsubaru\b', r'\bmazda\b',
    r'\blexus\b', r'\bacura\b', r'\bvolvo\b', r'\baudi\b',
    r'\bporsche\b', r'\bbuick\b', r'\bcadillac\b',
    r'\bauto\s+group\b', r'\bcar\s+dealer\b',
    r'\bauto\s*[&+]\s*finance', r'\bsupreme\s+auto\b',
]

# ----------------------------------------------------------------
# JUNK NAME PATTERNS
# ----------------------------------------------------------------
# These identify scraper artifacts: web page titles, IG post captions, etc.
JUNK_NAME_PATTERNS = [
    # Brand website pages
    r'^hellstar\s*[-|]',
    r'^rhude\s*[-|]',
    r'^r\s+h\s+u\s+d\s+e\s*$',
    r'^stockists\s*$',
    r'^stockists\s*[-\u2013]',
    r'^shop\s+hellstar',
    r'^shop\s+rhude',
    r'^products\s*[-\u2013]',
    r'^shop\s?all\s*$',
    r'^buy\s+hellstar',
    r'^official\s+hellstar',
    r'^hellstar\s+official',
    r'^hellstar\s+clothing\s*$',
    r'^hellstar\s+studios\s*$',
    r'^hell\s+star\s*$',
    r'^from\s+@',
    r'prnewswire',
    r'discoverlosangeles',
    r'trippin\.world',
    r'offerup\.com',
    r'^\d+\s+days\s+of\s+streetwear',
    r"^toreno'?s\s+top",
    r'^shops\s*[-\u2013]',
    r"^men'?s\s+rhude",
    r'^rhude\s+men\b',
    r'^rhude\s+t-?shirt',
    r'^rhude\s+archives?\s*$',
    r'^rhude\s+stores?\s+in\b',
    r'^hellstar\s+miami\s+boutiques',
    r'^hellstar\s+streetwear\b',
    r'^hellstar\s*\|',
    r'^vale\s+forever\s*[-|]',
    r'^vale\s+forever\s+stores',
    r'^supreme\s+in\s+',
    r'^supreme\s+store\s',
    r'^complex\s*&\s*espn',
    # IG post captions / social posts
    r'available\s+now[!]',
    r'just\s+dropped',
    r'just\s+arrived',
    r'just\s+touched\s+down',
    r'just\s+landed',
    r'just\s+restocked',
    r'^new\s+(season|arrival|item)\s+',
    r'^just\s+in\s+new\s+season',
    r'available\s+in[-\s]?store\s*[&+]',
    r'in\s+store\s*[&+]\s*online',
    r'sizes?\s+available',
    r'under\s+retail',
    r'^rhude\s+tee',
    r'^rhude\s+shirt',
    r'for\s+sale\s+in\s+\w+,\s*\w{2}\b',  # "for sale in City, ST"
    r'\bopen\s+from\s+\d',
    r'\bweekdays\b',
    r'in\s+stock[!\u2757]',
    r'^new\s+arrivals?\s+from\s+@',
    r'new\s+items?\s+from\s+rhude',
    r'new\s+season\s+rhude',
    r'^saks\s+(houston|nyc|chicago|fifth|new york)',
    r'@offerup',
    r'^#hellstar\b',
    r'best\s+reseller\s+in',
    r'are\s+here\s+[^\w]',
    r'now\s+in\s*stock[!\u2757]',
    r'most\s+sizes\s+available',
    # Wikipedia / editorial content
    r'wikipedia',
    r'hypebeast\s*magazine',
    r'sneaker\s*news',
    r'complex\s+magazine',
    r'grailed\.com',
    r'goat\s*app',
    r'\bstockx\b',
    r'\bgoat\b\s+sneakers',
    # Product listings (individual items, not stores)
    r'^hellstar\s+(star|logo|records|classic|powered|flame|inner\s*peace|tee|t-?shirt|hoodie|hat|shorts|sweatpants|jacket|pants|shirt|black|white|green|blue|red|purple|cream|grey|gray|men|baseball|rkive|screaming)',
    r'^vale\s+forever\s+(clothing|hoodie|tee|t-?shirt|discount|authentic|official|about|contact)',
    r'brand\s+new\s+(red|blue|black|white|green|hellstar)',
    r'\bds\s+brand\s+new\b',
    r'size\s+[sml]\b',
    r'\bsize\s+(small|medium|large|xl|xxl)\b',
    r'\bnfc\b',
    r"men'?s\s+t-?shirt\s+size",
    r'graphic\s+t\s+shirt\s+men',
    r'men\'?s\s+xl\b',
    r'\bwaferz\s+x\s+hellstar\b',
    # Contact / About pages
    r'^contact\s+us\b',
    r'^about\s+us\b',
    r'^contact\s+[-|]',
    r'customer\s+support\s*[&]?\s*store',
    r'customer\s+support\s*[&]?\s*inquir',
    # Blog / editorial / article titles
    r'^the\s+(best|most\s+popular)\s+(streetwear|sneaker)',
    r'^explore\s+these\s+\d+',
    r'^where\s+to\s+shop\s+(local|clothing)',
    r'your\s+guide\s+to\b',
    r'luxury\s+shopping\s+guide',
    r'shopping\s+guide\s*$',
    r'boutiques?\s*\|?\s*blog',
    r'^what\s+stores\s+sell',
    r'^find\s+(a|your)\s+local',
    r'near\s+you\s*$',
    r'^\d+\s+(streetwear|sneaker|boutique)\s+(stores?|shops?)',
    # IG account pages
    r'\(@\w+\)\s*[\u2022\u00b7]',
    r'instagram\s+photos\s+and\s+videos',
    # Mall / directory / aggregator entries
    r'\bwestfield\s+\w+',
    r'^brands\s+[|]\s+the\s+summit',
    r'\bshopsimon\b',
    r'^the\s+oaks\s+mall',
    r'^\w+\s+commercial\s+real\s+estate',
    # Resale / marketplace
    r'\bofferup\b',
    r'\bposhmark\b',
    r'\bdepop\b',
    # Non-apparel businesses
    r'\bcannabis\s+(co|club)\b',
    r'\bdispensary\b',
    r'insurance\s+commissioner',
    r'^careers\s+at\b',
    r'^newsletter\b',
    r'\bpainting\s+company\b',
    r'\btrailer\s+sales\b',
    r'\bwhataburger\b',
    r'\bsoccer\s+club\b',
    r'\bu\.?s\.?\s+bank\b',
    r'\bcadex\b',
    r'\bchristmas\s+wonderland\b',
    r'^vale\s+(soccer|cannabis|matcha|painting|group\s+llc)',
    r'^vale\s+forever\s+(discount|about|contact|clothing\s+official)',
    r'\bcraft\s+cannabis\b',
    r'\boutdoor\s+gear\s+shop\b',
    r'\bbudget\s+blinds\b',
    r'^peloton\b',
    r'\bthrift\s+store\b',
    r'^love\s+supreme\s+craft\b',
    r'^vale\s+matcha\b',
    r'\brunning\s+store\b',
    r'\bfit2run\b',
    r'^rosenblum\'?s\b',  # luxury menswear, not streetwear
    r'^lloyd\s+clarke\s+sport\b',  # sports not streetwear
    r'^hialeah\s+commercial\b',
    r'water\s+(district|authority)',
    r'savings?\s+and\s+sustain',
    r'\bmasonite\b',
    r'^rick\s+owens\s*[|]\s*official',
    # Tagline pipes
    r'[|]\s*(shop\s+now|find\s+out|learn\s+more|your\s+one\s+stop|all\s+things|city)\s*$',
    r'^new\s+york\s+[|]\s+city\s*$',
    r'^cookies\s+clothing\s*[|]\s*retailers',
    r'^supreme\s+[|]\s+your\s+guide',
    # Aggregator / city guide pages
    r'^(chicago|austin|nyc|new\s+york|houston|miami|la|atlanta)\'?s\s+(gold\s+coast|top|best)',
    r'^streetwear\s+in\s+\w+\s*[|]\s*top',
    r'northwest\s+arkansas\s+shopping',
    r'baumans\s*[|]\s*little\s+rock',
    r'^southern\s+trend\s+clothing\b',
    r'^rkive\s*[|]',
    r'^reynolds\s+&\s+sons\b',
    # Travel guides / city guides / editorial pages
    r"insider'?s\s+guide",
    r"travel\s+guide\s+to",
    r"guide\s+to\s+shopping",
    r"guide\s+to\s+(the\s+)?best",
    r"best\s+stores\s*[&]?\s*boutiques",
    r"cool\s+guy'?s\s+guide",
    r"gamer'?s\s+travel\s+guide",
    r"sneakerhead'?s\s+guide",
    r"boutique\s+guide\s+(for|to)",
    r"unique\s+shopping\s+in",
    r"shopping\s+in\s+style",
    r"^shop\s+at\s+(soho|nyc|la|miami|chicago)",
    r"lower\s+east\s+side\s+\d{4}",
    # Non-apparel businesses slipping through
    r"\bburger\b",
    r"\bgrill\b.*\bcontact",
    r"\bcontact\s+us",
    r"\bhabit\s+burger",
    r"\bfood\s+co\.?\s+(opens|in)",
    r"\bbpm\s+supply",
    r"dj\s+(store|supply|shop)",
    r"online\s+store\s+for\s+dj",
    # News/magazine websites masquerading as stores
    r"\bcntraveler\.com",
    r"\bdmagazine\.com",
    r"\bthescoutguide",
    r"\bchicagofashionweek",
    r"\bexperiencegr\.com",
    r"\bbocamag\.com",
    r"\bblog\.bpm",
    r"\bthelocalartisan",
    r"\bnyctourism\.com",
    r"\bvisit\w+\.com",
    r"\btimeout\.com",
    r"\bjaguarsarasota\.com",
    # Appliance / non-apparel dealers
    r"\bla\s+cornue",
    r"authorized\s+showrooms?",
    r"\bappliance\s+(dealer|showroom|store)",
    r"find\s+a\s+\w+\s+dealer",
    # Men's clothing store (generic description, not a store name)
    r"^men'?s\s+clothing\s+store\s+in",
    # Products page (literally named 'Products')
    r'^products\s*$',
    # Introducing / opening announcement articles
    r'^introducing\s+\w+',
    r'opens?\s+in\s+\w+\s*$',
    r'opens?\s+new\s+\w+\s+location',
    r'opens?\s+new\s+store\s+in',
    r'^vale\s+opens\s+new',
    r'^supreme\s+open\s+a\s+new',
    r'^supreme\s+opens?\s+(first|new|a\s+new|its)',  # "Supreme opens first Chicago store"
    r'^supreme\s+detailing\b',          # Supreme Detailing = car detail shop
    r'^supreme\s+deals\s+inc\b',        # company profile aggregator
    r'company\s+profile\s*[|]',         # "X Company Profile | City"
    r'^joyrich\s*[|]',                   # Joyrich is a brand, not a boutique
    # Magazine / media article titles
    r'\bmagazine\b.*\b(february|january|march|april|may|june|july|august|september|october|november|december|\d{4})\b',
    r'\b\d+\s+best\s+(shops|stores|boutiques)\b',
    r'^photos?:\s+',
    r'^grinmore\s+brings\b',
    r'brings\s+streetwear\s+to\b',
    r'\bla\s+(gala|beyond)\b',
    r'to\s+le\s+gala',
    r'\bwainscot\s+media\b',
    r'\bissuu\.com\b',
    r'\b100\s+best\b',
    r"\w+'?s?\s+\d+\s+best",
    r'^shopping\s+\w+\s+style\b',
    r'\btourism\s+authority\b',
    r'\bstreetscout\.io\b',
    r'\bstreet\s+scout\b',
    r'\bsandiego\.org\b',
    # Cafe / coffee / food names that aren't streetwear
    r'\bcaffeine\s+supreme\b',
    r'\batrium\s+magazine\b',
    r'\bqsr\s*magazine\b',
    r'\b405\s*mag\b',
    r'\bluxiere\.co\b',
    r'\bhero[-\s]?magazine\b',
    r'\burb\s*magazine\b',
    r'\bsarasota\s+magazine\b',
    r'^where\s+to\s+shop\s+for\b',
    r'^the\s+best\s+shops?\s+in\b',
    r'to\s+visit\s+right\s+now\s*$',
    r'^supreme\.appliances\b',
    r'^where\s+to\s+shop\s+the\s+best\b',
    r'locals?:.*t-?shirts?',                    # "Fort Worth Locals: Fort Worth T-Shirts"
    r't-?shirts?\s*$',                           # anything ending in T-Shirts (t-shirt stores not boutiques)
    r'^john\s+l\.?\s+ashe\b',                  # specific outlet page
    r'[-\s]?men\'?s\s+clothing\s+store\s*$',  # "X - Men's Clothing Store" = mall locator
    r'^visit\s+\w+\s+in\b',           # "Visit pOpshelf in Fort Worth..."
    r'^\d+\s+sneaker\s+boutiques\b',   # "5 sneaker boutiques in Fort Worth"
    r'\bus\s+hub\s+for\s+homegrown\b', # "Union Station is ... hub for homegrown"
    r"is\s+[\w']+s\s+hub\s+for\b",   # "X is City's hub for..."
    r"hub\s+for\s+homegrown\b",
    r'^the\s+shops?\s+at\s+clearfork\b',
    r'^the\s+shops?\s+at\s+\w+\s*[|]',  # "The Shops at X | Men's..." = mall directory
    r',\s*tx\s+store\s*$',              # "Fort Worth, TX Store" = outlet locator
    r'\bstore\s+locator\b',
    r'^\w+,\s*[a-z]{2}\s+store\s*$',   # generic outlet page names
    r'\b6amcity\.com\b',
    r'\bdfwi\.org\b',
    r'\bpopshelf\.com\b',
    r'\bftwtoday\.\w+\.com\b',
    # IG handles masquerading as store names
    r'^@sarasotamagazine\b',
    r'^@timeoutnewyork\b',
    # Pure nonsense / placeholder
    r'^store\s+name\s*$',
    r'^city\s*$',
    r'^soho\s*$',
    r'^brooklyn\s*$',
    r'^new\s+york\s*$',
    r'^los\s+angeles\s*$',
    r'^miami\s*$',
    r'^chicago\s*$',
    r'^atlanta\s*$',
    r'^(find|locate)\s+a\s+\w+\s+(showroom|dealer|store\s+near)',
    r'high[-\s]?end\s+shopping\s+experience',
    r'\bshopping\s+experiences?\s+in\b',
    # Remaining hellstar junk not caught by other patterns
    r'^hellstar\s+studios?\s+the\b',
    r'^hellstar\s+clothing\s*[|]',
    r'^shop\s*[-]\s*hellstar',
    r'^shop\s+authentic\s+hellstar',
    r'^terms\s*[&]\s*conditions',
    r'^hell\s+star\s+(tee|hoodie|shirt|hat)',
    r'^storefront\s*[|]\s*hellstar',
    r'^hellstar\s+studios?\s+screaming',
    # Vale Forever product listings (not boutiques)
    r'^shop\s+vale\s+forever',
    r'^vale\s+forever\s+(nyc|restock|anthem|classic|premium|streetwear|big\s+tee|tracks)',
    # Article titles / city guides
    r'^the\s+best\s+shopping\s+in\b',
    r'^\w+\s+location\s*[|]\s*shop\b',
    r'^\w+\s+sneakers\s*[&]\s*clothing\s*[|]\s*shop\b',
    r'^\w+\s+location\s*[|]\s*\w+\s+nice\s+kicks',
    r'cheesy\s+breads',
    r'^order\s+supreme\b',
    r'^dillard',  # Dillard's = dept store chain
    r'\bmatcha\b.*\bcoffee\b',
    # Article / guide / list titles
    r'shopping\s+guide\b',
    r'stores?\s+that\s+will\s+elevate',
    r'^\d+\s+\w+\s+(clothing|sneaker|boutique)\s+stores?\s+that',
    r'new\s+york\s+city\s+shopping\s+guide',
    r'^supreme\s+stores?\s+in\b',
    # Job listings / career pages
    r'jobs?,\s+employment',
    r'\btechnician\s*[-]\s*\d{5,}',
    r'careers?\.cbre\.com',
    r'^careers?\s+',
    # Address as store name (starts with a number + street)
    r'^\d+\s+\w+\s+(blvd|ave|st|dr|rd|ln|way|pkwy|hwy)\b',
    # Homepage / section page titles with colon
    r':\s*welcome\s*$',
    r':\s*home\s*$',
    # Thrift / non-boutique resellers
    r'\bthrift\s+store\b',
    r'\bvalue\s+village\b',
    r'\bsecond\s+hand\b',
    r'\bpawn\s+and\s+jewelry\b',
    # Gym / athletic wear (not streetwear)
    r'\bgym\s+clothing\b',
    r'sportswear\s*[&]?\s*gym\b',
    r'^vale\s+collective\s*[|]\s*shopping\b',
    # Remaining hellstar product combos
    r'^hellstar\s+studios?\s+',      # hellstar studios [anything]
    r'^hellstar\s+\w+\s+\w+',        # hellstar [word] [word] = product
    # Rhude brand events / non-store entries
    r'^rhude\s+[-\u2014]\s+vip\b',
    r'^rhude\s+[[]',                  # RHUDE [hidden] etc.
    r'^rhude\s+[A-Z]{3,}\b',          # RHUDE HIDDEN, RHUDE SAMPLE etc.
    # Product restock captions
    r'^restock\s+\w+\s+vale\s+forever',
    r'^vale\s+forever\s+classic\s+rugby',
    r'^vale\s+forever\s+anthem',
    r'^vale\s+forever\s+nyc',
]

# Junk websites
JUNK_WEBSITE_DOMAINS = {
    'instagram.com', 'facebook.com', 'twitter.com', 'x.com', 'tiktok.com',
    'maps.apple.com', 'prnewswire.com', 'discoverlosangeles.com',
    'trippin.world', 'nordstrom.com', 'therealreal.com',
    'hellstar.com', 'hellstar.us', 'store-hellstar.com',
    'hel-star.com', 'hellstarofficialstudio.com', 'officialhellstar.com',
    'rh-ude.com', 'rhude.com', 'shopenauer.com', 'simon.com',
    'maps.google.com', 'google.com', 'grailed.com', 'stockx.com',
    'goat.com', 'offerup.com', 'craigslist.org', 'poshmark.com',
    'depop.com', 'ebay.com', 'amazon.com', 'walmart.com',
    'youtube.com', 'reddit.com', 'hypebeast.com', 'sneakernews.com',
    # Editorial / travel / news sites that slip through as 'stores'
    'cntraveler.com', 'dmagazine.com', 'timeout.com', 'nyctourism.com',
    'thescoutguide.com', 'chicagofashionweek.com', 'experiencegr.com',
    'bocamag.com', 'blog.bpmmusic.io', 'thelocalartisanguide.com',
    'visitwesthollywood.com', 'jaguarsarasota.com', 'lacornueusa.com',
    'onemanhattansquare.com', 'habitburger.com', 'bonobos.com',
    'trailappliances.com',
    # More editorial/news sites
    'atriummag.org', 'sarasotamagazine.com', 'urbmagazine.substack.com',
    'sandiego.org', 'hero-magazine.com', 'supreme-appliances.com',
    '405magazine.com', 'qsrmagazine.com', 'issuu.com', 'luxiere.co',
    'sandiego.gov', 'visithouston.com', 'visitmiamibeach.com',
    'choosechicago.com', 'discoveratlanta.com', 'discoverlosangeles.com',
    'nycgo.com', 'lonelyplanet.com', 'tripadvisor.com', 'yelp.com',
    'foursquare.com',
}

FAKE_EMAILS_RE  = re.compile(r'\.(png|jpg|jpeg|gif|webp|svg|ico|pdf|php|js|css)$', re.I)
FAKE_PHONES_SET = {'0000000000', '9999999999', '1234567890', '0987654321'}
FAKE_EMAIL_SET  = {'xxx@xxx.xxx', 'user@domain.com', 'name@email.com', 'example@example.com', 'test@test.com', 'info@test.com'}
JUNK_IG_SET     = {
    '@rsrc.php', '@context', '@4GfJ', '@media', '@unknown',
    '@hellstar', '@HELLSTAR', '@rhude', '@rhude_official', '@RHUDE',
    '@supreme.appliances', '@shopify', '@shopify_stores',
    '@sarasotamagazine', '@timeoutnewyork', '@downtownfortworth',
}
EMOJI_RE = re.compile(
    u'[\U0001F300-\U0001F5FF'
    u'\U0001F600-\U0001F64F'
    u'\U0001F680-\U0001F6FF'
    u'\U0001F700-\U0001F77F'
    u'\U0001F780-\U0001F7FF'
    u'\U0001F800-\U0001F8FF'
    u'\U0001F900-\U0001F9FF'
    u'\U0001FA00-\U0001FA6F'
    u'\U0001FA70-\U0001FAFF'
    u'\U00002702-\U000027B0'
    u'\U000024C2-\U0001F251'
    u'\u2757\u2755\u203c\u2049'
    u']+'
)

# Brand prefix stripping (scraper prepended brand name to actual store name)
BRAND_PREFIX_RE = re.compile(
    r'^(?:hellstar\s+studios?\s*[-\u2013]\s*'
    r'|hellstar\s*[-\u2013]\s*'
    r'|rhude\s+archives?(?:\s*[-\u2013]\s*page\s*\d+\s+of\s+\d+)?\s*[-\u2013]\s*'
    r'|rhude\s*[-\u2013]\s*'
    r'|vale\s+forever\s*[-\u2013]\s*'
    r'|supreme\s*[-\u2013]\s*)',
    re.I
)

# Confirmed Godspeed stockists (remove from leads)
GODSPEED_STOCKISTS = {
    'hyp miami', 'backdoor miami', 'backdoor mia', 'duval kickz',
    'hellstar - backdoor miami', 'rhude - hyp miami', 'hellstar - hyp miami',
}

# ----------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------

def normalize_state(raw):
    s = raw.strip()
    if len(s) == 2:
        return s.upper()
    mapped = STATE_NAME_TO_ABBR.get(s.lower())
    if mapped:
        return mapped
    return s.upper()[:2] if len(s) >= 2 else ''


def get_territory(state, country):
    c = country.strip().upper()
    usa_variants = {'USA','US','UNITED STATES','U.S.A.','U.S.','AMERICA',''}
    if c not in usa_variants:
        return 'International'
    return TERRITORY_MAP.get(state.upper(), 'Unknown-US')


def get_domain(url):
    if not url:
        return ''
    return re.sub(r'^https?://', '', url).split('/')[0].lower().lstrip('www.')


def clean_phone(p):
    p = p.strip()
    if not p or p in FAKE_PHONES_SET:
        return ''
    digits = re.sub(r'\D', '', p)
    # More than 11 digits = not a phone
    if len(digits) > 11:
        return ''
    # Less than 7 digits = incomplete
    if len(digits) < 7:
        return ''
    # Unformatted 10-digit number = likely Instagram ID, not a phone
    if len(digits) == 10 and not re.search(r'[()\-\s+.]', p):
        return ''
    return p


def clean_email(e):
    e = e.strip()
    if not e or '@' not in e:
        return ''
    if e.lower() in FAKE_EMAIL_SET:
        return ''
    if FAKE_EMAILS_RE.search(e):
        return ''
    # Placeholder patterns
    if re.search(r'^(xxx|user|name|test|example)@', e, re.I):
        return ''
    if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
        return e.lower()
    return ''


def clean_instagram(ig):
    ig = ig.strip()
    if not ig or ig in JUNK_IG_SET:
        return ''
    if FAKE_EMAILS_RE.search(ig.lower()):
        return ''
    if ig.startswith('@') and len(ig) < 3:
        return ''
    # Strip trailing dots/underscores sometimes left by scraper
    ig = ig.rstrip('.')
    return ig


def clean_website(w):
    w = w.strip()
    if not w:
        return ''
    if FAKE_EMAILS_RE.search(w):
        return ''
    domain = get_domain(w)
    if not domain:
        return ''
    # Reject junk domains
    for junk in JUNK_WEBSITE_DOMAINS:
        if domain == junk or domain.endswith('.' + junk):
            return ''
    # Reject domains that are clearly editorial/tourism/media (not retail)
    NON_RETAIL_DOMAIN_KW = [
        'magazine', 'mag.com', 'mag.org', 'tourism', 'visitor', 'discover',
        'substack.com', 'tripadvisor', 'foursquare', 'yelp.com', 'lonelyplanet',
        'nycgo.com', 'choosechicago', 'visithouston', 'visitmiamibeach',
        'discoveratlanta', 'sandiego.gov', 'sandiego.org', '.gov/tourism',
        'appliances.com', 'supreme-appliances.com', 'littlerocksoiree.com',
    'popshelf.com', 'dfwi.org', 'mizzenandmain.com', 'overland.com',
    '6amcity.com',
    ]
    for kw in NON_RETAIL_DOMAIN_KW:
        if kw in domain:
            return ''
    # Return just the base domain as the canonical website
    return 'https://' + domain


def is_junk_name(name):
    n = name.strip()
    nl = n.lower()
    if not n:
        return True
    # Over 85 chars = page title
    if len(n) > 85:
        return True
    # HTML entities
    if '&amp;' in nl or '&#' in nl:
        return True
    # Multiple pipes = page title
    if n.count('|') >= 2:
        return True
    # Starts with URL
    if nl.startswith('http'):
        return True
    # Truncated title marker
    if '...' in n:
        return True
    # " - Instagram" suffix
    if nl.endswith('- instagram') or nl.endswith('-instagram'):
        return True
    # Emojis in name = almost always an IG post caption
    if EMOJI_RE.search(n):
        return True
    # Name is only the brand itself (no store context)
    if re.match(r'^(hellstar|rhude|vale\s+forever|supreme)\s*$', nl):
        return True
    # Name is only a city/state name (no actual store name — outlet locator result)
    BARE_CITY_NAMES = {
        'fort worth', 'houston', 'dallas', 'austin', 'san antonio', 'el paso',
        'new york', 'brooklyn', 'queens', 'bronx', 'manhattan', 'soho',
        'chicago', 'los angeles', 'miami', 'atlanta', 'seattle', 'denver',
        'portland', 'phoenix', 'las vegas', 'orlando', 'tampa', 'nashville',
        'detroit', 'philadelphia', 'boston', 'charlotte', 'raleigh',
        'minneapolis', 'st. louis', 'kansas city', 'new orleans',
    }
    if nl.strip() in BARE_CITY_NAMES:
        return True
    # "Hellstar [product]" - any single brand + product word = product listing
    if re.match(r'^hellstar\s+\w+$', nl) and len(nl.split()) <= 3:
        return True
    # Pattern matching
    for pat in JUNK_NAME_PATTERNS:
        if re.search(pat, nl, re.I | re.UNICODE):
            return True
    return False


def is_chain(name):
    nl = name.lower()
    for pat in CHAIN_PATTERNS:
        if re.search(pat, nl, re.I):
            return True
    return False


def is_car_or_non_apparel(name, notes=''):
    combined = (name + ' ' + notes).lower()
    for pat in CAR_PATTERNS:
        if re.search(pat, combined, re.I):
            return True
    for pat in NON_APPAREL_BUSINESS_PATTERNS:
        if re.search(pat, combined, re.I):
            return True
    return False


def carries_godspeed(name, notes, gs_field):
    nl = name.strip().lower()
    nf = notes.strip().lower()
    gf = gs_field.strip().lower()

    if nl in GODSPEED_STOCKISTS:
        return True
    if gf == 'yes':
        return True
    if 'godspeed' in nl:
        return True
    # Notes explicitly confirming Godspeed
    if 'godspeed' in nf and any(w in nf for w in ['carries','confirmed','stockist','carrying']):
        return True
    return False


def is_warm_lead(name, notes, website):
    """
    Warm lead = store that carries Rhude or Vale Forever (not the brand itself).
    """
    nl = name.lower()
    nt = notes.lower()
    wd = get_domain(website)

    # Exclude Rhude/Vale Forever brand websites
    if wd in ('rh-ude.com', 'rhude.com', 'valeforever.com'):
        return False
    # Exclude if name IS the brand
    if re.match(r'^r\s*h\s*u\s*d\s*e\s*$', nl.strip()):
        return False

    # Name pattern: "Rhude Archives - [Store]" or "[Store] - Rhude Collection"
    if re.search(r'rhude\s+(archives?|collection|tees?|shirts?)\s*[-\u2013]', nl):
        return True
    if re.search(r'[-\u2013]\s*(rhude|vale\s+forever)\s+(archives?|collection)', nl):
        return True
    # Notes say they carry these brands
    if re.search(r'\brhude\b', nt):
        return True
    if re.search(r'\bvale\s+forever\b', nt):
        return True
    # Name has "Buttafly" type patterns with Rhude collection ref
    if re.search(r'rhude\s+collection\s*[-\u2013]', nl):
        return True

    return False


# ----------------------------------------------------------------
# ROW PARSER
# ----------------------------------------------------------------

def parse_row(row):
    def g(i):
        return row[i].strip() if i < len(row) else ''

    name     = g(0)
    city     = g(1)
    raw_st   = g(2)
    col3     = g(3)

    # Detect schema
    if col3.lower() in KNOWN_COUNTRIES or col3.upper() == col3 and re.match(r'^[A-Z\s]+$', col3) and len(col3) > 2:
        # SCRAPER FORMAT: col3 = country
        country  = col3
        website  = g(4)
        instagram= g(5)
        email    = g(6)
        phone    = g(7)
        gs_field = g(10)
        notes    = g(14)
    elif col3.startswith('@'):
        # MANUAL FORMAT: col3 = instagram
        country  = 'USA'
        instagram= col3
        website  = g(4)
        phone    = g(5)
        email    = g(6)
        gs_field = g(9)
        notes    = g(11) if len(row) > 11 else ''
    else:
        # OTHER FORMAT: col3 empty or unknown
        country  = 'USA'
        instagram= ''
        website  = g(4)
        phone    = g(5)
        email    = g(6)
        gs_field = ''
        notes    = g(11) if len(row) > 11 else ''

    return {
        'name':     name,
        'city':     city,
        'raw_st':   raw_st,
        'country':  country,
        'website':  website,
        'instagram':instagram,
        'email':    email,
        'phone':    phone,
        'gs_field': gs_field,
        'notes':    notes,
    }


# ----------------------------------------------------------------
# MAIN CLEANING LOOP
# ----------------------------------------------------------------

removal_reasons = defaultdict(list)
kept      = []
seen_keys = {}  # name_key or domain_key -> index in kept

with open(INPUT_CSV, encoding='utf-8') as f:
    all_rows = list(csv.reader(f))

total_raw = len(all_rows) - 1
data_rows = all_rows[1:]

for row in data_rows:
    if len(row) < 3:
        removal_reasons['unparseable'].append('')
        continue

    p = parse_row(row)
    name = p['name']

    # 1. Junk name filter
    if is_junk_name(name):
        removal_reasons['junk_scraper_artifact'].append(name)
        continue

    # 2. Must have name
    if not name.strip():
        removal_reasons['empty_name'].append(name)
        continue

    # 2b. Strip brand prefixes and scraper appended noise from name
    name_stripped = BRAND_PREFIX_RE.sub('', name).strip()
    if name_stripped:
        name = name_stripped
    # Strip "(@handle)" appended by scraper: "Store Name (@handle)" -> "Store Name"
    name = re.sub(r'\s*\(@[^)]+\)\s*', '', name).strip()
    # Strip " - City, ST" or " - Los Angeles" type geographic suffixes
    name = re.sub(r'\s*[-\u2013]\s*(los angeles|new york|miami|chicago|houston|atlanta|seattle|dallas|austin|san francisco|las vegas|boston|denver|portland|orlando|nashville|detroit|philadelphia)\s*$', '', name, flags=re.I).strip()
    # Strip trailing " - Los Angeles, CA" with state abbr
    name = re.sub(r'\s*[-\u2013]\s*[A-Za-z\s]+,\s*[A-Z]{2}\s*$', '', name).strip()

    # 3. Chains
    if is_chain(name):
        removal_reasons['chain_store'].append(name)
        continue

    # 4. Cars / non-apparel
    if is_car_or_non_apparel(name, p['notes']):
        removal_reasons['car_or_non_apparel'].append(name)
        continue

    # 5. Godspeed stockists
    if carries_godspeed(name, p['notes'], p['gs_field']):
        removal_reasons['already_godspeed_stockist'].append(name)
        continue

    # --- Normalize fields ---
    state     = normalize_state(p['raw_st'])
    territory = get_territory(state, p['country'])
    country_n = 'USA' if p['country'].upper() in {'USA','US','UNITED STATES','U.S.A.','U.S.',''} else p['country']

    instagram = clean_instagram(p['instagram'])
    email     = clean_email(p['email'])
    phone     = clean_phone(p['phone'])
    website   = clean_website(p['website'])

    # 6. Must have at least one contact / presence signal
    if not any([instagram, email, phone, website]):
        removal_reasons['no_contact_info'].append(name)
        continue

    warm = 'Yes' if is_warm_lead(name, p['notes'], website) else 'No'

    record = {
        'Store Name': name,
        'City':       p['city'],
        'State':      state,
        'Country':    country_n,
        'Territory':  territory,
        'Instagram':  instagram,
        'Email':      email,
        'Phone':      phone,
        'Website':    website,
        'Warm_Lead':  warm,
    }

    # --- Deduplication (by name OR domain) ---
    name_key   = name.lower().strip()
    domain_key = website.replace('https://', '').rstrip('/') if website else None

    def score(r):
        return sum(1 for v in r.values() if v and v not in ('No', 'Unknown-US'))

    dup_found = False

    if domain_key and domain_key in seen_keys:
        idx = seen_keys[domain_key]
        if score(record) > score(kept[idx]):
            kept[idx] = record
        dup_found = True
    elif name_key in seen_keys:
        idx = seen_keys[name_key]
        if score(record) > score(kept[idx]):
            kept[idx] = record
        dup_found = True

    if not dup_found:
        idx = len(kept)
        seen_keys[name_key] = idx
        if domain_key:
            seen_keys[domain_key] = idx
        kept.append(record)


# ----------------------------------------------------------------
# WRITE CSV
# ----------------------------------------------------------------

os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
FIELDS = ['Store Name','City','State','Country','Territory','Instagram','Email','Phone','Website','Warm_Lead']

with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(kept)

print(f"Wrote {len(kept)} clean leads to {OUTPUT_CSV}")

# ----------------------------------------------------------------
# STATS
# ----------------------------------------------------------------

territory_counts = defaultdict(int)
warm_leads = []
for r in kept:
    territory_counts[r['Territory']] += 1
    if r['Warm_Lead'] == 'Yes':
        warm_leads.append(r)

total_removed = total_raw - len(kept)

removal_order = [
    ('junk_scraper_artifact',       'Junk scraper artifacts (web titles, IG post captions, brand pages)'),
    ('chain_store',                  'Chain / big-box stores'),
    ('already_godspeed_stockist',    'Already confirmed Godspeed stockists (removed from leads)'),
    ('car_or_non_apparel',           'Car dealerships / non-apparel businesses'),
    ('no_contact_info',              'No usable contact info (no IG, email, phone, or website)'),
    ('empty_name',                   'Empty store name'),
    ('unparseable',                  'Unparseable / malformed rows'),
]

# ----------------------------------------------------------------
# WRITE REPORT
# ----------------------------------------------------------------

with open(REPORT_MD, 'w', encoding='utf-8') as f:
    f.write("# Wilmar Barrios -- Godspeed Master Database Clean Report\n\n")
    f.write("**Date:** 2026-04-21  |  **Agent:** Wilmar Barrios (Data Collection)\n\n---\n\n")

    f.write("## Summary\n\n")
    f.write("| Metric | Count |\n|--------|-------|\n")
    f.write(f"| Raw rows (MASTER DATABASE) | {total_raw:,} |\n")
    f.write(f"| Clean leads (master_clean.csv) | {len(kept):,} |\n")
    f.write(f"| Total removed | {total_removed:,} |\n")
    f.write(f"| Warm leads (Rhude / Vale Forever carriers) | {len(warm_leads)} |\n\n")

    f.write("---\n\n## Removal Breakdown\n\n")
    f.write("| Reason | Count |\n|--------|-------|\n")
    for key, label in removal_order:
        count = len(removal_reasons.get(key, []))
        if count:
            f.write(f"| {label} | {count:,} |\n")

    chains = removal_reasons.get('chain_store', [])
    if chains:
        unique_chains = sorted(set(chains))
        f.write(f"\n**Chain stores removed ({len(unique_chains)} unique names, {len(chains)} total rows):**\n")
        for nm in unique_chains[:40]:
            f.write(f"- {nm}\n")
        if len(unique_chains) > 40:
            f.write(f"- *(+ {len(unique_chains)-40} more)*\n")

    gs_removed = removal_reasons.get('already_godspeed_stockist', [])
    if gs_removed:
        f.write(f"\n**Confirmed Godspeed stockists removed from leads:**\n")
        for nm in sorted(set(gs_removed)):
            f.write(f"- {nm}\n")

    f.write("\n---\n\n## Territory Breakdown\n\n")
    f.write("| Territory | Stores |\n|-----------|--------|\n")
    for terr in ['Southeast','Northeast','Midwest','Southwest','West','Mid-Atlantic','International','Unknown-US']:
        cnt = territory_counts.get(terr, 0)
        if cnt:
            f.write(f"| {terr} | {cnt:,} |\n")

    f.write("\n---\n\n## Warm Leads (Rhude / Vale Forever Carriers)\n\n")
    f.write(f"*{len(warm_leads)} stores identified as Warm_Lead=Yes -- they already buy at Godspeed's price point.*\n\n")
    if warm_leads:
        f.write("| Store Name | City | State | Territory | Instagram | Website |\n")
        f.write("|------------|------|-------|-----------|-----------|----------|\n")
        for r in warm_leads:
            f.write(f"| {r['Store Name']} | {r['City']} | {r['State']} | {r['Territory']} | {r['Instagram']} | {r['Website']} |\n")

    f.write("\n---\n\n## Data Quality Notes\n\n")
    notes_list = [
        "**Dual schema:** ~3,318 rows in scraper format (Country in col 3), ~454 in manual format (Instagram in col 3), ~36 in a third variant. Format auto-detected per row.",
        "**Scraper contamination:** Large portion of raw rows were web page titles, SEO results, or brand pages (e.g. Hellstar's own website appearing as a 'store'). Filtered via 50+ name patterns.",
        "**Instagram post captions:** Many rows had IG post captions as the store name (e.g. 'Rhude Tees In Stock!! -Size S-XL Available in-store & ...'). Filtered by emoji detection, truncation markers, and caption phrase patterns.",
        "**Phone contamination:** Many 'phone' values were Instagram follower/ID numbers (unformatted 10-digit strings like 1036701292). Filtered: unformatted 10-digit values rejected as IG IDs.",
        "**Email contamination:** Some 'email' fields contained image filenames (TOKEN_flagship.png etc.). Filtered via file extension detection.",
        "**Brand prefix stripping:** Scraper prepended brand name to store entries (e.g. 'Hellstar Studios - Token Miami' -> 'Token Miami', 'Rhude Archives - Coppra Miami' -> 'Coppra Miami').",
        "**Website normalization:** Product/collection paths stripped; only base domain stored as canonical website.",
        "**Deduplication:** Same store appearing under different scraper row titles merged by website domain. Best version (most fields populated) wins.",
        "**HYP Miami:** Confirmed Godspeed stockist per user instruction -- removed from leads.",
        "**Duval Kickz (Jacksonville FL):** Notes confirm 'CONFIRMED carries Godspeed + Hellstar' -- removed from leads.",
        "**Backdoor Miami:** Scraped data shows Carries Godspeed=YES -- removed from leads.",
        "**International territory:** Stores outside USA (France, Japan, UK, Australia, etc.) assigned Territory=International. All countries detected from scraper data.",
    ]
    for note in notes_list:
        f.write(f"- {note}\n")

    f.write("\n---\n\n*Report generated by Wilmar Barrios -- El Barrio Data Collection*\n")

print(f"Wrote report to {REPORT_MD}")
print(f"\nStats:")
print(f"  Raw: {total_raw}  |  Clean: {len(kept)}  |  Removed: {total_removed}  |  Warm: {len(warm_leads)}")
print(f"\n  Territory:")
for terr in ['Southeast','Northeast','Midwest','Southwest','West','Mid-Atlantic','International','Unknown-US']:
    cnt = territory_counts.get(terr, 0)
    if cnt:
        print(f"    {terr}: {cnt}")
print(f"\n  Removal:")
for key, label in removal_order:
    count = len(removal_reasons.get(key, []))
    if count:
        print(f"    {label}: {count}")
