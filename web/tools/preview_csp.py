#!/usr/bin/env python3
"""Restrict a copied browser shell's network policy for public PR previews."""
import re
import sys


META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
CSP_ATTRIBUTE = re.compile(
    r"\bhttp-equiv\s*=\s*([\"'])content-security-policy\1", re.IGNORECASE
)
CONTENT_ATTRIBUTE = re.compile(r"\bcontent\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
CONNECT_DIRECTIVE = re.compile(r"(?<![\w-])connect-src\s+[^;]+", re.IGNORECASE)


def restrict_preview_csp(html: str) -> str:
    """Keep the trusted policy but allow connections only to the preview origin."""
    tags = [match for match in META_TAG.finditer(html) if CSP_ATTRIBUTE.search(match.group(0))]
    if len(tags) != 1:
        raise ValueError("Expected exactly one Content-Security-Policy meta tag")

    tag = tags[0].group(0)
    content = CONTENT_ATTRIBUTE.search(tag)
    if not content:
        raise ValueError("CSP meta tag has no content attribute")
    policy = content.group(2)
    rewritten, count = CONNECT_DIRECTIVE.subn("connect-src 'self'", policy)
    if count != 1:
        raise ValueError("Expected exactly one connect-src directive")
    updated_tag = tag[:content.start(2)] + rewritten + tag[content.end(2):]
    return html[:tags[0].start()] + updated_tag + html[tags[0].end():]


if __name__ == "__main__":
    try:
        sys.stdout.write(restrict_preview_csp(sys.stdin.read()))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
