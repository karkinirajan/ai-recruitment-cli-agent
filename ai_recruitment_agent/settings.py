"""Configuration read from the environment (and a `.env` file in the working directory)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

# The model used for screening. Google retires Gemini models regularly (the 1.5 and 2.0 families, which this tool used to name, are gone),
# so it can be changed with GEMINI_MODEL without a new release. Default: one of the two models Google's model list recommends for new projects.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    notion_api_key: str | None
    notion_database_id: str | None
    notion_data_source_id: str | None
    gemini_model: str

    @classmethod
    def load(cls, environ: Mapping[str, str] | None = None, *, dotenv: bool = True) -> Settings:
        """Read the settings. With `dotenv`, a `.env` file in the working directory (or a parent of it) is loaded first; it never overrides
        real variables. (`load_dotenv()` alone looks next to the *calling module*, which for an installed package is site-packages, so a
        `.env` in the user's working directory was never found.)"""
        if dotenv and environ is None:
            load_dotenv(find_dotenv(usecwd=True))
        env = os.environ if environ is None else environ

        def get(name: str) -> str | None:
            value = env.get(name, "").strip()
            return value or None

        return cls(
            gemini_api_key=get("GOOGLE_GEMINI_API_KEY"),
            notion_api_key=get("NOTION_API_KEY"),
            notion_database_id=get("DEFAULT_NOTION_DB_ID"),
            notion_data_source_id=get("NOTION_DATA_SOURCE_ID"),
            gemini_model=get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        )
