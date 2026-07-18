"""CORS middleware setup."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings


def setup_cors(app: FastAPI) -> None:
    """Setup CORS with approved origins only."""
    origins = settings.api.cors_allowed_origins
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"], max_age=600)
