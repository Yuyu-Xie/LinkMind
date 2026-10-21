from urllib.parse import quote, unquote, urlencode, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Normalize a URL for duplicate detection.

    Lowercases scheme and host, sorts query parameters, and trims a trailing
    slash from the path. Fragments are preserved because they can identify a
    distinct document section.
    """
    if not url:
        return ""
    url = url.strip()
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url

        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        port = f":{parsed.port}" if parsed.port else ""
        userinfo = ""
        if parsed.username:
            userinfo = quote(parsed.username, safe="")
            if parsed.password:
                userinfo += ":" + quote(parsed.password, safe="")
            userinfo += "@"

        path = parsed.path.rstrip("/")
        query_pairs = []
        if parsed.query:
            for part in parsed.query.split("&"):
                if not part:
                    continue
                key, _, value = part.partition("=")
                query_pairs.append((unquote(key), unquote(value)))
        query = urlencode(sorted(query_pairs), doseq=True, safe=":/")

        netloc = f"{userinfo}{hostname}{port}"
        return urlunparse((scheme, netloc, path, parsed.params, query, parsed.fragment))
    except (ValueError, UnicodeError):
        return url


def word_tokens(text: str) -> list[str]:
    """Split mixed Chinese/English text into searchable tokens."""
    tokens: list[str] = []
    current = []
    for char in (text or "").lower():
        if char.isalnum() or char in {"_", "-", "+", "#"}:
            current.append(char)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens
