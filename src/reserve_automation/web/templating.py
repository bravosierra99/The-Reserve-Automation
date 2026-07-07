"""Shared Jinja2Templates factory.

Every route module builds its Jinja2Templates through make_templates() so all
environments share the same globals — most importantly `static_v`, the
cache-busting token appended to static asset URLs in templates
(`?v={{ static_v }}`). It is keyed to process start time, NOT the app version:
the version string frequently isn't bumped on deploy, and browsers plus the
Cloudflare edge cache /static/*.js aggressively, which has served stale
frontend code after fixes shipped. A new token per process start guarantees a
fresh URL (and therefore a cache miss everywhere) after every deploy/restart.
"""

import time

from fastapi.templating import Jinja2Templates

# One token per process start; a deploy restarts the container so every
# static URL changes and cached copies (browser or CDN edge) are bypassed.
STATIC_VERSION = str(int(time.time()))


def make_templates(directory) -> Jinja2Templates:
    templates = Jinja2Templates(directory=directory)
    templates.env.globals["static_v"] = STATIC_VERSION
    return templates
