from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from leadgen_tool.config import app_data_dir
from leadgen_tool.models import Lead

_saved_leads_cache: list[Lead] | None = None
_saved_leads_cache_path: Path | None = None
_saved_leads_cache_mtime: float | None = None


def saved_leads_path() -> Path:
    return app_data_dir() / "saved_leads.json"


def saved_progress_dir() -> Path:
    return app_data_dir() / "saved_progress"


def presets_path() -> Path:
    return app_data_dir() / "saved_presets.json"


def routes_path() -> Path:
    return app_data_dir() / "saved_routes.json"


def suppression_path() -> Path:
    return app_data_dir() / "hidden_businesses.json"


def save_leads_in_app(leads: list[Lead]) -> Path:
    global _saved_leads_cache, _saved_leads_cache_path, _saved_leads_cache_mtime
    destination = saved_leads_path()
    if not leads:
        return destination
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_leads(destination, _merge_leads(load_saved_leads(), leads))
    except PermissionError:
        destination = Path(__file__).resolve().parent.parent / "saved_leads.json"
        _write_leads(destination, _merge_leads(load_saved_leads(), leads))
    _saved_leads_cache = _merge_leads(_saved_leads_cache or [], leads)
    _saved_leads_cache_path = destination
    try:
        _saved_leads_cache_mtime = destination.stat().st_mtime
    except OSError:
        _saved_leads_cache_mtime = None
    return destination


def load_saved_leads() -> list[Lead]:
    global _saved_leads_cache, _saved_leads_cache_path, _saved_leads_cache_mtime
    path = saved_leads_path()
    if not path.exists():
        fallback = Path(__file__).resolve().parent.parent / "saved_leads.json"
        path = fallback if fallback.exists() else path
    if not path.exists():
        _saved_leads_cache = []
        _saved_leads_cache_path = path
        _saved_leads_cache_mtime = None
        return []

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if (
        _saved_leads_cache is not None
        and _saved_leads_cache_path == path
        and _saved_leads_cache_mtime == mtime
    ):
        return list(_saved_leads_cache)

    with path.open("r", encoding="utf-8-sig") as handle:
        payload: list[dict[str, Any]] = json.load(handle)
    _saved_leads_cache = [_lead_from_payload(item) for item in payload]
    _saved_leads_cache_path = path
    _saved_leads_cache_mtime = mtime
    return list(_saved_leads_cache)


def list_saved_progress() -> dict[str, dict[str, Any]]:
    saves: dict[str, dict[str, Any]] = {}
    folders = [
        saved_progress_dir(),
        Path(__file__).resolve().parent.parent / "saved_progress",
    ]
    for folder in folders:
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            name = str(payload.get("name") or path.stem).strip() or path.stem
            saves[name] = {
                "path": str(path),
                "saved_at": str(payload.get("saved_at") or ""),
                "lead_count": len(payload.get("leads", [])) if isinstance(payload.get("leads"), list) else 0,
            }
    return dict(sorted(saves.items(), key=lambda item: item[1].get("saved_at", ""), reverse=True))


def save_progress_snapshot(
    name: str,
    leads: list[Lead],
    route_leads: list[Lead] | None = None,
    route_current_index: int = 0,
    route_completed_count: int = 0,
) -> Path:
    safe_name = _safe_filename(name)
    if not safe_name:
        safe_name = "RouteForge Progress"
    destination = saved_progress_dir() / f"{safe_name}.json"
    payload = {
        "name": name.strip() or safe_name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "leads": [lead.to_dict() for lead in leads],
        "route_leads": [lead.to_dict() for lead in (route_leads or [])],
        "route_current_index": route_current_index,
        "route_completed_count": route_completed_count,
    }
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_json(destination, payload)
    except PermissionError:
        destination = Path(__file__).resolve().parent.parent / "saved_progress" / f"{safe_name}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_json(destination, payload)
    return destination


