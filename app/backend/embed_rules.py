"""Domain/URL whitelist rules for the embeddable chatbot widget.

A chatbot may restrict the pages its widget renders on to a configurable whitelist. Each rule is a
host with an optional path pattern, optionally prefixed with a scheme (which is ignored):

    *.snap.de                       any subdomain of snap.de (apex snap.de excluded)
    publishone.snap.de             that host, any path
    publishone.snap.de/preise.html that host, that exact path
    www.customer-website.com       that host, any path
    help.customer-website.com/*    that host, any path beneath it

Semantics (kept in lockstep with the client-side matcher in app/frontend/src/widget/widget.ts):

- An empty whitelist means "allow all" (matches today's permissive default).
- Host match is case-insensitive. ``*.host`` matches any subdomain (one or more labels) but not the
  apex. Otherwise the host must match exactly.
- Path match is case-sensitive. No path (or ``/`` or ``/*``) matches any path; a trailing ``/*`` (or
  ``*``) is a prefix match; otherwise the path must match exactly. The query string is ignored.

Only the *origin* portion of a rule can be enforced by the backend via the ``frame-ancestors`` CSP
header; path-level rules are enforced solely by the client-side widget matcher.
"""

import re
from typing import Optional
from urllib.parse import urlparse

SCHEME_PREFIX_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def parse_rule(rule: str) -> Optional[tuple[str, Optional[str]]]:
    """Split a rule into (host, path_pattern). ``path_pattern`` is None when the rule has no path."""
    if not isinstance(rule, str):
        return None
    candidate = SCHEME_PREFIX_PATTERN.sub("", rule.strip())
    if not candidate:
        return None
    if "/" in candidate:
        host, remainder = candidate.split("/", 1)
        path: Optional[str] = "/" + remainder
    else:
        host, path = candidate, None
    host = host.strip().lower()
    if not host:
        return None
    return host, path


def normalize_rule(rule: str) -> Optional[str]:
    """Return a canonical string form of a rule (scheme stripped, host lowercased), or None."""
    parsed = parse_rule(rule)
    if parsed is None:
        return None
    host, path = parsed
    return host if path is None else f"{host}{path}"


def normalize_rules(rules: list[str]) -> list[str]:
    """Normalize, drop blanks, and de-duplicate a list of rules, preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        canonical = normalize_rule(rule)
        if canonical and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    return normalized


def host_matches(pattern_host: str, url_host: str) -> bool:
    url_host = (url_host or "").lower()
    if not url_host:
        return False
    if pattern_host.startswith("*."):
        suffix = pattern_host[1:]  # ".snap.de"
        return url_host.endswith(suffix) and len(url_host) > len(suffix)
    return url_host == pattern_host


def path_matches(pattern_path: Optional[str], url_path: str) -> bool:
    if pattern_path is None or pattern_path in ("", "/", "/*"):
        return True
    url_path = url_path or "/"
    if pattern_path.endswith("/*"):
        prefix = pattern_path[:-2]  # "/docs"
        return url_path == prefix or url_path.startswith(prefix + "/")
    if pattern_path.endswith("*"):
        return url_path.startswith(pattern_path[:-1])
    return url_path == pattern_path


def match_url(rules: list[str], url: str) -> bool:
    """True if ``url`` is allowed by the whitelist (an empty whitelist allows everything)."""
    parsed_rules = [r for r in (parse_rule(rule) for rule in rules) if r is not None]
    if not parsed_rules:
        return True
    try:
        parsed_url = urlparse(url)
    except ValueError:
        return False
    url_host = parsed_url.hostname or ""
    url_path = parsed_url.path or "/"
    return any(host_matches(host, url_host) and path_matches(path, url_path) for host, path in parsed_rules)


def rules_to_frame_ancestors(rules: list[str]) -> str:
    """Build the ``Content-Security-Policy: frame-ancestors`` value for a whitelist.

    Empty whitelist -> ``*`` (allow all). Otherwise ``'self'`` plus each rule's host source (paths
    are dropped, since CSP cannot enforce them). ``'self'`` keeps our own demo/preview pages working.
    """
    parsed_rules = [r for r in (parse_rule(rule) for rule in rules) if r is not None]
    if not parsed_rules:
        return "*"
    sources: list[str] = []
    seen: set[str] = set()
    for host, _path in parsed_rules:
        if host not in seen:
            seen.add(host)
            sources.append(host)
    return "'self' " + " ".join(sources)
