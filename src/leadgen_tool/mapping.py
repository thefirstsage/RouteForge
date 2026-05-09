from __future__ import annotations

import json
import math
from html import escape

import requests

from leadgen_tool.models import Lead


TIER_COLORS = {
    "Tier 1": "#38aeea",
    "Tier 2": "#ffe58a",
    "Tier 3": "#7a8793",
}


def filter_map_leads(leads: list[Lead], mode: str) -> list[Lead]:
    if mode == "tier1":
        return [lead for lead in leads if lead.priority_tier == "Tier 1"]
    return list(leads)


def plan_route(
    leads: list[Lead],
    start_location: tuple[float, float] | None = None,
) -> list[Lead]:
    candidates = [
        lead for lead in leads if lead.latitude is not None and lead.longitude is not None
    ]
    if len(candidates) < 2:
        return candidates or list(leads)

    ordered = _nearest_neighbor_route(candidates, start_location)
    ordered = _two_opt_open_route(ordered, start_location)
    unmapped = [lead for lead in leads if lead.latitude is None or lead.longitude is None]
    return ordered + unmapped


def _nearest_neighbor_route(
    candidates: list[Lead],
    start_location: tuple[float, float] | None,
) -> list[Lead]:
    if not candidates:
        return []
    if start_location:
        remaining = candidates[:]
        current = min(remaining, key=lambda lead: _distance_from_point(start_location, lead))
        ordered = [current]
        remaining.remove(current)
        while remaining:
            next_lead = min(remaining, key=lambda lead: _distance_meters(current, lead))
            ordered.append(next_lead)
            remaining.remove(next_lead)
            current = next_lead
        return ordered

    best_route: list[Lead] = []
    best_distance = float("inf")
    start_candidates = candidates if len(candidates) <= 35 else candidates[:35]
    for first in start_candidates:
        remaining = candidates[:]
        ordered = [first]
        remaining.remove(first)
        current = first
        while remaining:
            next_lead = min(remaining, key=lambda lead: _distance_meters(current, lead))
            ordered.append(next_lead)
            remaining.remove(next_lead)
            current = next_lead
        distance = _route_distance(ordered, None)
        if distance < best_distance:
            best_distance = distance
            best_route = ordered
    return best_route or candidates[:]


def _two_opt_open_route(
    route: list[Lead],
    start_location: tuple[float, float] | None,
) -> list[Lead]:
    if len(route) < 4:
        return route
    best = route[:]
    best_distance = _route_distance(best, start_location)
    improved = True
    while improved:
        improved = False
        for left in range(0, len(best) - 2):
            for right in range(left + 2, len(best)):
                candidate = best[:left] + list(reversed(best[left:right + 1])) + best[right + 1:]
                distance = _route_distance(candidate, start_location)
                if distance + 1 < best_distance:
                    best = candidate
                    best_distance = distance
                    improved = True
                    break
            if improved:
                break
    return best


def _route_distance(route: list[Lead], start_location: tuple[float, float] | None) -> float:
    if not route:
        return 0
    distance = 0.0
    if start_location:
        distance += _distance_from_point(start_location, route[0])
    for index in range(len(route) - 1):
        distance += _distance_meters(route[index], route[index + 1])
    return distance


def geocode_start_address(address: str, state: str = "") -> tuple[float, float] | None:
    clean_address = address.strip()
    if not clean_address:
        return None
    query = clean_address if not state else f"{clean_address}, {state}"
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "WashAway Lead Dispatch route planner"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not payload:
        return None
    try:
        return float(payload[0]["lat"]), float(payload[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def build_route_text(leads: list[Lead]) -> str:
    if not leads:
        return "No route available yet."

    lines = []
    for index, lead in enumerate(leads, start=1):
        reason = lead.lead_reason or "No lead reason"
        lines.append(
            f"{index}. {lead.business_name} | {lead.full_address} | {lead.priority_tier} | "
            f"{lead.recommended_visit_window or 'Visit any time'} | {reason}"
        )
    return "\n".join(lines)


def build_map_lead_list(leads: list[Lead]) -> str:
    mapped = [
        lead for lead in leads if lead.latitude is not None and lead.longitude is not None
    ]
    if not mapped:
        return "No route businesses yet."

    lines = []
    for index, lead in enumerate(mapped, start=1):
        lines.append(
            f"{index}. {lead.business_name} | {lead.priority_tier} | "
            f"{lead.full_address} | {lead.lead_reason or 'No lead reason'}"
        )
    return "\n".join(lines)


def build_map_html(
    leads: list[Lead],
    route_leads: list[Lead] | None = None,
    dark_mode: bool = False,
) -> str:
    mapped_leads = [
        lead for lead in leads if lead.latitude is not None and lead.longitude is not None
    ]
    route_order_by_key = {
        _lead_key(lead): index
        for index, lead in enumerate(route_leads or [], start=1)
    }
    points = [
        {
            "index": index,
            "key": _lead_key(lead),
            "route_order": route_order_by_key.get(_lead_key(lead)),
            "name": lead.business_name,
            "tier": lead.priority_tier,
            "reason": lead.lead_reason,
            "address": lead.full_address,
            "phone": lead.phone,
            "email": lead.email,
            "website": lead.website,
            "hours": lead.hours_of_operation,
            "visit_window": lead.recommended_visit_window,
            "color": TIER_COLORS.get(lead.priority_tier, TIER_COLORS["Tier 3"]),
            "lat": lead.latitude,
            "lng": lead.longitude,
        }
        for index, lead in enumerate(mapped_leads, start=1)
    ]
    route_points = [
        {"lat": lead.latitude, "lng": lead.longitude, "name": lead.business_name}
        for lead in (route_leads or [])
        if lead.latitude is not None and lead.longitude is not None
    ]
    payload = json.dumps(points)
    route_payload = json.dumps(route_points)
    summary = f"{len(points)} route businesses"
    panel_background = "#171b22" if dark_mode else "#ffffff"
    panel_border = "#325568" if dark_mode else "#dce6ef"
    panel_text = "#8ddcff" if dark_mode else "#17212b"
    popup_tier = "#fff2a8" if dark_mode else "#38aeea"
    page_background = "#0d1116" if dark_mode else "#f4f7fb"
    tile_url = (
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        if dark_mode
        else "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
    )
    tile_attribution = "&copy; OpenStreetMap contributors &copy; CARTO"
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RouteForge Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
  <style>
    html, body, #map {{ height: 100%; margin: 0; font-family: Segoe UI, Arial, sans-serif; background: {page_background}; }}
    .summary {{
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 999;
      background: {panel_background};
      color: {panel_text};
      padding: 11px 14px;
      border-radius: 8px;
      border: 1px solid {panel_border};
      box-shadow: 0 10px 24px rgba(0,0,0,0.28);
      font-weight: 700;
    }}
    .leaflet-popup-content-wrapper, .leaflet-popup-tip {{
      background: {panel_background};
      color: {panel_text};
      border: 1px solid {panel_border};
      box-shadow: 0 10px 24px rgba(0,0,0,0.3);
    }}
    .popup-title {{ font-weight: 700; margin-bottom: 6px; color: {panel_text}; }}
    .popup-tier {{ font-size: 12px; color: {popup_tier}; margin-bottom: 6px; }}
    .marker-pin {{
      width: 26px;
      height: 26px;
      border-radius: 50%;
      border: 2px solid #ffffff;
      box-shadow: 0 4px 10px rgba(0,0,0,0.28);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #17212b;
      font-size: 12px;
      font-weight: 700;
    }}
    .route-pin {{
      box-shadow: 0 0 0 4px rgba(56,174,234,0.22), 0 5px 12px rgba(0,0,0,0.32);
    }}
    .selected-marker .marker-pin {{
      transform: scale(1.22);
      border-color: #fff2a8;
      box-shadow: 0 0 0 5px rgba(255,229,138,0.42), 0 8px 18px rgba(0,0,0,0.34);
    }}
    .route-order {{
      background: #38aeea;
      color: #ffffff;
      border: 1px solid #ffffff;
      border-radius: 999px;
      width: 20px;
      height: 20px;
      line-height: 20px;
      text-align: center;
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="summary">{escape(summary)}</div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <script>
    const points = {payload};
    const routePoints = {route_payload};
    const map = L.map('map').setView([39.8283, -98.5795], 4);
    L.tileLayer('{tile_url}', {{
      maxZoom: 18,
      attribution: '{tile_attribution}',
      subdomains: 'abcd'
    }}).addTo(map);

    const markers = L.markerClusterGroup();
    const bounds = [];
    points.forEach(point => {{
      const icon = L.divIcon({{
        className: '',
        html: `<div class="marker-pin ${{point.route_order ? 'route-pin' : ''}}" style="background:${{point.color}}">${{point.route_order || point.index}}</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13]
      }});
      const marker = L.marker([point.lat, point.lng], {{ icon }});
      marker.bindPopup(
        `<div class="popup-title">${{point.name}}</div>` +
        `<div class="popup-tier">${{point.tier}}</div>` +
        `<div>${{point.reason || ''}}</div>` +
        `<div style="margin-top:6px;">${{point.address || ''}}</div>` +
        `<div>${{point.phone || ''}}</div>` +
        `<div>${{point.email || ''}}</div>` +
        `<div>${{point.website || ''}}</div>` +
        `<div>${{point.hours || ''}}</div>` +
        `<div>${{point.visit_window || ''}}</div>`
      );
      markers.addLayer(marker);
      marker.leadIndex = point.index;
      marker.leadKey = point.key;
      marker.leadLatLng = [point.lat, point.lng];
      window.leadMarkers = window.leadMarkers || {{}};
      window.leadMarkersByKey = window.leadMarkersByKey || {{}};
      window.leadMarkers[point.index] = marker;
      window.leadMarkersByKey[point.key] = marker;
      marker.on('click', function() {{
        window.selectLeadMarker(point.key);
        window.location.hash = 'lead=' + encodeURIComponent(point.key);
      }});
      bounds.push([point.lat, point.lng]);
    }});
    map.addLayer(markers);

    window.selectedLeadMarker = null;
    window.selectLeadMarker = function(key) {{
      const marker = window.leadMarkersByKey ? window.leadMarkersByKey[key] : null;
      if (!marker) {{
        return false;
      }}
      if (window.selectedLeadMarker && window.selectedLeadMarker._icon) {{
        window.selectedLeadMarker._icon.classList.remove('selected-marker');
      }}
      window.selectedLeadMarker = marker;
      if (marker._icon) {{
        marker._icon.classList.add('selected-marker');
      }}
      return true;
    }};

    window.focusLead = function(index) {{
      const marker = window.leadMarkers ? window.leadMarkers[index] : null;
      if (!marker) {{
        return false;
      }}
      const targetZoom = Math.max(map.getZoom(), 17);
      markers.zoomToShowLayer(marker, function() {{
        window.selectLeadMarker(marker.leadKey);
        map.flyTo(marker.getLatLng(), targetZoom, {{ duration: 0.45 }});
        marker.openPopup();
      }});
      return true;
    }};

    window.focusLeadByKey = function(key) {{
      const marker = window.leadMarkersByKey ? window.leadMarkersByKey[key] : null;
      if (!marker) {{
        return false;
      }}
      const targetZoom = Math.max(map.getZoom(), 17);
      markers.zoomToShowLayer(marker, function() {{
        window.selectLeadMarker(key);
        map.flyTo(marker.getLatLng(), targetZoom, {{ duration: 0.45 }});
        marker.openPopup();
      }});
      return true;
    }};

    if (routePoints.length > 1) {{
      const routeLine = L.polyline(routePoints.map(point => [point.lat, point.lng]), {{
        color: '#38aeea',
        weight: 4,
        opacity: 0.75
      }});
      routeLine.addTo(map);
    }}

    if (routePoints.length) {{
      map.fitBounds(routePoints.map(point => [point.lat, point.lng]), {{ padding: [42, 42] }});
    }} else if (bounds.length) {{
      map.fitBounds(bounds, {{ padding: [30, 30] }});
    }}
  </script>
</body>
</html>
"""


def _route_priority_score(lead: Lead) -> float:
    tier_score = {"Tier 1": 30, "Tier 2": 18, "Tier 3": 6}.get(lead.priority_tier, 0)
    timing_bonus = 6 if "before 11" in lead.recommended_visit_window.lower() else 0
    timing_bonus += 4 if "after 2" in lead.recommended_visit_window.lower() else 0
    return tier_score + lead.lead_quality_score / 4 + timing_bonus


def _lead_key(lead: Lead) -> str:
    return f"{lead.business_name.strip().lower()}|{lead.full_address.strip().lower()}"


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


def _distance_from_point(point: tuple[float, float], lead: Lead) -> float:
    if lead.latitude is None or lead.longitude is None:
        return float("inf")

    earth_radius_meters = 6_371_000
    left_lat = math.radians(point[0])
    right_lat = math.radians(lead.latitude)
    delta_lat = math.radians(lead.latitude - point[0])
    delta_lon = math.radians(lead.longitude - point[1])

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(left_lat) * math.cos(right_lat) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_meters * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
