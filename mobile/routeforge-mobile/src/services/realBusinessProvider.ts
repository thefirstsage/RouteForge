import type { BusinessProvider, BusinessSearchDebug, BusinessStop, FindBusinessesRequest } from "../models";
import { isStopHidden } from "../utils/normalize";

const DEFAULT_LIMIT = 40;

const HIGH_VALUE_CATEGORY_TERMS = [
  "restaurant",
  "fast_food",
  "fast food",
  "cafe",
  "bakery",
  "retail",
  "shop",
  "salon",
  "hairdresser",
  "beauty",
  "pharmacy",
  "fuel",
  "gas station"
];

const PLAZA_TERMS = [
  "plaza",
  "strip mall",
  "shopping center",
  "shopping centre",
  "mall",
  "shops",
  "retail center",
  "retail centre"
];

const BUSINESS_TYPE_KEYS: Record<string, string[]> = {
  "Strip malls / plazas": ["retail", "restaurants", "fast_food", "cafes", "bakeries"],
  Storefronts: ["retail"],
  Restaurants: ["restaurants"],
  "Fast food": ["fast_food"],
  "Cafes / bakeries": ["cafes", "bakeries"],
  "Gas stations": ["gas_stations"],
  "Retail stores": ["retail"],
  "Salons / barbers": ["salons"],
  "Gyms / fitness": ["gyms"],
  Pharmacies: ["pharmacies"],
  "Phone stores": ["retail"],
  "Jewelry / clothing / shoes": ["retail"],
  "Dry cleaners / laundromats": ["laundromats"],
  "Property managers": ["property_managers"],
  "Leasing offices": ["offices", "estate_agents"],
  "Medical / dental offices": ["offices"],
  "Banks / credit unions": ["banks"],
  "Car washes": ["car_washes"],
  "Auto shops": ["retail"],
  "New / opening soon": ["retail"],
  "Construction / buildout": ["offices"]
};

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, "");
}

function normalizePhone(phone?: string): string {
  return phone?.trim() || "";
}

function backendBusinessTypeKeys(types: string[]): string[] {
  const keys = types.flatMap((type) => BUSINESS_TYPE_KEYS[type] || [type]);
  return [...new Set(keys.map((key) => key.trim()).filter(Boolean))];
}

function hasUsableStreetAddress(address?: string): boolean {
  const value = address?.trim() || "";
  return /\d/.test(value) && value.split(",")[0].trim().includes(" ");
}

function includesAny(value: string, terms: string[]): boolean {
  const normalized = value.toLowerCase();
  return terms.some((term) => normalized.includes(term));
}

function scoreStop(stop: BusinessStop): BusinessStop {
  const searchableText = `${stop.name} ${stop.address} ${stop.category}`.toLowerCase();
  let stopScore = 0;

  if (includesAny(stop.category, HIGH_VALUE_CATEGORY_TERMS)) {
    stopScore += 3;
  }
  if (includesAny(searchableText, PLAZA_TERMS)) {
    stopScore += 3;
  }
  if (stop.phone.trim()) {
    stopScore += 2;
  }
  if (stop.website?.trim()) {
    stopScore += 1;
  }
  if (hasUsableStreetAddress(stop.address)) {
    stopScore += 2;
  }
  if (typeof stop.latitude === "number" && typeof stop.longitude === "number") {
    stopScore += 1;
  }

  const stopTier = stopScore >= 7 ? "Best Stop" : stopScore >= 4 ? "Good Stop" : "Standard";
  return {
    ...stop,
    stopScore,
    stopTier,
    bestStop: stopTier === "Best Stop"
  };
}

function normalizeStop(raw: Partial<BusinessStop>, index: number): BusinessStop {
  return scoreStop({
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
  });
}

export function createRealBusinessProvider(
  baseUrl: string,
  onDebug?: (debug: BusinessSearchDebug) => void
): BusinessProvider {
  return {
    async findBusinesses(request: FindBusinessesRequest): Promise<BusinessStop[]> {
      const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
      if (!normalizedBaseUrl) {
        throw new Error("Backend URL is not set.");
      }

      const businessTypesSent = backendBusinessTypeKeys(request.businessTypes);
      const searchParams = new URLSearchParams({
        city: request.city.trim(),
        state: request.state.trim(),
        businessTypes: businessTypesSent.join(","),
        limit: String(DEFAULT_LIMIT)
      });
      const url = new URL(`${normalizedBaseUrl}/businesses`);
      url.search = searchParams.toString();

      onDebug?.({
        backendBaseUrl: normalizedBaseUrl,
        requestUrl: url.toString(),
        city: request.city.trim(),
        state: request.state.trim(),
        businessTypesSent,
        mode: "Pending"
      });

      const response = await fetch(url.toString());
      onDebug?.({
        backendBaseUrl: normalizedBaseUrl,
        requestUrl: url.toString(),
        city: request.city.trim(),
        state: request.state.trim(),
        businessTypesSent,
        httpStatus: response.status,
        mode: response.ok ? "Real data" : "Failed"
      });
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `Backend returned ${response.status}`);
      }

      const payload = await response.json();
      const businesses = Array.isArray(payload) ? payload : payload.businesses;
      if (!Array.isArray(businesses)) {
        throw new Error("Backend response did not include businesses.");
      }

      const usableBusinesses = businesses
        .map((business, index) => normalizeStop(business, index))
        .filter((stop) => stop.name.trim())
        .filter((stop) => !isStopHidden(stop, request.hiddenBusinesses));

      if (!usableBusinesses.length) {
        throw new Error("Backend returned zero usable businesses.");
      }

      return usableBusinesses;
    }
  };
}
