from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


EXPORT_HEADERS = [
    "Action Priority",
    "Priority Tier",
    "Business Name",
    "Full Address",
    "Phone",
    "Lead Reason",
    "Quick Notes",
    "Category",
    "City",
    "Website",
    "Email",
    "Google Maps URL",
    "Is Strip Mall",
    "Same Address Count",
    "Is Chain",
    "Property Manager Lead",
    "New / Pre-Opening Lead",
    "Construction Opportunity",
    "Hours of Operation",
    "Recommended Visit Window",
    "Status",
    "Notes",
    "Date Added",
    "Last Contacted",
    "Next Follow-Up Date",
    "Contact Attempts",
    "Contact History Summary",
    "Contact Method History",
    "Route Stop #",
    "Hidden / Suppressed",
    "Hidden Reason",
    "Source Keywords",
]


@dataclass
class Lead:
    business_name: str
    category: str
    city: str
    full_address: str
    website: str
    phone: str
    email: str = ""
    google_maps_url: str = ""
    is_strip_mall: bool = False
    same_address_count: int = 1
    is_chain: bool = False
    is_property_manager_lead: bool = False
    is_new_pre_opening_lead: bool = False
    is_construction_opportunity: bool = False
    hours_of_operation: str = ""
    recommended_visit_window: str = ""
    action_priority: str = "Optional"
    priority_tier: str = "Tier 3"
    date_added: str = ""
    source: str = "osm_overpass"
    status: str = "New"
    notes: str = ""
    last_contacted: str = ""
    next_follow_up_date: str = ""
    contact_attempts: int = 0
    contact_history: list[str] | None = None
    contact_method_history: list[str] | None = None
    route_stop_number: str = ""
    is_suppressed: bool = False
    suppression_reason: str = ""
    suppression_date: str = ""
    address_quality: str = "city_state_only"
    latitude: float | None = None
    longitude: float | None = None
    lead_quality_score: int = 0
    strip_mall_confidence: int = 0
    plaza_cluster_type: str = ""
    category_value: str = "unknown"
    lead_reason: str = ""
    quick_notes: str = ""
    source_keywords: list[str] | None = None
    keyword_match_count: int = 0
    keyword_quality_score: int = 0
    city_match_confidence: int = 100
    state_match_confidence: int = 100

    def ensure_date(self) -> None:
        if not self.date_added:
            self.date_added = date.today().isoformat()

    def export_row(self) -> dict[str, str]:
        self.ensure_date()
        return {
            "Action Priority": self.action_priority,
            "Priority Tier": self.priority_tier,
            "Business Name": self.business_name,
            "Full Address": self.full_address,
            "Phone": self.phone,
            "Lead Reason": self.lead_reason,
            "Quick Notes": self.quick_notes,
            "Category": self.category,
            "City": self.city,
            "Website": self.website,
            "Email": self.email,
            "Google Maps URL": self.google_maps_url,
            "Is Strip Mall": "Yes" if self.is_strip_mall else "No",
            "Same Address Count": str(self.same_address_count),
            "Is Chain": "Yes" if self.is_chain else "No",
            "Property Manager Lead": "Yes" if self.is_property_manager_lead else "No",
            "New / Pre-Opening Lead": "Yes" if self.is_new_pre_opening_lead else "No",
            "Construction Opportunity": "Yes" if self.is_construction_opportunity else "No",
            "Hours of Operation": self.hours_of_operation,
            "Recommended Visit Window": self.recommended_visit_window,
            "Status": self.status or "New",
            "Notes": self.notes,
            "Date Added": self.date_added,
            "Last Contacted": self.last_contacted,
            "Next Follow-Up Date": self.next_follow_up_date,
            "Contact Attempts": str(self.contact_attempts),
            "Contact History Summary": "; ".join(self.contact_history or []),
            "Contact Method History": "; ".join(self.contact_method_history or []),
            "Route Stop #": self.route_stop_number,
            "Hidden / Suppressed": "Yes" if self.is_suppressed else "No",
            "Hidden Reason": self.suppression_reason,
            "Source Keywords": ", ".join(self.source_keywords or []),
        }

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
