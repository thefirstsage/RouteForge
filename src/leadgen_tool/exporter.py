from __future__ import annotations

import csv
from pathlib import Path

from leadgen_tool.models import EXPORT_HEADERS, Lead


def export_csv(leads: list[Lead], output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_HEADERS)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.export_row())

    return destination

