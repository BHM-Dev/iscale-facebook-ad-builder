"""Pre-configured vertical keyword sets for Research section.

These keyword sets are used to run bulk searches against the Facebook Ad Library.
Keywords match against creative text (headlines + body) — not targeting keywords.

Exposed via GET /api/v1/research/vertical-config so the frontend reads them
without hardcoding. Update here only — no frontend deploy needed.
"""

# Pages that are always blocked regardless of vertical — no DB entry needed.
# Add pages here when Meta's broad-match search returns them consistently and
# they are clearly irrelevant (drama apps, unrelated industries, etc.).
ALWAYS_BLOCKED_PAGES = [
    "popkon chase3",
    "popkon chase1 drama",
    "popkon chase1",
    "novelwhisper-a",
    "legal authority lab",
    # Home service contractors — not insurance advertisers
    "jlo ganite llc",
    "dandy painting",
    "proclaim roofing",
    # Salon/suite operators
    "phenix salon suites - houston westheimer",
    "my salon suite",
    # Construction/trade
    "total civil construction",
    "hireline construction jobs",
    "home builders association of columbia",
    # Business coaches/consultants
    "the small business planner",
    "kevin blackler",
    "zack zitting",
    "launch pros agency",
    "nak business solutions",
    # Unrelated professionals
    "stanly community college sbc",
    "legal nationwide.",
    "health by heatherrene",
]

