import type { BusinessProvider, BusinessStop, FindBusinessesRequest } from "../models";
import { isStopHidden } from "../utils/normalize";

const DEFAULT_LIMIT = 60;

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, "");
}

function normalizePhone(phone?: string): string {
  return phone?.trim() || "";
}

function normalizeStop(raw: Partial<BusinessStop>, index: number): BusinessStop {
  return {
    id: raw.id || `real-${Date.now()}-${index}`,
    name: raw.name || "Unnamed business",
    address: raw.address || "",
    phone: normalizePhone(raw.phone),
    category: raw.category || "business",
    latitude: raw.latitude,
    longitude: raw.longitude,
    status: "New",
    notes: raw.notes || "",
    routeStopNumber: undefined,
    contactAttempts: 0,
    history: [],
    source: raw.source || "osm_overpass",
    hidden: false,
    bestStop: Boolean(raw.bestStop),
    website: raw.website
  };
}

export function createRealBusinessProvider(baseUrl: string): BusinessProvider {
  return {
    async findBusinesses(request: FindBusinessesRequest): Promise<BusinessStop[]> {
      const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
      if (!normalizedBaseUrl) {
        throw new Error("Backend URL is not set.");
      }

      const url = new URL(`${normalizedBaseUrl}/businesses`);
      url.searchParams.set("city", request.city);
      url.searchParams.set("state", request.state);
      url.searchParams.set("businessTypes", request.businessTypes.join(","));
      url.searchParams.set("limit", String(DEFAULT_LIMIT));

      const response = await fetch(url.toString());
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `Backend returned ${response.status}`);
      }

      const payload = await response.json();
      const businesses = Array.isArray(payload) ? payload : payload.businesses;
      if (!Array.isArray(businesses)) {
        throw new Error("Backend response did not include businesses.");
      }

      return businesses
        .map((business, index) => normalizeStop(business, index))
        .filter((stop) => stop.name.trim())
        .filter((stop) => !isStopHidden(stop, request.hiddenBusinesses));
    }
  };
}
