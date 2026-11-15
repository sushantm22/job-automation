import json
from pathlib import Path

# Curated list of verified tech companies across Greenhouse, Lever, and Ashby
# Covering top US/Global tech, AI startups, YC companies, and Indian tech companies.

greenhouse_companies = [
    # Top Tech, Cloud & Infrastructure
    "stripe", "databricks", "airbnb", "coinbase", "postman", "gitlab", "cloudflare", "elastic",
    "twilio", "mongodb", "rubrik", "razorpay", "hashicorp", "doordash", "instacart", "reddit",
    "robinhood", "canva", "notion", "slack", "miro", "datadog", "okta", "splunk", "crowdstrike",
    "paloaltonetworks", "box", "asana", "monday", "brex", "plaid", "chime", "gusto",
    "rippling", "scaleai", "anthropic", "huggingface", "vercel", "supabase", "neon", "pinecone",
    "langchain", "weaviate", "cohere", "perplexity", "mistral", "glean", "thoughtspot", "harness",
    "pagerduty", "fastly", "confluent", "segment", "zapier", "airtable", "webflow", "auth0",
    "samsara", "snowflake", "benchling", "checkr", "carta", "carta-careers", "branch", "amplitude",
    "cockroachlabs", "temporal", "starburst", "astronomer", "dbtlabs", "hex", "motherduck", "modal",
    "replicate", "runwayml", "midjourney", "adept", "inflection", "coreweave", "togetherai", "anyscale",
    "datarobot", "dataiku", "h2oai", "snorkel", "fivetran", "census", "hightouch", "rudderstack",
    "cube", "clickhouse", "scylladb", "couchbase", "yugabyte", "aerospike", "neo4j", "timescale",
    
    # Security, Networking, DevOps
    "wiz", "snyk", "lacework", "orca-security", "cyera", "armis", "axonius", "abnormal-security",
    "island", "claroty", "cato-networks", "tailscale", "teleport", "twingate", "chainguard",
    "aqua-security", "sysdig", "tigera", "datadome", "castle", "authress", "stytch", "clerk",
    "kinde", "workos", "fusionauth", "permitio", "cerbos", "styra", "spacelift", "env0",
    "scalr", "pulumi", "gruntwork", "circleci", "buildkite", "semaphore", "codefresh", "harness-inc",
    "octopus-deploy", "artifactory", "sonarsource", "launchdarkly", "split", "flagsmith", "growthbook",
    "honeycomb", "lightstep", "chronosphere", "coralogix", "logz", "sumologic", "betterstack",
    "signoz", "uptrace", "incident", "firehydrant", "rootly", "blameless", "transcend", "privado",
    
    # Fintech, Payments & Banking
    "adyen", "checkout", "revolut", "monzo", "n26", "starling", "nubank", "klarna", "affirm",
    "afterpay", "sezzle", "zip", "marqeta", "lithic", "galileo", "synapse", "unit", "treasury-prime",
    "column", "mercury", "relay", "novo", "brex-careers", "ramp-financial", "airbase", "teampay",
    "divvy", "bill", "tipalti", "melio", "routable", "modern-treasury", "increase", "lead-bank",
    "cross-river", "drivewealth", "alpaca", "interactive-brokers", "etoro", "public", "webull",
    "kraken", "gemini", "bitgo", "fireblocks", "anchorage", "paxos", "circle-internet", "chainalysis",
    "elliptic", "trm-labs", "certik", "consensys", "alchemy", "quicknode", "infura", "moralis",
    "dydx", "uniswap", "opensea", "magic-eden", "rarible", "ledger", "trezor", "phantom",
    
    # SaaS, Collaboration & Productivity
    "loom", "figma-careers", "coda", "pitch", "linear-app", "raycast", "craft", "superhuman",
    "spark-mail", "front", "missive", "intercom", "drift", "gorgias", "kustomer", "freshworks",
    "zendesk", "helpscout", "crisp", "livechat", "dialpad", "aircall", "openphone", "talkdesk",
    "five9", "ringcentral", "zoominfo", "apollo-io", "cognism", "lusha", "clearbit", "leadfeeder",
    "hubspot", "pipedrive", "copper", "close", "attio", "folk", "clay", "outreach", "salesloft",
    "gong", "chorus", "clari", "people-ai", "avoma", "fireflies", "otter-ai", "tldv",
    "grain", "fathom", "fellow", "hypercontext", "lattice", "culture-amp", "15five", "leapsome",
    "bonusly", "fond", "kudos", "recognize", "workvivo", "lumapps", "simpplr", "guru",
    
    # Indian & APAC Tech Leaders
    "clevertap", "hasura", "yellowai", "moengage", "leadsquared", "chargebee", "kissflow",
    "darwinbox", "hackerrank", "browserstack", "inmobi", "glance", "sharechat", "dailyhunt",
    "urban-company", "lenskart", "meesho", "spinny", "cars24", "acko", "digit-insurance",
    "navi-technologies", "jupiter", "fi-money", "kreditbee", "moneyview", "slice", "uni-cards",
    "onecard", "bharatpe", "mobikwik", "freecharge", "billdesk", "payu-india", "cashfree",
    "setu", "decentro", "finbox", "perfios", "karza", "signzy", "hyperverge", "idfy",
    "verloop", "gnani-ai", "reverie", "coRover", "haptik", "senseforth", "active-ai", "avaamo",
    "entrib", "flutura", "infinite-analytics", "mad-street-den", "quidich", "skylark-drones",
    
    # E-Commerce, Logistics & Marketplaces
    "instacart-careers", "shipt", "gopuff", "getir", "gorillas", "flinki", "deliveroo", "just-eat",
    "delivery-hero", "foodpanda", "wolt", "swiggy-careers", "zomato-careers", "dunzo", "zepto-careers",
    "blinkit", "bigbasket", "grofers", "faire", "tundra", "abound", "orderchamp", "creoate",
    "ankorstore", "pehub", "convoy", "flexport", "freightos", "project44", "fourkites", "shippo",
    "shipbob", "shipmonk", "deliverr", "veeqo", "linnworks", "skubana", "channelengine", "feedonomics",
    
    # HealthTech, BioTech & EdTech
    "oscar", "clover-health", "cityblock", "oak-street", "one-medical", "forward", "ro", "hims",
    "thirty-madison", "curology", "nurx", "pillpack", "capsule", "alto-pharmacy", "truepill", "komodo-health",
    "tempus", "flatiron", "owkin", "insitro", "recursion", "relentless", "coursera", "udemy",
    "edx", "skillshare", "masterclass", "duolingo", "babbel", "busuu", "quizlet", "kahoot",
    "brainly", "photomath", "chegg", "course-hero", "outlier", "scale-ai-education", "upgrad", "eruditus",
    
    # Gaming, Media & Entertainment
    "epicgames", "riotgames", "roblox", "unity3d", "niantic", "scopely", "zynga", "playtika",
    "moon-active", "supercell", "king", "voodoo", "applovin", "ironsource", "mintegral", "chartboost",
    "spotify-careers", "soundcloud", "deezer", "pandora", "tidal", "audiomack", "tunein", "iheartmedia",
    "roku-careers", "tubi", "pluto-tv", "fubo-tv", "sling-tv", "vimeo", "dailymotion", "twitch",
    "discord-careers", "kick", "streamlabs", "streamelements", "obs-studio", "medal-tv", "overwolf",
    
    # YC & High-Growth Startups (Greenhouse)
    "resend", "cal-com", "dub", "trigger-dev", "posthog", "highlight-io", "inngest", "papertrail",
    "axiom", "better-uptime", "checkly", "cronitor", "healthchecks", "deadmanssnitch", "statuspage",
    "statuspal", "statuspal-io", "incident-io", "alertmanager", "grafana-labs", "prometheus-group",
    "chronicle", "crowdstrike-inc", "mandiant", "sentinelone", "deepwatch", "expel", "arctic-wolf",
    "reliaquest", "red-canary", "huntress", "blackpoint", "blumira", "perch", "stellar-cyber",
    "securiti", "bigid", "one-trust", "trustarc", "collibra", "alation", "atlan-data", "datafold",
    "montecarlodata", "bigeye", "acceldata", "anomalo", "kaskada", "feast", "tecton", "hopsworks",
    "featureform", "qwak", "bento-ml", "seldon", "kserve", "triton-inference", "vllm", "ollama",
    "open-webui", "langfuse", "arize", "whylabs", "truera", "fiddler", "arthur-ai", "robust-intelligence",
    "calypsoai", "lakera", "promptfoo", "deepchecks", "giskard", "evidently", "nanny-ml", "cleanlab",
    
    # Enterprise Cloud & Systems
    "nutanix-careers", "purestorage", "netapp", "arista", "f5", "a10-networks", "extreme-networks",
    "juniper", "ciena", "infinera", "commvault", "veeam", "veritas", "rubrik-inc", "cohesity",
    "druva", "actifio", "zerto", "datastax", "couchbase-inc", "mariadb", "percona", "pingcap",
    "singlestore", "voltdb", "gridgain", "hazelcast", "redis-labs", "memurai", "dragonflydb", "keydb",
    
    # Additional High Growth & Global Tech
    "stripe-inc", "databricks-inc", "coinbase-inc", "roblox-corp", "pinterest", "snapchat", "snap-inc",
    "lyft-careers", "yelp", "groupon", "tripadvisor", "expedia-group", "booking-holdings", "kayak",
    "trivago", "opendoor", "zillow", "redfin", "compass-inc", "clutter", "samsara-inc", "fleetmatics",
    "geotab", "keep-truckin", "motive", "verkada", "rhombus", "coram-ai", "smart-witness", "netradyne",
    "loconav", "fleetx", "intugine", "far-eye", "locus", "elogii", "routific", "optimoroute",
    "onfleet", "bringg", "delivery-solutions", "parcellab", "narvar", "metapack", "shippypro",
    "sendcloud", "shipstation", "shippingeasy", "easyship", "shippo-inc", "postage-rates", "stamps-com",
    "pitney-bowes", "quadient", "neopost", "blue-yonder", "manhattan-associates", "kinaxis", "o9-solutions"
]

