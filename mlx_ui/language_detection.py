from __future__ import annotations

from functools import lru_cache
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

PARAKEET_TDT_V3_LANGUAGE_CODES = (
    "bg",
    "hr",
    "cs",
    "da",
    "nl",
    "en",
    "et",
    "fi",
    "fr",
    "de",
    "el",
    "hu",
    "it",
    "lv",
    "lt",
    "mt",
    "pl",
    "pt",
    "ro",
    "sk",
    "sl",
    "es",
    "sv",
    "ru",
    "uk",
)

_MINIMUM_DETECTION_CHARACTERS = 16
_MINIMUM_DETECTION_CONFIDENCE = 0.80


class _LanguageIdentifier(Protocol):
    def classify(self, text: str) -> tuple[str, float]: ...


def detect_parakeet_transcript_language(text: str) -> tuple[str | None, float | None]:
    normalized = " ".join((text or "").split())
    if len(normalized) < _MINIMUM_DETECTION_CHARACTERS:
        return None, None

    try:
        language, confidence = _parakeet_language_identifier().classify(normalized)
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        logger.warning(
            "Parakeet transcript language detection is unavailable: %s",
            type(exc).__name__,
        )
        return None, None

    language = str(language).strip().lower()
    confidence = float(confidence)
    if (
        language not in PARAKEET_TDT_V3_LANGUAGE_CODES
        or confidence < _MINIMUM_DETECTION_CONFIDENCE
        or confidence > 1.0
    ):
        return None, None
    return language, confidence


@lru_cache(maxsize=1)
def _parakeet_language_identifier() -> _LanguageIdentifier:
    from langid.langid import LanguageIdentifier, model

    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(list(PARAKEET_TDT_V3_LANGUAGE_CODES))
    return identifier
