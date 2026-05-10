"""
Shared JSON parsing utilities for LLM responses.

All LLMs (Gemini, OpenAI, Claude) can ignore "return ONLY valid JSON"
instructions and wrap output in markdown fences or append trailing text.
Use extract_json_from_response() any time you need to parse JSON from
a raw LLM response string.
"""
import json
from typing import Any, Dict


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """
    Robustly extract a JSON object from an LLM response string.

    Handles:
    - Markdown fences (```json ... ``` or ``` ... ```)
    - Missing or unclosed fences
    - Text before or after the JSON block
    - Trailing commentary added by the model

    Strategy:
    1. Strip markdown fences if present (handle unclosed fence gracefully)
    2. Find the outermost { } boundaries and extract only that slice
    3. Parse with json.loads
    """
    # Step 1: strip markdown fences
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip() if end != -1 else text[start:].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip() if end != -1 else text[start:].strip()

    # Step 2: extract outermost { ... } so trailing commentary doesn't break parse
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    return json.loads(text)