lever_companies = [
    # Prominent Tech on Lever
    "plivo", "atlan", "netflix-careers", "palantir-careers", "shopify-careers", "eventbrite",
    "atlassian-careers", "lyft", "uber-freight", "clearbanc", "bench", "freshbooks", "wave-accounting",
    "kount", "signifyd", "riskified", "forter", "sift", "feedzai", "socure", "jumio", "onfido",
    "veriff", "persona-identities", "trulioo", "idnow", "passbase", "berbix", "inverid", "fourthline",
    "automattic", "wordpress", "ghost", "strapi", "sanity", "contentful", "prismic", "storyblok",
    "directus", "payload-cms", "keystonejs", "buttercms", "cosmicjs", "agility-cms", "dotcms", "magnolia",
    "bloomreach", "coremedia", "sitecore", "optimizely", "abtasty", "vwo", "kameleoon", "dynamic-yield",
    
    # Data, AI & Infrastructure on Lever
    "dbt", "prefect", "dagster", "astronomer-io", "cube-dev", "metabase", "lightdash", "evidence-dev",
    "rill-data", "preset", "superset", "redash", "grafana", "clickhouse-inc", "questdb", "victoriametrics",
    "timescaledb", "influxdata", "cratedb", "warp10", "tdengine", "iotdb", "kairosdb", "opentsdb",
    "rilldata", "deepnote", "hex-tech", "count-co", "decisive-data", "mode-analytics", "chartio",
    "looker-careers", "periscope-data", "sisense", "thoughtspot-inc", "gooddata", "domo", "qlik",
    
    # European & Global Startups on Lever
    "personio", "pleo", "spendesk", "payfit", "alan", "qonto", "swan", "mollie", "bunq", "n26-careers",
    "traderepublic", "scalable-capital", "etoro-careers", "bitpanda", "freetrade", "bux", "plum",
    "chip", "moneybox", "curve", "tide", "annalise-ai", "safetyculture", "culture-amp-careers",
    "airwallex", "zip-co", "afterpay-touch", "tyro", "judopay", "checkout-com", "truelayer", "yapily",
    "tink", "plaid-eu", "nordigen", "bud", "finleap", "solarisbank", "railsr", "modulr", "form3",
    
    # Indian & Asian Startups on Lever
    "clevertap-inc", "invideo", "animaker", "renderforest", "biteable", "vyond", "powtoon", "lumen5",
    "pictory", "steve-ai", "synthesia", "d-id", "heygen", "elai-io", "colossyan", "rephrase-ai",
    "murf-ai", "lovo-ai", "speechify", "eleven-labs-lever", "wellsaid-labs", "resemble-ai", "play-ht",
    "coqui-ai", "deepgram", "assemblyai", "rev-ai", "speechmatics", "symbl-ai", "vapi-ai", "bland-ai",
    
    # DevTools & Open Source on Lever
    "sourcegraph", "gitpod", "coder", "codespaces", "replit-careers", "glitch", "codeanywhere",
    "stackblitz", "codesandbox", "scrimba", "boot-dev", "exercism", "codewars", "leetcode-careers",
    "hackerrank-inc", "coderbyte", "testgorilla", "codility", "qualified", "codesignal", "filtered",
    "interviewing-io", "pramp", "tryexponent", "interviewcake", "techinterviewpro", "algomonster",
    "neetcode", "designgurus", "bytebytego", "educative", "zerotomastery", "frontendmasters",
    "egghead-io", "scrimba-inc", "pluralsight", "datacamp", "dataquest", "superdatascience",
    "maven-learning", "reforge", "section4", "alison", "futurelearn", "open-classrooms", "edureka",
    "simplilearn", "great-learning", "scaler-academy", "interviewbit", "newton-school", "masai-school"
]

