from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from leadgen_tool.config import AppConfig
from leadgen_tool.models import Lead


ROAD_REPLACEMENTS = {
    "road": "rd",
    "rd": "rd",
    "street": "st",
    "st": "st",
    "avenue": "ave",
    "ave": "ave",
    "boulevard": "blvd",
    "blvd": "blvd",
    "drive": "dr",
    "dr": "dr",
    "lane": "ln",
    "ln": "ln",
    "court": "ct",
    "ct": "ct",
    "highway": "hwy",
    "hwy": "hwy",
    "parkway": "pkwy",
    "pkwy": "pkwy",
    "circle": "cir",
    "cir": "cir",
    "terrace": "ter",
    "ter": "ter",
}

DIRECTION_REPLACEMENTS = {
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
}

UNIT_PATTERN = re.compile(
    r"\b(?:suite|ste|unit|apt|apartment|bldg|building|room|rm|space|store|#)\s*[a-z0-9\-]+\b",
    re.IGNORECASE,
)

STREET_WORDS = {"rd", "st", "ave", "blvd", "dr", "ln", "ct", "hwy", "pkwy", "cir", "ter"}
DENSITY_RADIUS_METERS = 85


def classify_leads(leads: list[Lead], config: AppConfig) -> list[Lead]:
    _apply_strip_mall_detection(leads, config)
    _apply_chain_detection(leads, config)
    _apply_field_sales_flags(leads, config)
    _apply_quality_scores(leads, config)
    _apply_priority_tiers(leads)
    _apply_lead_reasons(leads)
    _apply_action_plan_fields(leads)
    return sorted(leads, key=_output_sort_key)


def is_low_value_category(name: str, category: str, config: AppConfig) -> bool:
    haystack = f"{name} {category}".lower()
    if is_property_manager_lead(name, category, config):
        return False
    if is_gas_station_lead(name, category, config):
        return False
    return any(keyword.lower() in haystack for keyword in config.low_value_category_keywords)


def is_property_manager_lead(name: str, category: str, config: AppConfig) -> bool:
    haystack = f"{name} {category}".lower()
    return any(keyword.lower() in haystack for keyword in config.property_manager_keywords)


def is_gas_station_lead(name: str, category: str, config: AppConfig) -> bool:
    haystack = f"{name} {category}".lower()
    if "fuel" in haystack or "gas station" in haystack:
        return True
    return any(brand.lower() in haystack for brand in config.gas_station_brands)


def keyword_intent(keyword: str, config: AppConfig) -> str:
    lowered = keyword.lower().strip()
    if not lowered:
        return "unknown"
    if any(_keyword_matches(lowered, value) for value in config.high_intent_keywords):
        return "high"
    if any(_keyword_matches(lowered, value) for value in config.medium_intent_keywords):
        return "medium"
    if any(_keyword_matches(lowered, value) for value in config.low_intent_keywords):
        return "low"
    return "unknown"


def effective_search_keywords(config: AppConfig) -> list[str]:
    keywords = []
    for keyword in config.search_keywords:
        if config.exclude_low_intent_keywords and keyword_intent(keyword, config) == "low":
            continue
        keywords.append(keyword)
    return _dedupe_text(keywords)


def matched_keywords_for_lead(
    name: str, category: str, address: str, config: AppConfig
) -> list[str]:
    haystack = f"{name} {category} {address}".lower()
    matched = []
    for keyword in effective_search_keywords(config):
        normalized_keyword = keyword.lower().strip()
        if normalized_keyword and (
            normalized_keyword in haystack
            or (normalized_keyword == "gas station" and is_gas_station_lead(name, category, config))
            or (
                normalized_keyword in {"property manager", "property management"}
                and is_property_manager_lead(name, category, config)
            )
        ):
            matched.append(keyword)
    return _dedupe_text(matched)


def _apply_strip_mall_detection(leads: list[Lead], config: AppConfig) -> None:
    address_groups = _group_by_base_address(leads)
    address_group_counts = {
        id(grouped_lead): len(grouped_leads)
        for grouped_leads in address_groups.values()
        for grouped_lead in grouped_leads
    }
    density_counts = (
        _nearby_business_counts(leads)
        if config.enable_proximity_cluster_detection
        else {id(lead): 1 for lead in leads}
    )

    for lead in leads:
        shared_address_count = address_group_counts.get(id(lead), 1)
        nearby_count = density_counts.get(id(lead), 1)
        confidence = _strip_mall_confidence(lead, shared_address_count, nearby_count)

        lead.same_address_count = max(shared_address_count, nearby_count, 1)
        lead.strip_mall_confidence = confidence
        lead.is_strip_mall = confidence >= 60
        if shared_address_count >= 3:
            lead.plaza_cluster_type = "shared_address"
        elif nearby_count >= 3:
            lead.plaza_cluster_type = "proximity"
        elif _has_plaza_signal(lead):
            lead.plaza_cluster_type = "plaza_signal"
        else:
            lead.plaza_cluster_type = ""


