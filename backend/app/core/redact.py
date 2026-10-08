"""Strip secrets from text that may be logged, stored, or returned to a client.

httpx error messages embed the full request URL, which for Meta calls carries ?access_token=... .
"""
import re

_PATTERNS = (
    # name=value in a URL / query string
    (re.compile(r"(access_token|api_key|token|key|secret)=[^&\s'\"]+", re.IGNORECASE), r"\1=***"),
    # JSON body: "access_token": "..."
    (re.compile(r"(\"(?:access_token|api_key|token|secret)\"\s*:\s*)\"[^\"]*\"", re.IGNORECASE), r'\1"***"'),
    # Authorization header value
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1***"),
)


def redact_secrets(text: object) -> str:
    out = str(text)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