ashby_companies = [
    # Top AI & Modern Tech on Ashby
    "sentry", "ramp", "replit", "figma", "openai", "cursor", "anysphere", "tldraw", "excalidraw",
    "linear", "supermaven", "augmentcode", "poolside", "magic-dev", "cognition", "devin",
    "factory-ai", "sweep-dev", "grit-io", "codium-ai", "qodo", "tabnine", "continue-dev", "aider",
    "cline", "roo-cline", "windsurf", "codeium", "sourcegraph-cody", "amazon-q", "github-copilot-team",
    "cohere-ai", "ai21-labs", "writer", "jasper", "copy-ai", "anyword", "rytr", "writesonic",
    "hypotenuse-ai", "frase-io", "surfer-seo", "scalenut", "marketmuse", "clearscope", "content-harmony",
    
    # Modern FinTech & YC on Ashby
    "mercury-bank", "brex-inc", "pilot", "bench-accounting", "puzzle-io", "digits", "zamp",
    "carry-money", "compound-planning", "farther", "savvy-wealth", "range-finance", "origin-financial",
    "quid", "equityzen", "forge-global", "carta-inc", "pulley", "ltse", "captable-io", "angellist",
    "vauban", "syndicate-io", "assure", "allocations", "round-vc", "stonks", "seedinvest", "startengine",
    
    # Modern DevTools, Infrastructure & DBs on Ashby
    "supabase-inc", "convex", "railway", "fly-io", "render", "koyeb", "northflank", "porter",
    "qovery", "flightcontrol", "coherence", "zeabur", "appwrite", "nhost", "pocketbase",
    "hasura-inc", "grafbase", "wundergraph", "stepzen", "apollo-graphql", "tailcall", "inigo",
    "cosmo-graphql", "hive-graphql", "yoga-graphql", "urql", "trpc", "blitzjs", "redwoodjs",
    "remix-run", "astro-build", "svelte-society", "solidjs", "qwik-dev", "bun-sh", "deno-land",
    
    # Enterprise & High-Growth on Ashby
    "deel-inc", "remote-com", "oyster-hr", "omnipresent", "multiplier", "velocity-global",
    "papaya-global", "rippling-inc", "workmotion", "horizons-pso", "boundless-hq", "globalization-partners",
    "safeguard-global", "atlas-hcm", "elements-gs", "shield-geo", "bridge-crew", "pennylane",
    "causal", "pigment", "runway-financial", "mosaic-tech", "cube-software", "finmark", "pry-financial",
    "abacum", "jirav", "datarails", "prophix", "vena-solutions", "planful", "anaplan-careers",
    
    # Indian & Global Unicorns on Ashby
    "zeptonow", "swiggy-labs", "urban-piper", "petpooja", "dotpe", "posist", "slickpos",
    "torokus", "chaayos", "chai-point", "curefoods", "rebel-foods", "eatfit", "faasos", "behrouz",
    "box8", "freshmenu", "biryani-by-kilo", "mad-over-donuts", "wow-momo", "chai-kings", "third-wave-coffee",
    "blue-tokai", "slay-coffee", "sleepy-owl", "rage-coffee", "country-bean", "bevzilla", "abCoffee",
    "perplexity-ai", "mistral-ai", "tavily", "firecrawl", "spider-cloud", "apify-careers",
    "browserbase", "multion", "hyperwrite", "adept-ai", "character-ai", "elevenlabs",
    "resemble", "speechify-inc", "runway-ai", "luma-ai", "pika-art", "kling-ai", "suno-ai",
    "udio-ai", "haiper-ai", "hedra", "kaiber", "cartesia", "playht", "deepgram-inc"
]

# Ensure uniqueness while preserving order
def dedupe(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]

greenhouse_clean = dedupe([s.lower().strip() for s in greenhouse_companies])
lever_clean = dedupe([s.lower().strip() for s in lever_companies])
ashby_clean = dedupe([s.lower().strip() for s in ashby_companies])

seed_data = {
    "greenhouse": greenhouse_clean,
    "lever": lever_clean,
    "ashby": ashby_clean,
}

total = len(greenhouse_clean) + len(lever_clean) + len(ashby_clean)
print(f"Compiled Seed Dataset: {len(greenhouse_clean)} Greenhouse, {len(lever_clean)} Lever, {len(ashby_clean)} Ashby. Total: {total}")

out_path = Path("data/seeds/companies_seed.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(seed_data, f, indent=2)

print(f"Successfully saved to {out_path}")
