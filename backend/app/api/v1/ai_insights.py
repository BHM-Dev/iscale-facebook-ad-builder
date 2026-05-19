"""
AI Insights — natural language queries powered by Claude + Meta Ads MCP.

POST /api/v1/ai-insights/query
  Body: { "query": "...", "ad_account_id": "act_123" }
  Returns: { "answer": "..." }

When META_MCP_TOKEN is set, Claude connects to the Meta Ads MCP server
(mcp.facebook.com/ads) using Joel's personal user access token and pulls
live campaign/ad set data to answer questions.

When META_MCP_TOKEN is not set, Claude answers from general Meta Ads
knowledge and notes that live data requires the token to be configured.
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
META_MCP_TOKEN = os.getenv("META_MCP_TOKEN", "").strip()
META_MCP_URL = "https://mcp.facebook.com/ads"

_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


class InsightQueryRequest(BaseModel):
    query: str
    ad_account_id: Optional[str] = None


class InsightQueryResponse(BaseModel):
    answer: str


SYSTEM_PROMPT_WITH_MCP = """You are an expert Meta Ads analyst for a performance marketing team.
You have direct access to live Meta ad account data via the Meta Ads MCP tools.

When answering questions:
- Pull real data using the available MCP tools rather than making assumptions
- Be concise and direct — the user is a media buyer, not a data scientist
- Lead with the number, then the context
- Flag anything that needs immediate attention
- Use $ for spend, % for rates, x for ROAS multipliers
- If asked about "today" or "this week", use the appropriate date preset

You are talking to Joel, the media buyer who manages these campaigns daily."""

SYSTEM_PROMPT_NO_MCP = (
    SYSTEM_PROMPT_WITH_MCP
    + "\n\nNote: You do not have live Meta account access in this session — "
    "META_MCP_TOKEN is not configured. Answer from general Meta Ads knowledge "
    "and be upfront about this. Direct the user to Campaign Performance in the "
    "app for live numbers."
)


def _extract_text(response) -> str:
    parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(parts).strip() or "No response generated."


@router.post("/query", response_model=InsightQueryResponse)
def query_insights(body: InsightQueryRequest, current_user: User = Depends(get_current_active_user)):
    if not _anthropic_client:
        raise HTTPException(503, "AI service not configured — ANTHROPIC_API_KEY missing")

    query = body.query
    if body.ad_account_id:
        query = f"[Ad account: {body.ad_account_id}]\n\n{query}"

    if META_MCP_TOKEN:
        # Live path — Claude + Meta MCP using Joel's personal user token
        try:
            response = _anthropic_client.beta.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                system=SYSTEM_PROMPT_WITH_MCP,
                messages=[{"role": "user", "content": query}],
                mcp_servers=[
                    {
                        "type": "url",
                        "url": META_MCP_URL,
                        "name": "meta-ads",
                        "authorization_token": META_MCP_TOKEN,
                    }
                ],
                betas=["mcp-client-2025-04-04"],
            )
            return InsightQueryResponse(answer=_extract_text(response))

        except anthropic.APIError as e:
            logger.error("Anthropic API error in ai_insights (MCP path): %s", e)
            raise HTTPException(502, f"AI service error: {str(e)}")

        except Exception as e:
            logger.error("Unexpected error in ai_insights (MCP path): %s", e)
            raise HTTPException(500, f"Query failed: {str(e)}")

    else:
        # No-token path — Claude from general knowledge, no MCP
        try:
            response = _anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                system=SYSTEM_PROMPT_NO_MCP,
                messages=[{"role": "user", "content": query}],
            )
            return InsightQueryResponse(answer=_extract_text(response))

        except anthropic.APIError as e:
            logger.error("Anthropic API error in ai_insights (no-MCP path): %s", e)
            raise HTTPException(502, f"AI service error: {str(e)}")

        except Exception as e:
            logger.error("Unexpected error in ai_insights (no-MCP path): %s", e)
            raise HTTPException(500, f"Query failed: {str(e)}")
