from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


US_STATES: tuple[str, ...] = (
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "District of Columbia",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
)

STATE_ABBREVIATIONS: dict[str, str] = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


LEGACY_MICHIGAN_CITIES: list[str] = [
    "Northville",
    "Novi",
    "Berkley",
    "West Bloomfield",
    "Livonia",
    "Ypsilanti",
]

DEFAULT_CITIES: list[str] = []

DEFAULT_SEARCH_KEYWORDS: list[str] = [
    "strip mall",
    "shopping plaza",
    "retail center",
    "storefront",
    "restaurant",
    "gas station",
    "property manager",
    "property management",
    "leasing office",
    "fast food",
    "cafe",
    "bakery",
    "beauty",
    "hair",
    "clothes",
    "retail",
    "pharmacy",
    "phone",
    "jewelry",
    "shoes",
    "gym",
    "fitness",
    "opening soon",
    "coming soon",
    "grand opening",
    "new location",
    "construction",
    "under construction",
    "development",
    "buildout",
]


@dataclass(frozen=True)
class AppConfig:
    state: str
    cities: list[str]
    search_keywords: list[str]
    exclude_incomplete_addresses: bool
    strict_state_matching: bool
    strict_city_matching: bool
    include_nearby_cities: bool
    exclude_low_value_categories: bool
    exclude_low_intent_keywords: bool
    enable_proximity_cluster_detection: bool
    category_weights: dict[str, int]
    high_intent_keywords: list[str]
    medium_intent_keywords: list[str]
    low_intent_keywords: list[str]
    high_value_category_keywords: list[str]
    medium_value_category_keywords: list[str]
    low_value_category_keywords: list[str]
    target_shop_values: list[str]
    target_amenity_values: list[str]
    target_leisure_values: list[str]
    target_office_values: list[str]
    gas_station_brands: list[str]
    property_manager_keywords: list[str]
    pre_opening_keywords: list[str]
    construction_keywords: list[str]
    franchise_name_patterns: list[str]
    tier1_category_keywords: list[str]
    tier2_category_keywords: list[str]
    excluded_category_keywords: list[str]
    overpass_urls: list[str]
    overpass_timeout_seconds: int
    output_directory: str


def default_config_path() -> Path:
    project_config = Path(__file__).resolve().parents[2] / "config" / "targets.json"
    if not getattr(sys, "frozen", False):
        return project_config

    user_config = app_data_dir() / "config" / "targets.json"
    if not user_config.exists():
        bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        bundled_config = bundled_root / "config" / "targets.json"
        user_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundled_config, user_config)
    return user_config


def app_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    app_folder = "RouteForge"
    old_app_folders = (
        "Route2Revenue",
        "Commercial Window Cleaning Client Lead Generator",
    )
    if root:
        new_path = Path(root) / app_folder
        old_paths = [Path(root) / old_app_folder for old_app_folder in old_app_folders]
    else:
        new_path = Path.home() / app_folder
        old_paths = [Path.home() / old_app_folder for old_app_folder in old_app_folders]
    for old_path in old_paths:
        _migrate_old_app_data(old_path, new_path)
    return new_path


def _migrate_old_app_data(old_path: Path, new_path: Path) -> None:
    if not old_path.exists() or new_path.exists():
        return
    try:
        new_path.mkdir(parents=True, exist_ok=True)
        for name in (
            "saved_leads.json",
            "saved_presets.json",
            "saved_routes.json",
            "config",
        ):
            source = old_path / name
            destination = new_path / name
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            elif source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    except OSError:
        return


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else default_config_path()
    with config_path.open("r", encoding="utf-8-sig") as handle:
        payload: dict[str, Any] = json.load(handle)

    return AppConfig(
        state=payload.get("state", "Michigan"),
        cities=_load_cities(payload),
        search_keywords=_load_search_keywords(payload),
        exclude_incomplete_addresses=payload.get("exclude_incomplete_addresses", True),
        strict_state_matching=payload.get("strict_state_matching", True),
        strict_city_matching=payload.get("strict_city_matching", True),
        include_nearby_cities=payload.get("include_nearby_cities", False),
        exclude_low_value_categories=payload.get("exclude_low_value_categories", True),
        exclude_low_intent_keywords=payload.get("exclude_low_intent_keywords", True),
        enable_proximity_cluster_detection=payload.get(
            "enable_proximity_cluster_detection", True
        ),
        category_weights=payload.get("category_weights", {}),
        high_intent_keywords=payload.get(
            "high_intent_keywords",
            ["strip mall", "shopping plaza", "retail center", "storefront"],
        ),
        medium_intent_keywords=payload.get(
            "medium_intent_keywords",
            [
                "restaurant",
                "gas station",
                "property manager",
                "property management",
                "fast food",
                "cafe",
                "bakery",
                "salon",
                "hair",
                "beauty",
                "gym",
                "fitness",
                "retail",
                "retail store",
                "clothes",
                "pharmacy",
                "phone",
                "jewelry",
                "shoes",
            ],
        ),
        low_intent_keywords=payload.get(
            "low_intent_keywords",
            ["business", "office", "company", "service", "commercial"],
        ),
        high_value_category_keywords=payload.get(
            "high_value_category_keywords",
            [
                "restaurant",
                "fast food",
                "cafe",
                "bakery",
                "fuel",
                "gas station",
                "retail",
                "clothes",
                "boutique",
                "salon",
                "hairdresser",
                "beauty",
                "gym",
                "fitness",
                "dry cleaning",
                "laundry",
                "property management",
                "leasing office",
                "commercial real estate",
                "mobile phone",
                "jewelry",
                "shoes",
                "pharmacy",
                "florist",
                "pet",
            ],
        ),
        medium_value_category_keywords=payload.get(
            "medium_value_category_keywords",
            ["clinic", "doctors", "doctor", "dentist", "medical", "optician"],
        ),
        low_value_category_keywords=payload.get(
            "low_value_category_keywords",
            [
                "bank",
                "atm",
                "office",
                "corporate",
                "warehouse",
                "industrial",
                "storage",
                "insurance",
                "real estate",
            ],
        ),
        target_shop_values=payload["target_shop_values"],
        target_amenity_values=payload["target_amenity_values"],
        target_leisure_values=payload.get("target_leisure_values", ["fitness_centre"]),
        target_office_values=payload.get("target_office_values", ["estate_agent", "company"]),
        gas_station_brands=payload.get(
            "gas_station_brands",
            [
                "Shell",
                "Exxon",
                "Mobil",
                "Chevron",
                "BP",
                "Sunoco",
                "Marathon",
                "Circle K",
                "Speedway",
                "7-Eleven",
                "Wawa",
                "RaceTrac",
                "Murphy",
                "Valero",
                "Phillips 66",
            ],
        ),
        property_manager_keywords=payload.get(
            "property_manager_keywords",
            [
                "property management",
                "property manager",
                "leasing office",
                "commercial real estate",
                "realty services",
                "asset management",
                "apartment management",
                "tenant services",
            ],
        ),
        pre_opening_keywords=payload.get(
            "pre_opening_keywords",
            ["opening soon", "coming soon", "grand opening", "now open", "new location"],
        ),
        construction_keywords=payload.get(
            "construction_keywords",
            ["construction", "under construction", "development", "buildout", "coming soon"],
        ),
        franchise_name_patterns=payload["franchise_name_patterns"],
        tier1_category_keywords=payload["tier1_category_keywords"],
        tier2_category_keywords=payload["tier2_category_keywords"],
        excluded_category_keywords=payload["excluded_category_keywords"],
        overpass_urls=payload.get("overpass_urls") or [payload["overpass_url"]],
        overpass_timeout_seconds=payload["overpass_timeout_seconds"],
        output_directory=payload["output_directory"],
    )


