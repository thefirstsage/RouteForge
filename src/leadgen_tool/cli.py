from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from leadgen_tool.config import default_config_path, load_config
from leadgen_tool.runner import run_lead_generation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect storefront leads for window cleaning prospecting."
    )
    parser.add_argument(
        "--city",
        action="append",
        dest="cities",
        help="Collect a specific city. Repeat the flag for multiple cities.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Collect all cities from the config file.",
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Path to the JSON config file.",
    )
    parser.add_argument(
        "--output",
        help="Optional custom CSV path. Defaults to output/storefront_leads_<market>_<timestamp>.csv",
    )
    parser.add_argument(
        "--state",
        help="US state to search. Defaults to the state in config/targets.json.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)
    if args.state:
        config = replace(config, state=args.state)

    selected_cities = _resolve_cities(args.cities, args.all, config.cities, parser)
    output_directory = Path(args.output).parent if args.output else config.output_directory
    try:
        summary = run_lead_generation(
            config,
            selected_cities,
            output_directory=output_directory,
            output_path=args.output,
            progress=print,
            save_settings=False,
        )
    except Exception as exc:
        print(f"Lead generation stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Collected {summary.total_raw_leads} raw leads")
    print(f"Removed {summary.duplicates_removed} duplicates")
    print(f"Excluded {summary.excluded_incomplete_address} incomplete-address leads")
    print(f"Excluded {summary.excluded_city_mismatch} out-of-city leads")
    print(f"Excluded {summary.excluded_state_mismatch} out-of-state leads")
    print(f"Filtered {summary.excluded_low_value_category} low-value leads")
    print(f"Found {summary.high_confidence_plazas} high-confidence plaza clusters")
    print(f"Saved {summary.total_leads} leads to {summary.output_path}")


def _resolve_cities(
    requested_cities: list[str] | None,
    use_all: bool,
    configured_cities: list[str],
    parser: argparse.ArgumentParser,
) -> list[str]:
    if use_all:
        if not configured_cities:
            parser.error("No saved cities are configured. Provide --city instead.")
        return configured_cities

    if requested_cities:
        return [city.strip() for city in requested_cities if city.strip()]

    parser.error("Choose --all or provide at least one --city value.")
    return []


if __name__ == "__main__":
    main()
