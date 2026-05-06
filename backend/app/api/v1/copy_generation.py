from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import google.generativeai as genai
import os
import json
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prompt

router = APIRouter()

COPY_GENERATION_PROMPT_ID = "copy_generation_system"

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("VITE_GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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
    return f"""You are a direct response copywriter specializing in lead generation ads for financial and insurance verticals (auto insurance, commercial insurance, home insurance, reverse mortgage, personal loans, debt relief). Your framework is Eugene Schwartz's Breakthrough Advertising: you write to a specific avatar at a specific awareness level, matching copy intensity to the depth of their pain.

BRAND VOICE: {request.brand.get('voice', 'Direct and trustworthy')}

OFFER / SERVICE: {request.product.get('name')}
{f"Details: {request.product.get('description')}" if request.product.get('description') else ''}

AVATAR:
- Who they are: {request.profile.get('demographics', 'Adults facing a financial or insurance decision')}
- Their pain: {request.profile.get('pain_points', 'Overpaying, uncertainty, or not knowing their options')}
- What they want: {request.profile.get('goals', 'Save money, peace of mind, or a better deal')}

CAMPAIGN:
- Hook / Offer: {request.campaignDetails.get('offer')}
- Core message: {request.campaignDetails.get('messaging')}

---

LEAD GEN COPY RULES (never break these):
- The goal is a FORM FILL or CLICK TO QUALIFY — not a purchase. Copy should move the reader toward taking the first step, not closing a sale.
- Never imply guaranteed savings, guaranteed approval, or guaranteed rates. Use "could", "may", "up to", "as low as".
- Never use "best rate", "lowest price", or absolute superlatives — Meta flags these in financial verticals.
- No income claims or specific dollar savings amounts unless they are explicitly provided in the offer.
- CTAs drive action toward a quote, comparison, or qualification check — not "Buy Now", "Shop Now", or "Order".
- Approved CTAs: "Get My Quote", "See My Rate", "Check If I Qualify", "Compare Rates", "Get a Free Quote", "See Options", "Find Out Now", "Get Started".

---

COPY STYLES — generate {count} variations and distribute across these styles:

1. PROBLEM-AWARE (Schwartz Level 2) — Avatar knows they have a problem but hasn't found a solution yet.
   - Lead with the pain: name the specific frustration (overpaying, getting denied, not knowing options)
   - Agitate briefly, then position the offer as the relief
   - Tone: empathetic, slightly urgent
   - Example structure: "Still paying [pain point]? [Quick qualifier statement]. [CTA]."

2. SOLUTION-AWARE (Schwartz Level 3) — Avatar knows solutions exist but hasn't chosen one.
   - Lead with the category benefit, then differentiate
   - Emphasize speed, simplicity, and no-obligation
   - Tone: confident, straightforward
   - Example structure: "[Benefit statement]. Takes 60 seconds. No obligation. [CTA]."

3. SOCIAL PROOF / CREDIBILITY — Uses numbers, results, or volume to build trust.
   - Lead with a proof point (number of people helped, average savings range if stated in offer, years in business)
   - Keep claims conservative and compliant
   - Bullet points with ✓ work well here
   - Example: "✓ Compare multiple options in minutes\n✓ No obligation, no spam\n✓ See your rate instantly"

FORMATTING RULES:
- Headlines: under 40 characters. Pattern options: question ("Overpaying for {vertical}?"), statement ("Lower your {vertical} bill"), or curiosity ("Most {avatar} don't know this").
- Body: 100–160 characters for bullet styles; up to 220 for narrative styles. Line breaks between bullets.
- CTA: under 20 characters. Use one of the approved CTAs above.
- Do NOT use product/e-commerce language: no "free shipping", "in stock", "order today", "add to cart".

Return ONLY valid JSON in this exact format:
{{
  "variations": [
    {{
      "headline": "Short, direct headline",
      "body": "Lead gen body copy matching one of the three styles above",
      "cta": "Approved lead gen CTA"
    }}
  ]
}}"""


@router.post("/generate")
async def generate_copy(request: CopyGenerationRequest, db: Session = Depends(get_db)):
    """Generate ad copy variations using Gemini AI"""

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")

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
        
        # Generate with Gemini
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        
        # Parse the response
        response_text = response.text.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.startswith('```'):
            response_text = response_text[3:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        response_text = response_text.strip()
        
        # Parse JSON
        result = json.loads(response_text)
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e}")
        print(f"Response text: {response_text}")
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response as JSON: {str(e)}")
    except Exception as e:
        print(f"Copy generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Copy generation failed: {str(e)}")

@router.post("/regenerate-field")
async def regenerate_field(request: FieldRegenerationRequest):
    """Regenerate a specific field (headline, body, or cta)"""
    
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    try:
        field_prompts = {
            "headline": "Generate a new headline (under 40 characters)",
            "body": "Generate new body copy (under 125 characters for bullets, or up to 200 for storytelling)",
            "cta": "Generate a new call-to-action (under 20 characters)"
        }
        
        prompt = f"""You are a direct response copywriter specializing in lead generation ads for financial and insurance verticals. {field_prompts.get(request.field, 'Generate new copy')}.

BRAND VOICE: {request.brand.get('voice', 'Direct and trustworthy')}
OFFER / SERVICE: {request.product.get('name')}
AVATAR: {request.profile.get('demographics', 'Adults facing a financial or insurance decision')}
THEIR PAIN: {request.profile.get('pain_points', 'Overpaying or uncertainty about their options')}
CAMPAIGN HOOK: {request.campaignDetails.get('offer')}

Current {request.field}: {request.currentValue}

Generate a DIFFERENT variation that:
1. Matches the brand voice
2. Is written for lead generation (goal = form fill / click to qualify, NOT a purchase)
3. For headlines: question, statement, or curiosity format — under 40 characters
4. For CTAs: use only approved lead gen CTAs — "Get My Quote", "See My Rate", "Check If I Qualify", "Compare Rates", "Get a Free Quote", "See Options", "Find Out Now", "Get Started"
5. For body: address the avatar's pain or desire, no guaranteed savings claims, no absolute superlatives
6. Follows the character limits

Return ONLY the new {request.field} text, nothing else."""

        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        
        new_value = response.text.strip().strip('"').strip("'")
        
        return {"newValue": new_value}
        
    except Exception as e:
        print(f"Field regeneration error: {e}")
        raise HTTPException(status_code=500, detail=f"Field regeneration failed: {str(e)}")