def _group_by_base_address(leads: list[Lead]) -> dict[str, list[Lead]]:
    raw_groups: defaultdict[str, list[Lead]] = defaultdict(list)
    for lead in leads:
        if not is_groupable_address(lead.full_address, lead.city):
            lead.same_address_count = 1
            lead.is_strip_mall = False
            continue

        base_key = normalize_base_address(lead.full_address)
        if base_key:
            raw_groups[base_key].append(lead)

    if len(raw_groups) < 2:
        return dict(raw_groups)

    parent = {key: key for key in raw_groups}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    keys = list(raw_groups)
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            if _similar_base_addresses(left, right):
                union(left, right)

    merged: defaultdict[str, list[Lead]] = defaultdict(list)
    for key, grouped_leads in raw_groups.items():
        merged[find(key)].extend(grouped_leads)
    return dict(merged)


def _similar_base_addresses(left: str, right: str) -> bool:
    left_number = _leading_street_number(left)
    right_number = _leading_street_number(right)
    if not left_number or left_number != right_number:
        return False

    left_tokens = set(_street_tokens_without_number(left))
    right_tokens = set(_street_tokens_without_number(right))
    if not left_tokens or not right_tokens:
        return False

    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    if overlap >= 0.72:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.86


def _nearby_business_counts(leads: list[Lead]) -> dict[int, int]:
    counts = {id(lead): 1 for lead in leads}
    located_leads = [
        lead for lead in leads if lead.latitude is not None and lead.longitude is not None
    ]
    for index, lead in enumerate(located_leads):
        for other in located_leads[index + 1 :]:
            if _distance_meters(lead, other) <= DENSITY_RADIUS_METERS:
                counts[id(lead)] += 1
                counts[id(other)] += 1
    return counts


def _strip_mall_confidence(lead: Lead, shared_address_count: int, nearby_count: int) -> int:
    confidence = 0
    if shared_address_count >= 3:
        confidence = 92
    elif shared_address_count == 2:
        confidence = 70 if _has_plaza_signal(lead) else 58

    if nearby_count >= 4:
        confidence = max(confidence, 84)
    elif nearby_count == 3:
        confidence = max(confidence, 68)

    if _has_plaza_signal(lead):
        confidence = max(confidence, 62)
        confidence += 8

    if lead.address_quality == "city_state_only":
        confidence -= 25
    elif lead.address_quality == "partial_address":
        confidence -= 8

    return max(0, min(confidence, 100))


def _apply_chain_detection(leads: list[Lead], config: AppConfig) -> None:
    name_counter = Counter(normalize_business_name(lead.business_name) for lead in leads)

    for lead in leads:
        normalized_name = normalize_business_name(lead.business_name)
        business_name = lead.business_name.lower()
        matches_pattern = any(
            pattern.lower() in business_name for pattern in config.franchise_name_patterns
        )
        lead.is_chain = lead.is_chain or (
            name_counter[normalized_name] >= 2 or matches_pattern
        )


def _apply_field_sales_flags(leads: list[Lead], config: AppConfig) -> None:
    for lead in leads:
        lead.is_property_manager_lead = is_property_manager_lead(
            lead.business_name, lead.category, config
        )
        lead.is_new_pre_opening_lead = _is_new_pre_opening_lead(lead, config)
        lead.is_construction_opportunity = _is_construction_opportunity(lead, config)
        lead.recommended_visit_window = _recommended_visit_window(lead)