def load_progress_snapshot(name: str) -> dict[str, Any]:
    saves = list_saved_progress()
    meta = saves.get(name)
    if not meta:
        return {"leads": [], "route_leads": []}
    path = Path(str(meta["path"]))
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return {"leads": [], "route_leads": []}
    leads_payload = payload.get("leads", [])
    route_payload = payload.get("route_leads", [])
    return {
        "name": str(payload.get("name") or name),
        "saved_at": str(payload.get("saved_at") or ""),
        "leads": [
            _lead_from_payload(item)
            for item in leads_payload
            if isinstance(item, dict)
        ] if isinstance(leads_payload, list) else [],
        "route_leads": [
            _lead_from_payload(item)
            for item in route_payload
            if isinstance(item, dict)
        ] if isinstance(route_payload, list) else [],
        "route_current_index": int(payload.get("route_current_index") or 0),
        "route_completed_count": int(payload.get("route_completed_count") or 0),
    }


def load_presets() -> dict[str, dict[str, Any]]:
    path = presets_path()
    if not path.exists():
        fallback = Path(__file__).resolve().parent.parent / "saved_presets.json"
        path = fallback if fallback.exists() else path
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8-sig") as handle:
        payload: dict[str, dict[str, Any]] = json.load(handle)
    return payload


def save_preset(name: str, preset: dict[str, Any]) -> Path:
    destination = presets_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        presets = load_presets()
        presets[name] = preset
        _write_json(destination, presets)
    except PermissionError:
        destination = Path(__file__).resolve().parent.parent / "saved_presets.json"
        presets = load_presets()
        presets[name] = preset
        _write_json(destination, presets)
    return destination


def delete_preset(name: str) -> Path | None:
    destination = presets_path()
    if not destination.exists():
        fallback = Path(__file__).resolve().parent.parent / "saved_presets.json"
        destination = fallback if fallback.exists() else destination
    if not destination.exists():
        return None

    presets = load_presets()
    if name not in presets:
        return destination
    presets.pop(name, None)
    _write_json(destination, presets)
    return destination


def load_routes() -> dict[str, dict[str, Any]]:
    path = routes_path()
    if not path.exists():
        fallback = Path(__file__).resolve().parent.parent / "saved_routes.json"
        path = fallback if fallback.exists() else path
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8-sig") as handle:
        payload: dict[str, dict[str, Any]] = json.load(handle)
    return payload


def save_route(name: str, leads: list[Lead]) -> Path:
    destination = routes_path()
    route_payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "leads": [lead.to_dict() for lead in leads],
    }
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        routes = load_routes()
        routes[name] = route_payload
        _write_json(destination, routes)
    except PermissionError:
        destination = Path(__file__).resolve().parent.parent / "saved_routes.json"
        routes = load_routes()
        routes[name] = route_payload
        _write_json(destination, routes)
    return destination


def load_route(name: str) -> list[Lead]:
    routes = load_routes()
    route = routes.get(name, {})
    payload = route.get("leads", [])
    if not isinstance(payload, list):
        return []
    return [_lead_from_payload(item) for item in payload if isinstance(item, dict)]


def delete_route(name: str) -> Path | None:
    destination = routes_path()
    if not destination.exists():
        fallback = Path(__file__).resolve().parent.parent / "saved_routes.json"
        destination = fallback if fallback.exists() else destination
    if not destination.exists():
        return None

    routes = load_routes()
    if name not in routes:
        return destination
    routes.pop(name, None)
    _write_json(destination, routes)
    return destination


def load_suppressed_businesses() -> list[dict[str, Any]]:
    path = suppression_path()
    if not path.exists():
        fallback = Path(__file__).resolve().parent.parent / "hidden_businesses.json"
        path = fallback if fallback.exists() else path
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_suppressed_business(lead: Lead, reason: str) -> Path:
    destination = suppression_path()
    existing = load_suppressed_businesses()
    keys = _suppression_keys_for_lead(lead)
    components = _suppression_components_for_lead(lead)
    today = datetime.now().date().isoformat()
    entry = {
        "business_name": lead.business_name,
        "address": lead.full_address,
        "phone": lead.phone,
        "normalized_name": components["name"],
        "normalized_address": components["address"],
        "normalized_phone": components["phone"],
        "city": lead.city,
        "status": lead.status,
        "notes": lead.notes,
        "reason": reason,
        "date_hidden": today,
        "keys": sorted(keys),
    }
    merged = [
        item for item in existing
        if _suppression_match_count(_entry_components(item), components) < 2
    ]
    merged.append(entry)
    _write_json(destination, merged)
    return destination


