"""Pre-configured vertical keyword sets for Research section.

These keyword sets are used to run bulk searches against the Facebook Ad Library.
Keywords match against creative text (headlines + body) — not targeting keywords.

Exposed via GET /api/v1/research/vertical-config so the frontend reads them
without hardcoding. Update here only — no frontend deploy needed.
"""

VERTICAL_KEYWORD_SETS = {
    "commercial_insurance": {
        "label": "Commercial Insurance",
        "keywords": [
            "small business insurance",
            "contractor insurance",
            "business insurance quote",
            "trucking insurance",
            "restaurant insurance",
            "salon insurance",
            "general liability insurance for small business",
            "commercial property insurance",
            "business owners policy",
            "BOP insurance",
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
            # Wrong insurance verticals — use specific phrases to avoid filtering
            # carriers who offer both commercial + personal lines
            "compare car insurance",
            "overpaying for car insurance",
            "save on car insurance",
            "compare auto insurance",
            # Entertainment / drama (Meta broad match returns these)
            "heiress",
            "mistress",
            "drama",
            "episode",
            # Business coaching / lead gen (not insurance advertisers)
            "masterclass",
            "restaurant coaching",
            "qualified leads",
            "exclusive leads",
            # Home improvement / unrelated services (broad match bleed)
            "electrical panel",
            "panel upgrade",
            "hail damage",
            "temporary housing",
            "rv rental",
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