def _apply_quality_scores(leads: list[Lead], config: AppConfig) -> None:
    for lead in leads:
        category_value, category_score = _category_value_score(lead, config)
        lead.category_value = category_value
        address_score = _address_quality_score(lead)
        strip_score = round(lead.strip_mall_confidence * 0.36)
        if lead.same_address_count >= 5:
            strip_score += 12
        elif lead.same_address_count >= 3:
            strip_score += 8
        chain_score = 12 if lead.is_chain else 0
        keyword_score = _keyword_quality_score(lead, config)
        location_score = _location_quality_score(lead)
        timing_score = 6 if lead.recommended_visit_window else 0
        field_signal_score = 0
        if lead.is_property_manager_lead:
            field_signal_score += 18
        if lead.is_new_pre_opening_lead:
            field_signal_score += 8
        if lead.is_construction_opportunity:
            field_signal_score += 8

        lead.lead_quality_score = max(
            0,
            min(
                100,
                category_score
                + address_score
                + strip_score
                + chain_score
                + keyword_score
                + location_score
                + timing_score
                + field_signal_score,
            ),
        )


def _apply_priority_tiers(leads: list[Lead]) -> None:
    if not leads:
        return

    max_tier1_count = max(1, round(len(leads) * 0.28))
    tier1_candidates = [
        lead
        for lead in leads
        if lead.category_value in {"high", "very_high"}
        and lead.address_quality == "full_street_address"
        and lead.same_address_count >= 3
        and lead.strip_mall_confidence >= 80
        and (lead.is_chain or lead.category_value in {"high", "very_high"})
        and lead.lead_quality_score >= 80
        and lead.address_quality != "city_state_only"
    ]
    tier1_ids = {
        id(lead)
        for lead in sorted(
            tier1_candidates,
            key=lambda item: (
                item.same_address_count,
                item.lead_quality_score,
                item.strip_mall_confidence,
                1 if item.is_chain else 0,
            ),
            reverse=True,
        )[:max_tier1_count]
    }

    for lead in leads:
        if id(lead) in tier1_ids:
            lead.priority_tier = "Tier 1"
        elif lead.category_value != "low" and lead.lead_quality_score >= 48:
            lead.priority_tier = "Tier 2"
        else:
            lead.priority_tier = "Tier 3"


def _category_value_score(lead: Lead, config: AppConfig) -> tuple[str, int]:
    haystack = f"{lead.business_name} {lead.category}".lower()
    if lead.is_property_manager_lead:
        return "very_high", 40
    if is_gas_station_lead(lead.business_name, lead.category, config):
        return "high", 30
    if any(keyword.lower() in haystack for keyword in config.low_value_category_keywords):
        return "low", 0

    config_bonus = sum(
        int(weight)
        for keyword, weight in config.category_weights.items()
        if keyword.lower() in haystack
    )
    config_bonus = min(config_bonus, 8)

    if any(keyword.lower() in haystack for keyword in config.high_value_category_keywords):
        return "high", 28 + config_bonus
    if any(keyword.lower() in haystack for keyword in config.medium_value_category_keywords):
        return "medium", 18 + min(config_bonus, 5)
    return "unknown", 8 + min(config_bonus, 4)


def _address_quality_score(lead: Lead) -> int:
    if lead.address_quality == "full_street_address":
        return 12
    if lead.address_quality == "partial_address":
        return 4
    return 0


def _location_quality_score(lead: Lead) -> int:
    city_confidence = max(0, min(lead.city_match_confidence, 100))
    state_confidence = max(0, min(lead.state_match_confidence, 100))
    return round(((city_confidence + state_confidence) / 2) * 0.10)


def _keyword_quality_score(lead: Lead, config: AppConfig) -> int:
    keywords = _dedupe_text(lead.source_keywords or [])
    if lead.category_value == "low":
        keywords = [
            keyword
            for keyword in keywords
            if keyword_intent(keyword, config) not in {"high", "low"}
        ]
    elif lead.is_strip_mall:
        keywords.extend(
            keyword
            for keyword in config.search_keywords
            if keyword_intent(keyword, config) == "high"
        )
        keywords = _dedupe_text(keywords)
    lead.source_keywords = keywords
    lead.keyword_match_count = len(keywords)
    if not keywords:
        lead.keyword_quality_score = 0
        return 0

    best_score = -5
    for keyword in keywords:
        intent = keyword_intent(keyword, config)
        if intent == "high":
            best_score = max(best_score, 20)
        elif intent == "medium":
            best_score = max(best_score, 10)
        elif intent == "low":
            best_score = max(best_score, -5)
        else:
            best_score = max(best_score, 3)

    multi_keyword_bonus = min(max(len(keywords) - 1, 0) * 4, 12)
    lead.keyword_quality_score = max(0, min(28, best_score + multi_keyword_bonus))
    return lead.keyword_quality_score


def _apply_lead_reasons(leads: list[Lead]) -> None:
    for lead in leads:
        lead.lead_reason = _lead_reason(lead)


