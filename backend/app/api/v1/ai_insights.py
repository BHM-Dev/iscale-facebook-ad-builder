"""
AI Insights — natural language queries powered by Claude + Meta Ads MCP.

POST /api/v1/ai-insights/query
  Body: { "query": "...", "ad_account_id": "act_123" }
  Returns: { "answer": "..." }

Claude calls the Meta MCP server (mcp.facebook.com/ads) using the stored
FACEBOOK_ACCESS_TOKEN so it has live access to the account's campaigns,
ad sets, and performance data when answering Joel's questions.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
import logging
from app.core.deps import get_current_active_user
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
META_MCP_URL = "https://mcp.facebook.com/ads"

_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


class InsightQueryRequest(BaseModel):
    query: str
    ad_account_id: Optional[str] = None


class InsightQueryResponse(BaseModel):
    answer: str


SYSTEM_PROMPT = """You are an expert Meta Ads analyst for a performance marketing team.
You have direct access to live Meta ad account data via the Meta Ads MCP tools.

When answering questions:
- Pull real data using the available MCP tools rather than making assumptions
- Be concise and direct — the user is a media buyer, not a data scientist
- Lead with the number, then the context
- Flag anything that needs immediate attention
- Use $ for spend, % for rates, x for ROAS multipliers
- If asked about "today" or "this week", use the appropriate date preset

You are talking to Joel, the media buyer who manages these campaigns daily."""


@router.post("/query", response_model=InsightQueryResponse)
def query_insights(body: InsightQueryRequest, current_user: User = Depends(get_current_active_user)):
    if not _anthropic_client:
        raise HTTPException(503, "AI service not configured — ANTHROPIC_API_KEY missing")
    if not FACEBOOK_ACCESS_TOKEN:
        raise HTTPException(503, "Meta access token not configured — FACEBOOK_ACCESS_TOKEN missing")

    # Append ad account context to the query if provided
    query = body.query
    if body.ad_account_id:
        query = f"[Ad account: {body.ad_account_id}]\n\n{query}"

    def _extract_text(response) -> str:
        parts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(parts).strip() or "No response generated."

    # --- Attempt 1: Claude + Meta MCP (live account data) ---
    try:
        response = _anthropic_client.beta.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
            mcp_servers=[
                {
                    "type": "url",
                    "url": META_MCP_URL,
                    "name": "meta-ads",
                    "authorization_token": FACEBOOK_ACCESS_TOKEN,
                }
            ],
            betas=["mcp-client-2025-04-04"],
        )
        return InsightQueryResponse(answer=_extract_text(response))

    except anthropic.APIError as e:
        error_str = str(e).lower()
        is_mcp_auth = "authentication error" in error_str and "mcp" in error_str
        is_mcp_invalid = "invalid_request_error" in error_str and "mcp" in error_str

        if not (is_mcp_auth or is_mcp_invalid):
            # Non-MCP error — don't retry, surface it
            logger.error("Anthropic API error in ai_insights: %s", e)
            raise HTTPException(502, f"AI service error: {str(e)}")

        # MCP auth failed — the system token isn't accepted by Meta's MCP server.
        # Fall back to Claude answering from general knowledge, flagging the limitation.
        logger.warning("Meta MCP auth failed, falling back to non-MCP response: %s", e)

    except Exception as e:
        logger.error("Unexpected error in ai_insights (MCP attempt): %s", e)
        raise HTTPException(500, f"Query failed: {str(e)}")

    # --- Fallback: Claude without live Meta data ---
    fallback_system = (
        SYSTEM_PROMPT
        + "\n\nIMPORTANT: You do NOT have live access to this Meta account right now — "
        "the Meta data connection requires a fresh OAuth token. Answer the question as best "
        "you can from general Meta Ads knowledge, and be upfront that you're working without "
        "live account data. Suggest the user check Campaign Performance in the app for live numbers."
    )
    try:
        response = _anthropic_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=fallback_system,
            messages=[{"role": "user", "content": query}],
        )
        answer = _extract_text(response)
        return InsightQueryResponse(answer=f"⚠️ Live Meta data unavailable (token needs refresh) — answering from general knowledge:\n\n{answer}")

    except anthropic.APIError as e:
        logger.error("Anthropic fallback error in ai_insights: %s", e)
        raise HTTPException(502, f"AI service error: {str(e)}")
    except Exception as e:
        logger.error("Unexpected fallback error in ai_insights: %s", e)
        raise HTTPException(500, f"Query failed: {str(e)}")
