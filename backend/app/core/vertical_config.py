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
            "commercial insurance",
            "business insurance",
            "contractor insurance",
            "general liability",
            "workers comp",
            "workers compensation",
            "small business insurance",
            "commercial auto insurance",
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
    },
    "home_services": {
        "label": "Home Services",
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
