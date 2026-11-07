"""Browser policies shared by normal and exception responses."""
SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
}


def response_headers(scope, identifier):
    headers = {**SAFE_HEADERS, "X-Request-ID": identifier}
    nonce = scope.get("state", {}).get("csp_nonce")
    path = scope.get("path", "")
    if nonce and path in {"/portal", "/admin", "/payments", "/docs", "/docs/oauth2-redirect"}:
        docs = path.startswith("/docs")
        scripts = f"'self' 'nonce-{nonce}'" + (" https://cdn.jsdelivr.net" if docs else "")
        styles = ("'self' 'unsafe-inline' https://cdn.jsdelivr.net" if docs else f"'self' 'nonce-{nonce}'")
        headers["Content-Security-Policy"] = (
            f"default-src 'none'; script-src {scripts}; style-src {styles}; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
        )
    # Trust the ASGI transport scheme, never a caller-supplied X-Forwarded-Proto here.
    if scope.get("scheme") == "https":
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers
