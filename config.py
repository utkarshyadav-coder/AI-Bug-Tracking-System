"""Central configuration. Override anything with environment variables."""
import os

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "bugtracker"),
}

# Optional: enables LLM-written root-cause + fix plans (see ai/resolution_engine.py)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