def save_config(config: AppConfig, path: str | Path | None = None) -> Path:
    config_path = Path(path) if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": config.state,
        "cities": config.cities,
        "search_keywords": config.search_keywords,
        "exclude_incomplete_addresses": config.exclude_incomplete_addresses,
        "strict_state_matching": config.strict_state_matching,
        "strict_city_matching": config.strict_city_matching,
        "include_nearby_cities": config.include_nearby_cities,
        "exclude_low_value_categories": config.exclude_low_value_categories,
        "exclude_low_intent_keywords": config.exclude_low_intent_keywords,
        "enable_proximity_cluster_detection": config.enable_proximity_cluster_detection,
        "category_weights": config.category_weights,
        "high_intent_keywords": config.high_intent_keywords,
        "medium_intent_keywords": config.medium_intent_keywords,
        "low_intent_keywords": config.low_intent_keywords,
        "high_value_category_keywords": config.high_value_category_keywords,
        "medium_value_category_keywords": config.medium_value_category_keywords,
        "low_value_category_keywords": config.low_value_category_keywords,
        "target_shop_values": config.target_shop_values,
        "target_amenity_values": config.target_amenity_values,
        "target_leisure_values": config.target_leisure_values,
        "target_office_values": config.target_office_values,
        "gas_station_brands": config.gas_station_brands,
        "property_manager_keywords": config.property_manager_keywords,
        "pre_opening_keywords": config.pre_opening_keywords,
        "construction_keywords": config.construction_keywords,
        "franchise_name_patterns": config.franchise_name_patterns,
        "tier1_category_keywords": config.tier1_category_keywords,
        "tier2_category_keywords": config.tier2_category_keywords,
        "excluded_category_keywords": config.excluded_category_keywords,
        "overpass_urls": config.overpass_urls,
        "overpass_timeout_seconds": config.overpass_timeout_seconds,
        "output_directory": config.output_directory,
    }
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return config_path


def state_abbreviation(state: str) -> str:
    return STATE_ABBREVIATIONS.get(state, state)


def state_query_name(state: str) -> str:
    if state == "District of Columbia":
        return "District of Columbia"
    return state


def default_output_directory() -> str:
    return str(Path.home() / "Documents" / "Storefront Lead Generator" / "Exports")


def _load_cities(payload: dict[str, Any]) -> list[str]:
    cities = payload.get("cities") or DEFAULT_CITIES
    normalized = {city.lower().strip() for city in cities}
    legacy_normalized = {city.lower().strip() for city in LEGACY_MICHIGAN_CITIES}
    if normalized == legacy_normalized and "strict_state_matching" not in payload:
        return []
    return cities


def _load_search_keywords(payload: dict[str, Any]) -> list[str]:
    keywords = payload.get("search_keywords") or DEFAULT_SEARCH_KEYWORDS
    merged = _dedupe_text([*DEFAULT_SEARCH_KEYWORDS, *keywords])
    if "exclude_low_intent_keywords" in payload:
        return merged

    migrated = [
        keyword for keyword in merged if keyword.lower().strip() not in {"bank", "atm"}
    ]
    migrated = [*DEFAULT_SEARCH_KEYWORDS[:4], *migrated, "gym", "fitness"]
    return _dedupe_text(migrated)


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped
