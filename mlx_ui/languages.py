from __future__ import annotations

from dataclasses import dataclass
import re

AUTO_LANGUAGE = "auto"
LEGACY_AUTO_LANGUAGE = "any"
DEFAULT_LANGUAGE = AUTO_LANGUAGE

_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")


@dataclass(frozen=True)
class LanguageOption:
    id: str
    label: str


_COMMON_LANGUAGE_OPTIONS: tuple[LanguageOption, ...] = (
    LanguageOption(id=AUTO_LANGUAGE, label="Detect automatically"),
    LanguageOption(id="en", label="English"),
    LanguageOption(id="es", label="Spanish"),
    LanguageOption(id="fr", label="French"),
    LanguageOption(id="de", label="German"),
    LanguageOption(id="it", label="Italian"),
    LanguageOption(id="pt", label="Portuguese"),
    LanguageOption(id="ru", label="Russian"),
    LanguageOption(id="uk", label="Ukrainian"),
    LanguageOption(id="tr", label="Turkish"),
    LanguageOption(id="pl", label="Polish"),
    LanguageOption(id="nl", label="Dutch"),
    LanguageOption(id="ar", label="Arabic"),
    LanguageOption(id="hi", label="Hindi"),
    LanguageOption(id="ja", label="Japanese"),
    LanguageOption(id="ko", label="Korean"),
    LanguageOption(id="zh", label="Chinese"),
)

_COMMON_LANGUAGE_LABELS = {
    option.id: option.label
    for option in _COMMON_LANGUAGE_OPTIONS
    if option.id != AUTO_LANGUAGE
}


def parse_language(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower().replace("_", "-")
    if not candidate:
        return None
    if candidate in {AUTO_LANGUAGE, LEGACY_AUTO_LANGUAGE}:
        return AUTO_LANGUAGE
    if _LANGUAGE_CODE_PATTERN.fullmatch(candidate):
        return candidate
    return None


def normalize_language(value: object, *, default: str = DEFAULT_LANGUAGE) -> str:
    parsed = parse_language(value)
    if parsed is not None:
        return parsed
    return default


def is_auto_language(value: object) -> bool:
    return normalize_language(value) == AUTO_LANGUAGE


def language_label(language: str) -> str:
    normalized = normalize_language(language)
    if normalized == AUTO_LANGUAGE:
        return "Detect automatically"
    return _COMMON_LANGUAGE_LABELS.get(normalized, normalized.upper())


def build_language_options(
    selected_language: str | None = None,
) -> list[dict[str, str]]:
    normalized_selected = normalize_language(selected_language)
    options = [
        {"id": option.id, "label": option.label} for option in _COMMON_LANGUAGE_OPTIONS
    ]
    option_ids = {option["id"] for option in options}
    if normalized_selected not in option_ids:
        options.append(
            {
                "id": normalized_selected,
                "label": language_label(normalized_selected),
            }
        )
    return options