def save_suppressed_businesses(entries: list[dict[str, Any]]) -> Path:
    destination = suppression_path()
    _write_json(destination, entries)
    return destination


def restore_suppressed_business(entry: dict[str, Any]) -> Path:
    target_components = _entry_components(entry)
    entries = [
        item for item in load_suppressed_businesses()
        if _suppression_match_count(_entry_components(item), target_components) < 2
    ]
    return save_suppressed_businesses(entries)


def clear_suppressed_businesses() -> Path:
    return save_suppressed_businesses([])


def suppression_match_for_lead(lead: Lead) -> dict[str, Any] | None:
    return suppression_match_for_lead_in_entries(lead, load_suppressed_businesses())


def suppression_match_for_lead_in_entries(
    lead: Lead,
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lead_components = _suppression_components_for_lead(lead)
    for item in entries:
        if _suppression_match_count(_entry_components(item), lead_components) >= 2:
            return item
    return None


def _suppression_components_for_lead(lead: Lead) -> dict[str, str]:
    return {
        "name": _normalize_text(lead.business_name),
        "address": _normalize_text(lead.full_address),
        "phone": _normalize_phone(lead.phone),
    }


def _entry_components(item: dict[str, Any]) -> dict[str, str]:
    return {
        "name": _normalize_text(str(item.get("normalized_name") or item.get("business_name") or "")),
        "address": _normalize_text(str(item.get("normalized_address") or item.get("address") or "")),
        "phone": _normalize_phone(str(item.get("normalized_phone") or item.get("phone") or "")),
    }


def _suppression_match_count(first: dict[str, str], second: dict[str, str]) -> int:
    return sum(
        1
        for key in ("name", "address", "phone")
        if first.get(key) and second.get(key) and first[key] == second[key]
    )


def _suppression_keys_for_lead(lead: Lead) -> set[str]:
    keys: set[str] = set()
    name = _normalize_text(lead.business_name)
    address = _normalize_text(lead.full_address)
    city = _normalize_text(lead.city)
    phone = _normalize_phone(lead.phone)
    if name and address:
        keys.add(f"name_address:{name}|{address}")
    if name and city:
        keys.add(f"name_city:{name}|{city}")
    if phone:
        keys.add(f"phone:{phone}")
    return keys


def _lead_from_payload(item: dict[str, Any]) -> Lead:
    allowed_fields = Lead.__dataclass_fields__.keys()
    clean_item = {key: value for key, value in item.items() if key in allowed_fields}
    if not isinstance(clean_item.get("contact_history"), list):
        clean_item["contact_history"] = []
    if not isinstance(clean_item.get("contact_method_history"), list):
        clean_item["contact_method_history"] = []
    if "contact_attempts" in clean_item:
        try:
            clean_item["contact_attempts"] = int(clean_item["contact_attempts"] or 0)
        except (TypeError, ValueError):
            clean_item["contact_attempts"] = 0
    return Lead(**clean_item)


def _normalize_text(value: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {" ", "-", "_"} else "_" for ch in value)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:80].strip(" .")


def _lead_key(lead: Lead) -> tuple[str, str]:
    return (
        lead.business_name.strip().lower(),
        lead.full_address.strip().lower(),
    )


def _merge_leads(existing: list[Lead], incoming: list[Lead]) -> list[Lead]:
    merged = {_lead_key(lead): lead for lead in existing}
    for lead in incoming:
        key = _lead_key(lead)
        previous = merged.get(key)
        if previous is None:
            merged[key] = lead
            continue

        if previous.status and not lead.status:
            lead.status = previous.status
        lead.last_contacted = lead.last_contacted or previous.last_contacted
        lead.next_follow_up_date = lead.next_follow_up_date or previous.next_follow_up_date
        lead.contact_attempts = max(lead.contact_attempts, previous.contact_attempts)
        lead.contact_history = lead.contact_history or previous.contact_history or []
        lead.contact_method_history = (
            lead.contact_method_history or previous.contact_method_history or []
        )
        lead.route_stop_number = lead.route_stop_number or previous.route_stop_number
        lead.date_added = previous.date_added or lead.date_added
        merged[key] = lead
    return list(merged.values())


def _write_leads(destination: Path, leads: list[Lead]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = [lead.to_dict() for lead in leads]
    _write_json(destination, payload)


def _write_json(destination: Path, payload: Any) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
