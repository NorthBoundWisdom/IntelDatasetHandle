from __future__ import annotations

import re

CANONICAL_CATEGORIES: tuple[str, ...] = (
    "Good",
    "Excessive_Convexity",
    "Undercut",
    "Lack_of_Fusion",
    "Porosity",
    "Spatter",
    "Burnthrough",
    "Porosity_w_Excessive_Penetration",
    "Excessive_Penetration",
    "Crater_Cracks",
    "Warping",
    "Overlap",
)


def _key(value: str) -> str:
    value = value.strip().casefold()
    value = value.replace("w/", " with ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


_ALIASES = {
    _key("Good"): "Good",
    _key("Normal"): "Good",
    _key("OK"): "Good",
    _key("Excessive Convexity"): "Excessive_Convexity",
    _key("Undercut"): "Undercut",
    _key("Lack of Fusion"): "Lack_of_Fusion",
    _key("Porosity"): "Porosity",
    _key("Spatter"): "Spatter",
    _key("Burnthrough"): "Burnthrough",
    _key("Burn through"): "Burnthrough",
    _key("Porosity with Excessive Penetration"): "Porosity_w_Excessive_Penetration",
    _key("Porosity w Excessive Penetration"): "Porosity_w_Excessive_Penetration",
    _key("Porosity w EP"): "Porosity_w_Excessive_Penetration",
    _key("Porosity_w_Excessive_Penetration"): "Porosity_w_Excessive_Penetration",
    _key("Excessive Penetration"): "Excessive_Penetration",
    _key("Crater Cracks"): "Crater_Cracks",
    _key("Warping"): "Warping",
    _key("Overlap"): "Overlap",
}


def normalize_category(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "null", "na", "n/a"}:
        return None
    return _ALIASES.get(_key(text), text)


def category_display_name(value: object | None) -> str:
    normalized = normalize_category(value)
    return normalized.replace("_", " ") if normalized else "Unknown"


def is_good_category(value: object | None) -> bool:
    return normalize_category(value) == "Good"
