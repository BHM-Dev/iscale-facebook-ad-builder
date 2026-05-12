from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import anthropic
import os
import json
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prompt
from app.utils.json_utils import extract_json_from_response

router = APIRouter()

COPY_GENERATION_PROMPT_ID = "copy_generation_system"

# Anthropic client — instantiated once at module level
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

_MODEL = "claude-3-5-sonnet-20241022"

class CopyGenerationRequest(BaseModel):
    brand: Dict[str, Any]
    product: Dict[str, Any]
    profile: Dict[str, Any]
    template: Optional[Dict[str, Any]] = None
    variationCount: int = 3
    campaignDetails: Dict[str, str]
    customPrompt: Optional[str] = None

class FieldRegenerationRequest(BaseModel):
    field: str
    currentValue: str
    brand: Dict[str, Any]
    product: Dict[str, Any]
    profile: Dict[str, Any]
    template: Optional[Dict[str, Any]] = None
    campaignDetails: Dict[str, str]

def _build_default_prompt(count: int, request: "CopyGenerationRequest") -> str:
    return f"""You are a direct response copywriter trained on Eugene Schwartz's Breakthrough Advertising. You write Facebook lead gen ads for financial and insurance verticals — auto insurance, commercial insurance, home insurance, reverse mortgage, personal loans, debt relief.

Your job is not to write "ad copy." Your job is to take a mass desire that already exists inside this avatar — a frustration, a fear, a hope — and channel it precisely toward one action: clicking to qualify. You do not create desire. You locate it and focus it.

---

INPUTS:

Brand voice: {request.brand.get('voice', 'Direct and trustworthy')}
Offer / service: {request.product.get('name')}{(chr(10) + 'Details: ' + request.product.get('description')) if request.product.get('description') else ''}
Who this avatar is: {request.profile.get('demographics', 'Adults in a financial or insurance decision')}
Their pain: {request.profile.get('pain_points', 'Overpaying, uncertainty, or not knowing their options')}
What they want: {request.profile.get('goals', 'Save money, peace of mind, or a better deal')}
Campaign hook: {request.campaignDetails.get('offer')}
Core message: {request.campaignDetails.get('messaging')}

---

STEP 1 — DIAGNOSE AWARENESS STAGE (Schwartz, Chapter 2)

Before writing, silently identify where this avatar sits on the awareness scale:

• Stage 5 — MOST AWARE: Knows the product, wants it, just hasn't acted. Lead with the name + deal/price. Nothing more needed.
• Stage 4 — PRODUCT AWARE: Knows the product exists but isn't fully convinced or hasn't seen enough reason to move. Reinforce desire, sharpen the benefit, introduce new proof or a new mechanism.
• Stage 3 — SOLUTION AWARE: Knows they want a solution (lower rates, less debt, better coverage), doesn't yet know your product is the answer. Name the desired outcome in the headline, prove you can deliver, present your product as the path.
• Stage 2 — PROBLEM AWARE: Knows they have a problem (overpaying, underinsured, drowning in debt), doesn't know a solution exists or is accessible. Open by naming and intensifying the specific pain. Then offer relief.
• Stage 1 — UNAWARE: Doesn't consciously recognize the problem or won't admit it. Start with a universally felt emotion, image, or identity — not the product at all. Pull them in sideways.

Most financial/insurance prospects are at Stage 2 or 3. Write to the stage that matches the hook and pain provided.

---

STEP 2 — DIAGNOSE MARKET SOPHISTICATION (Schwartz, Chapter 3)

These verticals are saturated. Prospects have seen "Save on insurance" and "Lower your rate" a thousand times.

• Stage 1 (Unsophisticated): First product in the market — simple direct claim.
• Stage 2: Competition exists — enlarge the claim, push it further.
• Stage 3 (Most financial verticals): Claims are worn out — you MUST introduce a new mechanism, a new angle, or a specific niche. Generic claims will be ignored.
• Stage 4: Mechanisms are worn out too — lead with personality, identity, or a very specific avatar ("for small business owners in [state]", "if you're 62 or older and own your home").
• Stage 5: Dead market — complete repositioning required.

Insurance, mortgage, and loan verticals are at Stage 3–4. Do NOT open with tired claims. Find the specific mechanism, the niche angle, or the identity hook that makes this ad feel new and relevant to the exact person scrolling past it.

---

STEP 3 — MATCH THE LANGUAGE (Joel's Rule)

Write in the voice of the avatar — not in "advertiser voice." Before writing, think: how does this person describe their own problem on Reddit, in a Facebook comment, or to a friend?

Examples of avatar voice by vertical:
- Auto insurance: "I've been with [company] for 10 years and my rate just went up again for no reason"
- Commercial insurance: "I need coverage but I don't have time to call 5 brokers"
- Personal loans: "I just need a few thousand to get through this — I don't want to get ripped off"
- Debt relief: "I'm embarrassed by how much I owe. I just want a way out that doesn't destroy my credit"
- Reverse mortgage: "I own my home but I'm cash-poor. I don't want to sell but I need options"

Use short sentences. Use "you." Use the specific words they use — not polished corporate language. The copy should feel like it was written by someone who understood them, not by someone selling at them. AI-generated language is fine as long as it reads naturally — no stiff phrasing, no robotic transitions.

---

STEP 4 — LEAD GEN COMPLIANCE RULES (never break these)

- Goal is FORM FILL or CLICK TO QUALIFY — not a purchase. Move toward the first step.
- Never guarantee savings, approval, or rates. Use "could", "may", "up to", "as low as".
- No absolute superlatives ("best rate", "lowest price") — Meta flags these in financial verticals.
- No specific dollar savings claims unless explicitly stated in the offer above.
- No e-commerce language: no "free shipping", "in stock", "order today", "buy now", "add to cart".
- Approved CTAs only: "Get My Quote", "See My Rate", "Check If I Qualify", "Compare Rates", "Get a Free Quote", "See Options", "Find Out Now", "Get Started".

---

STEP 5 — GENERATE {count} VARIATIONS

Spread the variations across different awareness strategies and copy formats. For each variation, use the strategy best matched to the awareness stage and sophistication level you diagnosed.

Format options:
- Problem-lead: Open with the specific pain in the avatar's own words. Agitate briefly. Offer the relief. CTA.
- Benefit-lead: Open with the desired outcome. Show it's fast/easy/no-obligation. CTA.
- Mechanism: Introduce a specific how or why this works differently. Name the mechanism. CTA.
- Identity/niche: Call out the exact avatar ("If you're a [descriptor]…"). Make them feel seen. CTA.
- Social proof: Lead with volume, results, or trust signal. Bullet the simplicity. CTA.

Formatting constraints:
- Headline: under 40 characters. Question, bold statement, or curiosity gap.
- Body: 100–220 characters. Line breaks between bullet points if using bullets.
- CTA: under 20 characters. Approved list only.

---

Return ONLY valid JSON in this exact format — no markdown, no code fences, no explanatory text:
{{
  "variations": [
    {{
      "headline": "Short, direct headline under 40 chars",
      "body": "Body copy matching the diagnosed awareness stage and avatar voice",
      "cta": "Approved lead gen CTA"
    }}
  ]
}}"""


