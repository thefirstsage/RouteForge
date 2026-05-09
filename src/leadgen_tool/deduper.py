from __future__ import annotations

from leadgen_tool.classifier import (
    is_groupable_address,
    normalize_address,
    normalize_base_address,
    normalize_business_name,
)
from leadgen_tool.models import Lead


def deduplicate_leads(leads: list[Lead]) -> list[Lead]:
    seen: dict[tuple[str, str], Lead] = {}
    for lead in leads:
        key = (
            normalize_business_name(lead.business_name),
            _dedupe_address_key(lead),
        )
        if key not in seen:
            seen[key] = lead
            continue

        existing = seen[key]
        seen[key] = _merge_duplicate(existing, lead)

    return list(seen.values())


def _dedupe_address_key(lead: Lead) -> str:
    if is_groupable_address(lead.full_address, lead.city):
        return normalize_base_address(lead.full_address)
    return normalize_address(lead.full_address)


def _merge_duplicate(existing: Lead, incoming: Lead) -> Lead:
    winner = _choose_better(existing, incoming)
    other = incoming if winner is existing else existing

    winner.source_keywords = _merge_text_lists(
        winner.source_keywords or [],
        other.source_keywords or [],
    )
    winner.keyword_match_count = len(winner.source_keywords)
    winner.is_chain = winner.is_chain or other.is_chain
    winner.same_address_count = max(winner.same_address_count, other.same_address_count)
    winner.strip_mall_confidence = max(
        winner.strip_mall_confidence, other.strip_mall_confidence
    )
    winner.lead_quality_score = max(winner.lead_quality_score, other.lead_quality_score)

    if not winner.website and other.website:
        winner.website = other.website
    if not winner.phone and other.phone:
        winner.phone = other.phone
    if winner.address_quality != "full_street_address" and other.address_quality == "full_street_address":
        winner.full_address = other.full_address
        winner.address_quality = other.address_quality
    if winner.latitude is None and other.latitude is not None:
        winner.latitude = other.latitude
    if winner.longitude is None and other.longitude is not None:
        winner.longitude = other.longitude
    return winner


def _choose_better(existing: Lead, incoming: Lead) -> Lead:
    existing_score = _quality_score(existing)
    incoming_score = _quality_score(incoming)
    return incoming if incoming_score > existing_score else existing


def _merge_text_lists(left: list[str], right: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in [*left, *right]:
        key = value.lower().strip()
        if key and key not in seen:
            seen.add(key)
            merged.append(value)
    return merged


def _quality_score(lead: Lead) -> int:
    score = 0
    if lead.address_quality == "full_street_address":
        score += 4
    elif lead.address_quality == "partial_address":
        score += 1
    if lead.website:
        score += 2
    if lead.phone:
        score += 2
    if lead.full_address and normalize_address(lead.full_address) != normalize_address(lead.city):
        score += 1
    return score
