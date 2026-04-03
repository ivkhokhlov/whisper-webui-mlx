from __future__ import annotations

from mlx_ui.engine_registry import list_engine_providers


def build_registry_engine_options(
    *,
    configured_engine_id: str | None = None,
    active_engine_id: str | None = None,
) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for provider in list_engine_providers(visible_only=True):
        instantiable = provider.is_implemented()
        runtime_present = provider.is_available()
        available = instantiable and runtime_present
        reason = engine_unavailable_reason(provider, available=available)
        implementation_snapshot = _implementation_snapshot(provider)
        options.append(
            {
                "id": provider.id,
                "label": provider.label,
                "mode": provider.mode,
                "local": provider.mode == "local",
                "cloud": provider.mode == "cloud",
                "available": available,
                "runtime_present": runtime_present,
                "instantiable": instantiable,
                "configured": provider.id == configured_engine_id,
                "active": provider.id == active_engine_id and available,
                "selectable": provider.selectable and available,
                "selectable_flag": provider.selectable,
                "implemented": instantiable,
                "reason": reason,
                "note": reason,
                "disabled": (not provider.selectable) or not available,
                "disabled_label": engine_disabled_label(provider, available=available),
                # Implementation-aware truth: the concrete backend currently presented
                # for this engine family on this machine.
                "implementation_id": implementation_snapshot.get("id"),
                "implementation": implementation_snapshot,
            }
        )
    return options


def find_engine_option(
    options: list[dict[str, object]],
    engine_id: str,
) -> dict[str, object] | None:
    for option in options:
        if option.get("id") == engine_id:
            return option
    return None


def engine_unavailable_reason(provider, *, available: bool) -> str | None:
    if available:
        return None
    detail = provider.unavailable_reason()
    if not provider.is_available() and detail:
        return normalize_unavailable_reason(detail)
    if not provider.is_implemented():
        return "Not implemented yet."
    if detail:
        return normalize_unavailable_reason(detail)
    return "Not available."


def engine_disabled_label(provider, *, available: bool) -> str | None:
    if available and provider.selectable:
        return None
    if not provider.is_implemented():
        return provider.disabled_label or "Unavailable"
    if not provider.selectable:
        return provider.disabled_label or "Unavailable"
    return provider.disabled_label


def provider_unavailable_detail(provider) -> str:
    detail = (provider.unavailable_reason() or "not available.").strip()
    if detail.endswith("."):
        return detail[:-1]
    return detail


def normalize_unavailable_reason(detail: str) -> str:
    normalized = detail.strip()
    if not normalized:
        return "Not available."
    return normalized[0].upper() + normalized[1:]


def _implementation_snapshot(provider) -> dict[str, object]:
    implementation = provider.display_implementation()
    if implementation is None:
        return {
            "id": None,
            "available": False,
            "implemented": False,
            "reason": None,
            "disabled_label": None,
        }
    implementation_implemented = implementation.is_implemented()
    implementation_available = (
        implementation_implemented and implementation.is_available()
    )
    implementation_reason = None
    if not implementation_available:
        detail = implementation.unavailable_reason()
        if detail:
            implementation_reason = normalize_unavailable_reason(detail)
    return {
        "id": implementation.id,
        "available": implementation_available,
        "implemented": implementation_implemented,
        "reason": implementation_reason,
        "disabled_label": implementation.disabled_label,
    }