def _lead_reason(lead: Lead) -> str:
    if lead.is_property_manager_lead:
        return "Property manager account - one yes can unlock multiple buildings"
    if lead.is_construction_opportunity:
        return "New development - get in before another cleaner does"
    if lead.is_new_pre_opening_lead:
        return "Opening soon - ideal time to win the first cleaning agreement"
    if lead.category_value == "low":
        return "Lower-fit business - only worth a quick pass"
    if lead.is_strip_mall and lead.plaza_cluster_type == "shared_address":
        return f"Busy strip mall - {lead.same_address_count} storefronts can be pitched in one stop"
    if lead.strip_mall_confidence >= 88:
        return f"Strong plaza cluster - {lead.same_address_count} nearby storefronts create repeat work"
    if lead.is_strip_mall:
        return f"Retail cluster - several storefronts can be knocked in one visit"
    if lead.is_chain and lead.category_value == "high":
        return "Chain storefront - likely already values recurring window cleaning"
    if lead.keyword_match_count >= 2 and lead.keyword_quality_score >= 14:
        return "Matched across strong keywords - solid storefront opportunity"
    if lead.category_value == "high":
        return "Visible storefront - frequent cleaning needs make this worth a visit"
    if lead.category_value == "medium":
        return "Commercial storefront - decent fit for a follow-up pass"
    return "Optional stop - weaker fit than the top targets"


def _apply_action_plan_fields(leads: list[Lead]) -> None:
    for lead in leads:
        lead.action_priority = _action_priority(lead)
        lead.quick_notes = _quick_notes(lead)


def _action_priority(lead: Lead) -> str:
    if (
        lead.priority_tier == "Tier 1"
        and lead.lead_quality_score >= 84
        and lead.strip_mall_confidence >= 82
        and lead.same_address_count >= 3
    ):
        return "Hit First"
    if lead.priority_tier in {"Tier 1", "Tier 2"} and lead.lead_quality_score >= 50:
        return "Hit Soon"
    return "Optional"


def _quick_notes(lead: Lead) -> str:
    if lead.is_strip_mall and lead.same_address_count >= 3:
        return "Multiple storefronts in one stop - knock the whole plaza"
    if lead.is_chain:
        return "Likely already serviced - pitch consistency, speed, or better pricing"
    if lead.is_property_manager_lead:
        return "Ask about all managed storefronts, not just one location"
    if lead.is_new_pre_opening_lead or lead.is_construction_opportunity:
        return "Pitch startup cleaning before the location settles into a vendor"
    if lead.category_value == "high":
        return "Independent storefront - high chance to convert with a simple offer"
    if lead.category_value == "medium":
        return "Worth a quick visit if you are already nearby"
    return "Optional stop - only hit if route time remains"


def _output_sort_key(lead: Lead) -> tuple[object, ...]:
    action_rank = {"Hit First": 0, "Hit Soon": 1, "Optional": 2}.get(
        lead.action_priority, 3
    )
    tier_rank = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2}.get(lead.priority_tier, 3)
    return (
        action_rank,
        tier_rank,
        -lead.same_address_count,
        -lead.strip_mall_confidence,
        -(1 if lead.is_chain else 0),
        -lead.lead_quality_score,
        lead.business_name.lower(),
    )


def _is_new_pre_opening_lead(lead: Lead, config: AppConfig) -> bool:
    haystack = f"{lead.business_name} {lead.category} {lead.full_address}".lower()
    if any(keyword.lower() in haystack for keyword in config.pre_opening_keywords):
        return True
    sparse_profile = not lead.website and not lead.phone and not lead.hours_of_operation
    return sparse_profile and lead.same_address_count >= 3 and lead.address_quality != "city_state_only"


def _is_construction_opportunity(lead: Lead, config: AppConfig) -> bool:
    haystack = f"{lead.business_name} {lead.category} {lead.full_address}".lower()
    if any(keyword.lower() in haystack for keyword in config.construction_keywords):
        return True
    return lead.is_new_pre_opening_lead and lead.same_address_count >= 4 and lead.is_strip_mall


