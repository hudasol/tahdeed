"""Vercel entrypoint: exposes the FastAPI app as the top-level name ``app``.

Set the Vercel project's Root Directory to ``deploy/vercel``. ``create_app()`` is cheap; the
gazetteer is loaded on the first request of each instance (about 8 s for the full UAE data).
"""

import logging
import sys

from tahdeed.api import create_app

if not logging.getLogger().handlers:  # surface the audit log in Vercel's runtime logs
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

app = create_app()
