from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests

from leadgen_tool.classifier import (
    effective_search_keywords,
    is_gas_station_lead,
    is_low_value_category,
    is_property_manager_lead,
    keyword_intent,
    matched_keywords_for_lead,
)
from leadgen_tool.config import AppConfig, state_abbreviation, state_query_name
from leadgen_tool.models import Lead


EMAIL_PATTERN = re.compile(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", re.IGNORECASE)
MAX_WEBSITE_EMAIL_LOOKUPS_PER_CITY = 20
GENERIC_PROPERTY_MANAGER_EMAILS = (
    "leasing",
    "info",
    "contact",
    "office",
    "manager",
    "hello",
)


@dataclass(frozen=True)
class CityCollectionResult:
    leads: list[Lead]
    excluded_incomplete_address: int = 0
    excluded_city_mismatch: int = 0
    excluded_state_mismatch: int = 0
    excluded_low_value_category: int = 0
    excluded_low_intent_keyword: int = 0


@dataclass(frozen=True)
class OverpassCollector:
    config: AppConfig

    def collect_city(self, city: str, state: str | None = None) -> list[Lead]:
        return self.collect_city_result(city, state).leads

    def collect_city_result(self, city: str, state: str | None = None) -> CityCollectionResult:
        selected_state = state or self.config.state
        area_id, bounds = self._geocode_city(city, selected_state)
        query = self._build_query(area_id, bounds)
        last_error: Exception | None = None
        for overpass_url in self.config.overpass_urls:
            try:
                response = requests.post(
                    overpass_url,
                    data={"data": query},
                    timeout=self.config.overpass_timeout_seconds,
                    headers={"User-Agent": "local-leadgen-tool/1.0"},
                )
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
                return self._parse_elements(city, selected_state, payload.get("elements", []))
            except requests.RequestException as exc:
                last_error = exc

        raise RuntimeError(
            f"Could not collect leads for {city}, {selected_state}. "
            "Please check your internet connection and try again."
        ) from last_error

    def _geocode_city(
        self, city: str, state: str
    ) -> tuple[int | None, tuple[float, float, float, float]]:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "city": city,
                "state": state_query_name(state),
                "country": "United States",
                "format": "json",
                "limit": 1,
            },
            timeout=30,
            headers={"User-Agent": "storefront-lead-generator/1.0"},
        )
        response.raise_for_status()
        matches: list[dict[str, Any]] = response.json()
        if not matches:
            raise RuntimeError(
                f"We could not find {city}, {state}. Check the spelling or try a nearby city."
            )

        match = matches[0]
        south, north, west, east = [float(value) for value in match["boundingbox"]]
        return self._overpass_area_id(match), (south, west, north, east)

    def _overpass_area_id(self, match: dict[str, Any]) -> int | None:
        osm_type = match.get("osm_type")
        osm_id = match.get("osm_id")
        if not osm_id:
            return None
        if osm_type == "relation":
            return 3_600_000_000 + int(osm_id)
        if osm_type == "way":
            return 2_400_000_000 + int(osm_id)
        return None

    def _build_query(
        self,
        area_id: int | None,
        bounds: tuple[float, float, float, float],
    ) -> str:
        south, west, north, east = bounds
        shop_pattern = "|".join(self.config.target_shop_values)
        amenity_pattern = "|".join(self.config.target_amenity_values)
        leisure_pattern = "|".join(self.config.target_leisure_values)
        office_pattern = "|".join(self.config.target_office_values)
        if area_id and not self.config.include_nearby_cities:
            return f"""
[out:json][timeout:{self.config.overpass_timeout_seconds}];
area({area_id})->.searchArea;
(
  nwr(area.searchArea)["shop"~"^({shop_pattern})$"];
  nwr(area.searchArea)["amenity"~"^({amenity_pattern})$"];
  nwr(area.searchArea)["leisure"~"^({leisure_pattern})$"];
  nwr(area.searchArea)["office"~"^({office_pattern})$"];
);
out center tags;
""".strip()

        return f"""
[out:json][timeout:{self.config.overpass_timeout_seconds}];
(
  nwr({south},{west},{north},{east})["shop"~"^({shop_pattern})$"];
  nwr({south},{west},{north},{east})["amenity"~"^({amenity_pattern})$"];
  nwr({south},{west},{north},{east})["leisure"~"^({leisure_pattern})$"];
  nwr({south},{west},{north},{east})["office"~"^({office_pattern})$"];
);
out center tags;
""".strip()

    def _parse_elements(
        self,
        city: str,
        state: str,
        elements: list[dict[str, Any]],
    ) -> CityCollectionResult:
        leads: list[Lead] = []
        excluded_incomplete_address = 0
        excluded_city_mismatch = 0
        excluded_state_mismatch = 0
        excluded_low_value_category = 0
        excluded_low_intent_keyword = 0
        website_email_lookups = 0
        for element in elements:
            tags = element.get("tags", {})
            name = (tags.get("name") or "").strip()
            if not name:
                continue

            category = self._derive_category(tags)
            if not category or (
                self._is_excluded(category)
                and not is_property_manager_lead(name, category, self.config)
            ):
                continue
            if (
                self.config.exclude_low_value_categories
                and is_low_value_category(name, category, self.config)
            ):
                excluded_low_value_category += 1
                continue
            full_address, address_quality = self._build_full_address(tags, city, state)
            matched_keywords = matched_keywords_for_lead(
                name, category, full_address, self.config
            )
            if not self._matches_search_keywords(name, category, full_address):
                continue
            if self.config.strict_state_matching and self._has_state_mismatch(tags, state):
                excluded_state_mismatch += 1
                continue
            if (
                self.config.strict_city_matching
                and not self.config.include_nearby_cities
                and self._has_city_mismatch(tags, city)
            ):
                excluded_city_mismatch += 1
                continue
            if (
                self.config.exclude_incomplete_addresses
                and address_quality == "city_state_only"
            ):
                excluded_incomplete_address += 1
                continue

            lat = element.get("lat") or element.get("center", {}).get("lat")
            lon = element.get("lon") or element.get("center", {}).get("lon")
            website = self._clean_website(
                self._pick_first(
                    tags,
                    "website",
                    "contact:website",
                    "url",
                    "brand:website",
                    "operator:website",
                )
            )
            email = self._extract_email(tags, name, category)
            if not email and website and website_email_lookups < MAX_WEBSITE_EMAIL_LOOKUPS_PER_CITY:
                email = self._extract_email_from_website(website)
                website_email_lookups += 1
            lead = Lead(
                business_name=name,
                category=category,
                city=city,
                full_address=full_address,
                website=website,
                phone=self._pick_first(
                    tags,
                    "phone",
                    "contact:phone",
                    "contact:mobile",
                    "mobile",
                    "telephone",
                ),
                email=email,
                google_maps_url=self._build_google_maps_url(name, tags, element, city, state),
                is_chain=self._has_brand_signal(tags),
                hours_of_operation=self._pick_first(
                    tags,
                    "opening_hours",
                    "contact:opening_hours",
                ),
                date_added="",
                address_quality=address_quality,
                latitude=float(lat) if lat is not None else None,
                longitude=float(lon) if lon is not None else None,
                source_keywords=matched_keywords,
                keyword_match_count=len(matched_keywords),
                city_match_confidence=100
                if not self._has_city_mismatch(tags, city)
                else 35,
                state_match_confidence=100
                if not self._has_state_mismatch(tags, state)
                else 20,
            )
            leads.append(lead)

        return CityCollectionResult(
            leads=leads,
            excluded_incomplete_address=excluded_incomplete_address,
            excluded_city_mismatch=excluded_city_mismatch,
            excluded_state_mismatch=excluded_state_mismatch,
            excluded_low_value_category=excluded_low_value_category,
            excluded_low_intent_keyword=excluded_low_intent_keyword,
        )

    def _derive_category(self, tags: dict[str, str]) -> str:
        if tags.get("shop"):
            return tags["shop"].replace("_", " ").title()
        if tags.get("amenity"):
            return tags["amenity"].replace("_", " ").title()
        if tags.get("leisure"):
            return tags["leisure"].replace("_", " ").title()
        if tags.get("office"):
            return tags["office"].replace("_", " ").title()
        if tags.get("brand"):
            return "Retail"
        return ""

    def _is_excluded(self, category: str) -> bool:
        lowered = category.lower()
        return any(keyword in lowered for keyword in self.config.excluded_category_keywords)

    def _matches_search_keywords(self, name: str, category: str, address: str) -> bool:
        hard_filter_keywords = [
            keyword
            for keyword in effective_search_keywords(self.config)
            if keyword_intent(keyword, self.config) != "high"
        ]
        if not hard_filter_keywords:
            return True

        return any(
            self._keyword_matches_lead(keyword, name, category, address)
            for keyword in hard_filter_keywords
        )

    def _build_full_address(
        self, tags: dict[str, str], city: str, state: str
    ) -> tuple[str, str]:
        state_code = state_abbreviation(state)
        full_address = (
            tags.get("addr:full")
            or tags.get("addr:full:en")
            or tags.get("address")
            or ""
        ).strip()
        if full_address:
            return full_address, "full_street_address"

        street_parts = [
            tags.get("addr:housenumber", "").strip(),
            tags.get("addr:street", "").strip(),
        ]
        line_one = " ".join(part for part in street_parts if part).strip()
        locality_parts = [
            tags.get("addr:city", "").strip() or city,
            tags.get("addr:state", "").strip() or state_code,
            tags.get("addr:postcode", "").strip(),
        ]
        line_two = ", ".join(part for part in locality_parts if part)
        address = ", ".join(part for part in [line_one, line_two] if part)
        if tags.get("addr:housenumber") and tags.get("addr:street"):
            return address, "full_street_address"
        if tags.get("addr:street") or tags.get("addr:place"):
            return address or f"{tags.get('addr:place')}, {line_two}", "partial_address"
        return address or f"{city}, {state_code}", "city_state_only"

    def _build_google_maps_url(
        self,
        name: str,
        tags: dict[str, str],
        element: dict[str, Any],
        city: str,
        state: str,
    ) -> str:
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        if lat is not None and lon is not None:
            return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

        address, _ = self._build_full_address(tags, city, state)
        return (
            "https://www.google.com/maps/search/?api=1&query="
            f"{quote_plus(f'{name} {address}')}"
        )

    def _pick_first(self, tags: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = (tags.get(key) or "").strip()
            if value:
                return value
        return ""

    def _has_brand_signal(self, tags: dict[str, str]) -> bool:
        return any(
            (tags.get(key) or "").strip()
            for key in ("brand", "brand:wikidata", "operator", "operator:wikidata")
        )

    def _has_city_mismatch(self, tags: dict[str, str], city: str) -> bool:
        tagged_city = (tags.get("addr:city") or "").strip()
        if not tagged_city:
            return False
        return self._normalize_city(tagged_city) != self._normalize_city(city)

    def _has_state_mismatch(self, tags: dict[str, str], state: str) -> bool:
        tagged_state = (tags.get("addr:state") or "").strip()
        if not tagged_state:
            return False
        return self._normalize_state(tagged_state) != self._normalize_state(state)

    def _normalize_city(self, value: str) -> str:
        return "".join(character.lower() for character in value if character.isalnum())

    def _normalize_state(self, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) == 2:
            return cleaned.upper()
        return state_abbreviation(cleaned).upper()

    def _keyword_matches_lead(
        self,
        keyword: str,
        name: str,
        category: str,
        address: str,
    ) -> bool:
        lowered_keyword = keyword.lower().strip()
        haystack = f"{name} {category} {address}".lower()
        if lowered_keyword in haystack:
            return True
        if lowered_keyword == "gas station":
            return is_gas_station_lead(name, category, self.config)
        if lowered_keyword in {"property manager", "property management"}:
            return is_property_manager_lead(name, category, self.config)
        return False

    def _clean_website(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        return f"https://{value}"

    def _extract_email(self, tags: dict[str, str], name: str, category: str) -> str:
        exact_match = self._pick_first(
            tags,
            "email",
            "contact:email",
            "contact:e-mail",
            "operator:email",
            "office:email",
            "manager:email",
            "leasing:email",
        )
        cleaned_exact = self._clean_email(exact_match)
        if cleaned_exact:
            return cleaned_exact

        for key, value in tags.items():
            if "email" in key.lower():
                cleaned = self._clean_email(value)
                if cleaned:
                    return cleaned

        for value in tags.values():
            cleaned = self._clean_email(value)
            if cleaned:
                return cleaned

        if is_property_manager_lead(name, category, self.config):
            website = self._clean_website(
                self._pick_first(
                    tags,
                    "website",
                    "contact:website",
                    "url",
                    "brand:website",
                    "operator:website",
                )
            )
            inferred = self._infer_property_manager_email(website, name)
            if inferred:
                return inferred
        return ""

    def _clean_email(self, value: str) -> str:
        raw_value = (value or "").strip()
        if not raw_value:
            return ""
        raw_value = raw_value.replace("mailto:", "").strip()
        match = EMAIL_PATTERN.search(raw_value)
        return match.group(1).lower() if match else ""

    def _extract_email_from_website(self, website: str) -> str:
        if not website:
            return ""
        parsed = urlparse(website)
        host = (parsed.netloc or parsed.path).lower()
        if any(
            blocked in host
            for blocked in ("facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com")
        ):
            return ""
        for url in (website, urljoin(website.rstrip("/") + "/", "contact")):
            try:
                response = requests.get(
                    url,
                    timeout=4,
                    headers={"User-Agent": "WashAway Lead Dispatch email lookup"},
                )
                response.raise_for_status()
            except requests.RequestException:
                continue
            cleaned = self._clean_email(response.text[:180_000])
            if cleaned and not cleaned.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                return cleaned
        return ""

    def _infer_property_manager_email(self, website: str, name: str) -> str:
        if not website:
            return ""
        parsed = urlparse(website)
        host = (parsed.netloc or parsed.path).lower().strip()
        if not host:
            return ""
        host = host.removeprefix("www.")
        if any(
            blocked in host
            for blocked in ("facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com")
        ):
            return ""
        if host.count(".") < 1:
            return ""
        if not any(
            signal in f"{host} {name.lower()}"
            for signal in ("property", "realty", "leasing", "management", "commercial")
        ):
            return ""
        domain_parts = host.split(".")
        if len(domain_parts) >= 2:
            host = ".".join(domain_parts[-2:])
        return f"{GENERIC_PROPERTY_MANAGER_EMAILS[0]}@{host}"
