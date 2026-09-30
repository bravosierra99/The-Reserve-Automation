"""Cookie helpers shared by every route that calls ``response.set_cookie``.

Why this exists: a cookie sent with ``Secure`` from a plain-http origin is
*silently discarded* by the browser. No error, no console warning. Setting
``secure=True`` unconditionally therefore broke every cookie on direct LAN
access (http://192.168.x.x:8000) while looking like it worked — the response
carried the header, the browser threw it away, and the next request arrived
without it. That is how event participants ended up dropping out of event mode
between joining and opening the tasting wizard.

#CLAUDE_REQ: the Cloudflare JWT header name here must match
config/auth.yaml -> cloudflare.jwt_header and web/auth/middleware.py.
"""

from starlette.requests import Request

DEFAULT_CF_JWT_HEADER = "Cf-Access-Jwt-Assertion"


def _cf_jwt_header_name(request: Request) -> str:
    auth_config = getattr(request.app.state, "auth_config", None)
    header = getattr(getattr(auth_config, "cloudflare", None), "jwt_header", None)
    return header or DEFAULT_CF_JWT_HEADER


def is_secure_request(request: Request) -> bool:
    """Whether this request reached us over https, as far as we can tell.

    Three signals, OR'd, deliberately biased toward "yes":

    1. A Cloudflare Access JWT header. Anything carrying one came through the
       Cloudflare Tunnel, which is https end to end at the browser. This is the
       load-bearing signal in production, because X-Forwarded-Proto is NOT —
       cloudflared speaks plain http to NPM, so NPM stamps ``$scheme`` as
       ``http`` and an XFP-only check would strip Secure from every real user.
    2. X-Forwarded-Proto, for any proxy that does terminate TLS itself.
    3. The request's own scheme, for direct https.

    Failing "secure" is the safe direction: the only request that trips none of
    these is a direct hit on the app port with no proxy in front, i.e. the LAN
    dev path — where a Secure cookie would have been discarded anyway, so
    dropping the attribute takes nothing away.
    """
    if request.headers.get(_cf_jwt_header_name(request)):
        return True

    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto.split(",")[0].strip().lower() == "https":
        return True

    return request.url.scheme == "https"
