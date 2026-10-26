"""The engine Lambda: the FastAPI app of api/index.py behind API Gateway, with identity from the Cognito token."""

from __future__ import annotations

from mangum import Mangum

from api.index import app

handler = Mangum(app, lifespan="off")
