from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from leadgen_tool.classifier import (
    classify_leads,
    count_high_confidence_plazas,
    count_strip_mall_clusters,
)
from leadgen_tool.collector import OverpassCollector
from leadgen_tool.config import AppConfig, save_config, state_abbreviation
from leadgen_tool.deduper import deduplicate_leads
from leadgen_tool.exporter import export_csv
from leadgen_tool.logging import configure_logging
from leadgen_tool.models import Lead

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class RunSummary:
    total_raw_leads: int
    total_leads: int
    duplicates_removed: int
    tier1_leads: int
    output_path: Path
    leads: list[Lead]
    excluded_incomplete_address: int = 0
    excluded_city_mismatch: int = 0
    excluded_state_mismatch: int = 0
    strip_mall_clusters: int = 0
    high_confidence_plazas: int = 0
    excluded_low_value_category: int = 0


def run_lead_generation(
    config: AppConfig,
    selected_cities: list[str],
    output_directory: str | Path | None = None,
    output_path: str | Path | None = None,
    progress: ProgressCallback | None = None,
    save_settings: bool = True,
) -> RunSummary:
    logger = configure_logging()
    output_dir = Path(output_directory or config.output_directory)
    selected_cities = [city.strip() for city in selected_cities if city.strip()]
    if not selected_cities:
        raise ValueError("Enter at least one city before running the lead generator.")

    if save_settings:
        save_config(config)

    collector = OverpassCollector(config)
    collected: list[Lead] = []
    excluded_incomplete_address = 0
    excluded_city_mismatch = 0
    excluded_state_mismatch = 0
    excluded_low_value_category = 0

    _report(progress, f"Starting search in {config.state}: {', '.join(selected_cities)}")
    logger.info("Lead generation started for %s in %s", selected_cities, config.state)

    for city in selected_cities:
        _report(progress, f"Finding storefront businesses in {city}, {config.state}...")
        _report(progress, _search_phrase_preview(city, config))
        city_result = collector.collect_city_result(city, config.state)
        collected.extend(city_result.leads)
        excluded_incomplete_address += city_result.excluded_incomplete_address
        excluded_city_mismatch += city_result.excluded_city_mismatch
        excluded_state_mismatch += city_result.excluded_state_mismatch
        excluded_low_value_category += city_result.excluded_low_value_category
        _report(progress, f"Found {len(city_result.leads)} possible storefront leads in {city}.")
        if city_result.excluded_incomplete_address:
            _report(
                progress,
                f"Excluded {city_result.excluded_incomplete_address} {city} leads with incomplete addresses.",
            )
        if city_result.excluded_city_mismatch:
            _report(
                progress,
                f"Excluded {city_result.excluded_city_mismatch} out-of-city leads from {city}.",
            )
        if city_result.excluded_state_mismatch:
            _report(
                progress,
                f"Excluded {city_result.excluded_state_mismatch} out-of-state leads from {city}.",
            )
        if city_result.excluded_low_value_category:
            _report(
                progress,
                f"Filtered {city_result.excluded_low_value_category} low-value category matches in {city}.",
            )

    _report(progress, "Removing duplicate businesses...")
    deduped = deduplicate_leads(collected)

    _report(progress, "Scoring strip malls, chains, and storefront priority...")
    classified = classify_leads(deduped, config)
    high_confidence_plazas = count_high_confidence_plazas(classified)
    if high_confidence_plazas:
        _report(progress, f"Found {high_confidence_plazas} high-confidence plaza clusters.")

    destination = Path(output_path) if output_path else _build_output_path(
        output_dir, config.state, selected_cities
    )
    _report(progress, "Saving CSV file...")
    saved_path = export_csv(classified, destination)

    summary = RunSummary(
        total_raw_leads=len(collected),
        total_leads=len(classified),
        duplicates_removed=len(collected) - len(classified),
        tier1_leads=sum(1 for lead in classified if lead.priority_tier == "Tier 1"),
        output_path=saved_path,
        leads=classified,
        excluded_incomplete_address=excluded_incomplete_address,
        excluded_city_mismatch=excluded_city_mismatch,
        excluded_state_mismatch=excluded_state_mismatch,
        strip_mall_clusters=count_strip_mall_clusters(classified),
        high_confidence_plazas=high_confidence_plazas,
        excluded_low_value_category=excluded_low_value_category,
    )
    logger.info("Lead generation finished: %s", summary)
    _report(progress, f"Done. CSV saved to {saved_path}")
    return summary


def _build_output_path(output_dir: Path, state: str, cities: list[str]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    market = "_".join(city.lower().replace(" ", "_") for city in cities[:3])
    state_slug = state.lower().replace(" ", "_")
    return output_dir / f"storefront_leads_{state_slug}_{market}_{timestamp}.csv"


def _report(progress: ProgressCallback | None, message: str) -> None:
    if progress:
        progress(message)


def _search_phrase_preview(city: str, config: AppConfig) -> str:
    state_code = state_abbreviation(config.state)
    keywords = [keyword for keyword in config.search_keywords if keyword.strip()][:3]
    if not keywords:
        return f"Using selected market: {city}, {state_code}."
    phrases = "; ".join(f"{keyword} in {city}, {state_code}" for keyword in keywords)
    return f"Using selected market phrases: {phrases}."