@router.post("/generate")
async def generate_copy(request: CopyGenerationRequest, db: Session = Depends(get_db)):
    """Generate ad copy variations using Claude AI"""

    if not _anthropic_client:
        raise HTTPException(status_code=500, detail="Anthropic API key not configured")

    try:
        count = request.variationCount

        # Use explicit custom prompt if provided, otherwise check DB for an edited system prompt,
        # then fall back to the built-in default
        if request.customPrompt:
            prompt = request.customPrompt
        else:
            db_prompt = db.query(Prompt).filter(Prompt.id == COPY_GENERATION_PROMPT_ID).first()
            if db_prompt:
                prompt = db_prompt.template.format(
                    count=count,
                    brand_voice=request.brand.get('voice', 'Professional and friendly'),
                    product_name=request.product.get('name', ''),
                    product_description=request.product.get('description', ''),
                    demographics=request.profile.get('demographics', 'General audience'),
                    pain_points=request.profile.get('pain_points', 'Not specified'),
                    goals=request.profile.get('goals', 'Not specified'),
                    offer=request.campaignDetails.get('offer', ''),
                    messaging=request.campaignDetails.get('messaging', ''),
                    design_style=request.template.get('design_style', 'Modern and clean') if request.template else 'Modern and clean',
                )
            else:
                prompt = _build_default_prompt(count, request)

        response = _anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        response_text = response.content[0].text.strip()

        # Parse JSON — extract_json_from_response handles markdown fences and trailing text
        result = extract_json_from_response(response_text)

        return result

    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response as JSON: {str(e)}")
    except Exception as e:
        print(f"Copy generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Copy generation failed: {str(e)}")

