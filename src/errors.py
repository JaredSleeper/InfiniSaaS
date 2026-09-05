"""Turn exceptions into messages safe to persist or show in the UI.

Third-party client errors (httpx in particular) embed the request URL, which for
webhook-style integrations *is* the secret, so URLs and bearer-like tokens are
stripped before anything leaves the server.
"""

import re

import httpx

_URL_RE = re.compile(r"https?://[^\s'\"<>]+")
_TOKEN_RE = re.compile(r"\b(sk|rk|pk|whsec|ghp|github_pat|xox[abp])_[A-Za-z0-9_-]{8,}")


def redact(text: str) -> str:
    text = _URL_RE.sub("<url>", text)
    return _TOKEN_RE.sub("<redacted>", text)


def safe_error(exc: BaseException, limit: int = 500) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        msg = f"HTTP {exc.response.status_code} from {exc.request.url.host}"
    elif isinstance(exc, httpx.HTTPError):
        msg = f"{type(exc).__name__}: {redact(str(exc))}"
    else:
        msg = redact(str(exc)) or type(exc).__name__
    return msg[:limit]