VERTICAL_KEYWORD_SETS = {
    "commercial_insurance": {
        "label": "Commercial Insurance",
        "keywords": [
            # Niche-specific — these yield clean results vs generic broad terms
            "commercial trucking insurance",
            "contractor liability insurance",
            "restaurant business insurance",
            "salon business insurance",
            "construction company insurance",
            "landscaping business insurance",
            # Competitor brand names — returns their actual running ads directly
            "Hiscox business insurance",
            "NEXT Insurance small business",
            "Simply Business insurance",
            "biBERK insurance",
            "Thimble insurance",
            "CoverWallet business insurance",
        ],
        "negative_keywords": [
            # Personal injury / legal
            "personal injury",
            "injury attorney",
            "lawsuit",
            "class action",
            "car accident",
            "accident attorney",
            "law group",
            "law firm",
            "hurt at work",
            "workers compensation",
            "workers comp",
            "workers rights",
            "pro athlete",
            "pro athletes",
            "retired pro",
            # Medical / mental health
            "TMS",
            "tms therapy",
            "transcranial",
            "therapy",
            "depression",
            "mental health",
            "health insurance",
            "individual plan",
            "family plan",
            "self-employed health",
            # Wrong insurance verticals
            "compare car insurance",
            "overpaying for car insurance",
            "save on car insurance",
            "compare auto insurance",
            # Entertainment / drama
            "heiress",
            "mistress",
            "drama",
            "episode",
            # Business coaching / lead gen
            "masterclass",
            "restaurant coaching",
            "qualified leads",
            "exclusive leads",
            # Home improvement / unrelated services
            "electrical panel",
            "panel upgrade",
            "hail damage",
            "temporary housing",
            "rv rental",
            # Contractors/tradespeople/service businesses advertising their OWN services
            # (they mention being insured but are not selling insurance)
            "free in-home visit",
            "free in-home estimate",
            "we come to you",
            "upgrade your fireplace",
            "natural stone",
            "stone installation",
            "fireplace makeover",
            "interior painting",
            "exterior painting",
            "roof replacement",
            "roof repair",
            "gutter installation",
            "floor installation",
            "deck installation",
            "fence installation",
            "tree removal",
            "pressure washing",
            "remodeling",
            "renovation",
            # Salon/suite franchise operators (buying insurance, not selling)
            "salon suite",
            "salon suites",
            "booth rental",
            "rent a suite",
            # Construction/trade companies (not insurers)
            "construction jobs",
            "construction hiring",
            "general contractor",
            "subcontractor",
            # Hiring / recruiting signals
            "we're hiring",
            "now hiring",
            "join our team",
            "open positions",
            # Business coaches, consultants, educators (not insurers)
            "business coach",
            "business planner",
            "small business coach",
            "community college",
            "trade association",
            "builders association",
            "contractors association",
            # Unrelated professionals
            "realtor",
            "real estate agent",
            "medical billing",
            "bookkeeper",
            "accounting firm",
        ],
        # At least one relevance term must appear in the ad text.
        # Filters ads that Meta returns via broad/semantic match but have no
        # insurance-related content (drama apps, coaching, unrelated industries).
        "relevance_terms": [
            "insurance", "insure", "insured", "coverage", "policy",
            "liability", "premium", "quote", "bop", "commercial",
            "protect your business", "business owner",
        ],
    },
    "auto_insurance": {
        "label": "Auto Insurance",
        "keywords": [
            "auto insurance",
            "car insurance",
            "vehicle insurance",
            "car insurance quote",
            "auto insurance quote",
            "save on car insurance",
            "cheap car insurance",
            "switch and save",
            "full coverage",
            "SR-22",
        ],
        "negative_keywords": ["home insurance", "life insurance", "health insurance"],
        "relevance_terms": [
            "insurance", "insure", "insured", "coverage", "policy",
            "premium", "quote", "auto", "vehicle", "driver", "car",
        ],
    },
    "home_services": {
        "label": "Home Services",
        "negative_keywords": ["personal injury", "lawsuit", "attorney"],
        "sub_verticals": {
            "floor_installation": {
                "label": "Floor Installation",
                "keywords": [
                    "floor installation",
                    "flooring contractor",
                    "hardwood floors",
                    "laminate flooring",
                    "floor replacement",
                    "new floors",
                ],
                "relevance_terms": ["floor", "flooring", "hardwood", "laminate", "vinyl", "tile", "carpet"],
            },
            "interior_painting": {
                "label": "Interior Painting",
                "keywords": [
                    "interior painting",
                    "interior painters",
                    "house painting",
                    "painting contractor",
                    "home painting",
                    "interior paint",
                ],
                "relevance_terms": ["paint", "painting", "painter", "coat", "interior", "wall"],
            },
            "mold_remediation": {
                "label": "Mold Remediation",
                "keywords": [
                    "mold remediation",
                    "mold removal",
                    "mold inspection",
                    "black mold",
                    "mold testing",
                ],
                "relevance_terms": ["mold", "mildew", "remediation", "water damage", "moisture", "fungus"],
            },
            "patio_remodel": {
                "label": "Patio Remodel",
                "keywords": [
                    "patio installation",
                    "patio remodel",
                    "patio addition",
                    "patio contractor",
                    "deck installation",
                    "outdoor living space",
                ],
                "relevance_terms": ["patio", "deck", "outdoor", "pergola", "hardscape", "backyard"],
            },
            "fence_gate": {
                "label": "Fence & Gate",
                "keywords": [
                    "fence installation",
                    "fence contractor",
                    "privacy fence",
                    "gate installation",
                    "wood fence",
                    "vinyl fence",
                ],
                "relevance_terms": ["fence", "fencing", "gate", "privacy", "picket", "wood fence", "vinyl fence"],
            },
            "gutters": {
                "label": "Gutters",
                "keywords": [
                    "gutter installation",
                    "gutter replacement",
                    "rain gutters",
                    "gutter contractor",
                    "new gutters",
                ],
                "relevance_terms": ["gutter", "downspout", "rain gutter", "drainage", "eavestrough"],
            },
            "tree_service": {
                "label": "Tree Service",
                "keywords": [
                    "tree removal",
                    "tree trimming",
                    "tree service",
                    "tree cutting",
                    "stump removal",
                    "arborist",
                ],
                "relevance_terms": ["tree", "stump", "arborist", "branch", "pruning", "trimming"],
            },
        },
    },
}

# Valid angle tags for research ad curation
ANGLE_TAGS = [
    {"value": "fear", "label": "Fear", "color": "red"},
    {"value": "social_proof", "label": "Social Proof", "color": "blue"},
    {"value": "urgency", "label": "Urgency", "color": "orange"},
    {"value": "savings", "label": "Savings", "color": "green"},
    {"value": "authority", "label": "Authority", "color": "purple"},
    {"value": "story", "label": "Story", "color": "amber"},
    {"value": "curiosity", "label": "Curiosity", "color": "teal"},
]