@router.post("/regenerate-field")
async def regenerate_field(request: FieldRegenerationRequest):
    """Regenerate a specific field (headline, body, or cta)"""

    if not _anthropic_client:
        raise HTTPException(status_code=500, detail="Anthropic API key not configured")

    try:
        field_prompts = {
            "headline": "Generate a new headline (under 40 characters)",
            "body": "Generate new body copy (under 125 characters for bullets, or up to 200 for storytelling)",
            "cta": "Generate a new call-to-action (under 20 characters)"
        }

        prompt = f"""You are a direct response copywriter trained on Eugene Schwartz's Breakthrough Advertising. You write Facebook lead gen ads for financial and insurance verticals.

BRAND VOICE: {request.brand.get('voice', 'Direct and trustworthy')}
OFFER / SERVICE: {request.product.get('name')}
AVATAR: {request.profile.get('demographics', 'Adults facing a financial or insurance decision')}
THEIR PAIN: {request.profile.get('pain_points', 'Overpaying or uncertainty about their options')}
THEIR GOAL: {request.profile.get('goals', 'Save money, peace of mind, or a better deal')}
CAMPAIGN HOOK: {request.campaignDetails.get('offer')}
CORE MESSAGE: {request.campaignDetails.get('messaging')}

Current {request.field}: {request.currentValue}

{field_prompts.get(request.field, 'Generate new copy')} that is DIFFERENT from the current value above.

Rules:
- Write in the avatar's voice — short sentences, "you" language, words they'd actually use (think Reddit/forum voice, not corporate ad copy)
- Goal is form fill / click to qualify — NOT a purchase
- This is a saturated market (Stage 3–4 Schwartz sophistication) — avoid generic tired claims like "save on insurance" or "lower your rate" unless you give them a specific mechanism or angle that feels new
- Match the Schwartz awareness stage that fits the pain: if avatar is Problem-Aware (knows they have a problem), lead with the pain; if Solution-Aware, lead with the outcome
- For headlines: question, bold statement, identity call-out, or curiosity gap — under 40 characters
- For body: 100–220 characters. No guaranteed savings, no absolute superlatives, no e-commerce language
- For CTAs: use ONLY — "Get My Quote", "See My Rate", "Check If I Qualify", "Compare Rates", "Get a Free Quote", "See Options", "Find Out Now", "Get Started"
- Sounds like a human wrote it, not AI

Return ONLY the new {request.field} text, nothing else."""

        response = _anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=512,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        new_value = response.content[0].text.strip().strip('"').strip("'")

        return {"newValue": new_value}

    except Exception as e:
        print(f"Field regeneration error: {e}")
        raise HTTPException(status_code=500, detail=f"Field regeneration failed: {str(e)}")


class RemixVariationsRequest(BaseModel):
    source_headline: str
    source_body: str
    hook: str
    niche: str
    brand_name: Optional[str] = ""
    brand_voice: Optional[str] = ""
    vertical: Optional[str] = "commercial_insurance"


@router.post("/remix-variations")
async def remix_variations(request: RemixVariationsRequest):
    """Generate 3 remix variations of a winning ad using a new hook and/or niche.

    Kept separate from /generate because remix has a fundamentally different input
    contract: it takes a source (winning) ad as context instead of a full
    brand/product/profile payload. The prompt is also tighter — the goal is
    copy variation to fight ad fatigue, not a full creative brief from scratch.
    """

    if not _anthropic_client:
        raise HTTPException(status_code=500, detail="Anthropic API key not configured")

    prompt = f"""You are a direct response copywriter trained on Eugene Schwartz's Breakthrough Advertising. You write Facebook lead gen ads for {request.vertical.replace('_', ' ')} — NOT ecommerce. No discounts, no products to buy. Ads drive form submissions.

A media buyer has a winning ad and wants 3 variations. Their job is to remix the same emotional angle with slight copy variations — different sentence structure, different opening word, different proof element — to fight ad fatigue while keeping what made the original work.

WINNING AD:
Headline: {request.source_headline}
Body: {request.source_body}

REMIX PARAMETERS:
- Hook/Angle to preserve or riff on: {request.hook}
- Niche: {request.niche or 'same as original'}
- Brand: {request.brand_name or 'not specified'}
{f'- Brand voice: {request.brand_voice}' if request.brand_voice else ''}

RULES:
- Each variation keeps the same emotional core as the winning ad but uses different words, structure, or proof
- Headline: under 60 characters, punchy, no clickbait, no ALL CAPS
- Body: 2-4 sentences max, conversational, written like a person not a brand
  # NOTE (UI): Meta recommends ≤125 characters for primary text in some placements (e.g. Feed).
  # The 2-4 sentence guideline above routinely produces 150-250+ char bodies. This is a prompt
  # tuning tradeoff — shorter bodies lose conversational tone. If Joel flags truncation in
  # previews, revisit with a tighter constraint (e.g. "2 sentences max, under 130 characters").
- Do NOT use: "Are you...", "Did you know...", discount language, urgency pressure tactics, emojis
- Write for awareness Stage 3-4 (solution-aware to product-aware) — they know their problem exists
- Use the niche context naturally if provided

Return ONLY valid JSON, no markdown:
{{"variations": [{{"headline": "...", "body": "..."}}, {{"headline": "...", "body": "..."}}, {{"headline": "...", "body": "..."}}]}}"""

    try:
        response = _anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        text = response.content[0].text.strip()

        # Parse JSON — extract_json_from_response handles fences and trailing text
        data = extract_json_from_response(text)
        variations = data.get("variations", [])
        if not variations:
            raise ValueError("No variations returned from model")
        return {"variations": variations}
    except Exception as e:
        print(f"Remix variations error: {e}")
        raise HTTPException(status_code=500, detail=f"Remix generation failed: {str(e)}")