def _recommended_visit_window(lead: Lead) -> str:
    category = f"{lead.business_name} {lead.category}".lower()
    hours = lead.hours_of_operation.lower()
    if lead.is_property_manager_lead:
        return "Best between 9 AM and 11 AM"
    if "24/7" in hours or "24 hours" in hours:
        return "Best between 1 PM and 4 PM"
    if any(keyword in category for keyword in ("restaurant", "fast food", "cafe", "bakery")):
        return "Best before 11 AM or after 2 PM"
    if any(keyword in category for keyword in ("fuel", "gas station")):
        return "Best between 1 PM and 4 PM"
    if any(keyword in category for keyword in ("beauty", "hairdresser", "salon")):
        return "Best after 2 PM"
    if any(keyword in category for keyword in ("gym", "fitness")):
        return "Best between 11 AM and 3 PM"
    if any(keyword in category for keyword in ("clinic", "doctor", "dentist", "medical")):
        return "Best between 1 PM and 3 PM"
    return "Best between 1 PM and 4 PM"


def normalize_address(value: str) -> str:
    lowered = value.lower()
    lowered = UNIT_PATTERN.sub("", lowered)
    for original, replacement in DIRECTION_REPLACEMENTS.items():
        lowered = re.sub(rf"\b{re.escape(original)}\b", replacement, lowered)
    for original, replacement in ROAD_REPLACEMENTS.items():
        lowered = re.sub(rf"\b{re.escape(original)}\b", replacement, lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_street_address(value: str) -> str:
    street_line = value.split(",", 1)[0]
    return normalize_address(street_line)


def normalize_base_address(value: str) -> str:
    street_line = value.split(",", 1)[0]
    normalized = normalize_address(street_line)
    tokens = normalized.split()
    if len(tokens) > 2 and tokens[-1].isalnum() and tokens[-1] not in STREET_WORDS:
        if any(token in STREET_WORDS for token in tokens[:-1]):
            tokens = tokens[:-1]
    return " ".join(tokens)


def is_groupable_address(value: str, city: str) -> bool:
    normalized = normalize_base_address(value)
    has_street_number = bool(re.search(r"\b\d{2,}\b", normalized))
    has_street_word = any(road_word in normalized.split() for road_word in STREET_WORDS)
    city_only = normalize_address(value) == normalize_address(city)
    return has_street_number and has_street_word and not city_only


def normalize_business_name(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(
        r"\b(inc|llc|ltd|co|company|restaurant|grill|store|shop|salon)\b",
        "",
        lowered,
    )
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def count_strip_mall_clusters(leads: list[Lead]) -> int:
    return len(
        {
            _cluster_key(lead)
            for lead in leads
            if lead.is_strip_mall and lead.strip_mall_confidence >= 60
        }
    )


def count_high_confidence_plazas(leads: list[Lead]) -> int:
    return len(
        {_cluster_key(lead) for lead in leads if lead.strip_mall_confidence >= 80}
    )


def _has_plaza_signal(lead: Lead) -> bool:
    haystack = f"{lead.business_name} {lead.category} {lead.full_address}".lower()
    signals = (
        "plaza",
        "shopping center",
        "shopping centre",
        "strip mall",
        "marketplace",
        "retail center",
        "retail centre",
        "mall",
        "village shops",
        "town center",
        "town centre",
    )
    return any(signal in haystack for signal in signals)


def _distance_meters(left: Lead, right: Lead) -> float:
    if (
        left.latitude is None
        or left.longitude is None
        or right.latitude is None
        or right.longitude is None
    ):
        return float("inf")

    earth_radius_meters = 6_371_000
    left_lat = math.radians(left.latitude)
    right_lat = math.radians(right.latitude)
    delta_lat = math.radians(right.latitude - left.latitude)
    delta_lon = math.radians(right.longitude - left.longitude)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(left_lat) * math.cos(right_lat) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_meters * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _leading_street_number(value: str) -> str:
    match = re.match(r"^(\d+[a-z]?)\b", value)
    return match.group(1) if match else ""


def _street_tokens_without_number(value: str) -> list[str]:
    tokens = value.split()
    if tokens and re.match(r"^\d+[a-z]?$", tokens[0]):
        tokens = tokens[1:]
    return [token for token in tokens if token not in {"n", "s", "e", "w"}]


def _keyword_matches(keyword: str, configured_value: str) -> bool:
    configured = configured_value.lower().strip()
    return keyword == configured or configured in keyword


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def _cluster_key(lead: Lead) -> str:
    if is_groupable_address(lead.full_address, lead.city):
        return f"address:{normalize_base_address(lead.full_address)}"
    if lead.latitude is not None and lead.longitude is not None:
        return f"geo:{round(lead.latitude, 3)}:{round(lead.longitude, 3)}"
    return f"lead:{normalize_business_name(lead.business_name)}"
