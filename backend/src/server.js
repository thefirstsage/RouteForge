import { createServer } from "node:http";
import { URL } from "node:url";

const PORT = Number(process.env.PORT || 3001);
const OVERPASS_URL = process.env.OVERPASS_URL || "https://overpass-api.de/api/interpreter";
const CACHE_TTL_MS = 12 * 60 * 60 * 1000;
const DEFAULT_LIMIT = 40;
const MAX_LIMIT = 80;
const REQUEST_TIMEOUT_MS = 25000;

const cache = new Map();

const TYPE_TAGS = {
  "Strip malls / plazas": [
    { key: "shop" },
    { key: "amenity", value: "restaurant" },
    { key: "amenity", value: "cafe" }
  ],
  Storefronts: [{ key: "shop" }],
  Restaurants: [{ key: "amenity", value: "restaurant" }],
  "Fast food": [{ key: "amenity", value: "fast_food" }],
  "Cafes / bakeries": [
    { key: "amenity", value: "cafe" },
    { key: "shop", value: "bakery" }
  ],
  "Gas stations": [{ key: "amenity", value: "fuel" }],
  "Retail stores": [{ key: "shop" }],
  "Salons / barbers": [
    { key: "shop", value: "hairdresser" },
    { key: "shop", value: "beauty" },
    { key: "shop", value: "cosmetics" }
  ],
  "Gyms / fitness": [
    { key: "leisure", value: "fitness_centre" },
    { key: "sport" }
  ],
  Pharmacies: [{ key: "amenity", value: "pharmacy" }],
  "Phone stores": [
    { key: "shop", value: "mobile_phone" },
    { key: "shop", value: "electronics" }
  ],
  "Jewelry / clothing / shoes": [
    { key: "shop", value: "jewelry" },
    { key: "shop", value: "clothes" },
    { key: "shop", value: "shoes" }
  ],
  "Dry cleaners / laundromats": [
    { key: "shop", value: "dry_cleaning" },
    { key: "shop", value: "laundry" },
    { key: "amenity", value: "laundry" }
  ],
  "Property managers": [
    { key: "office", value: "property_management" },
    { key: "office", value: "estate_agent" },
    { key: "shop", value: "estate_agent" }
  ],
  "Leasing offices": [
    { key: "office", value: "estate_agent" },
    { key: "office", value: "property_management" }
  ],
  "Medical / dental offices": [
    { key: "amenity", value: "dentist" },
    { key: "amenity", value: "doctors" },
    { key: "healthcare" }
  ],
  "Banks / credit unions": [{ key: "amenity", value: "bank" }],
  "Car washes": [{ key: "amenity", value: "car_wash" }],
  "Auto shops": [
    { key: "shop", value: "car_repair" },
    { key: "shop", value: "tyres" },
    { key: "shop", value: "car" }
  ],
  "New / opening soon": [
    { key: "opening_hours" },
    { key: "shop" }
  ],
  "Construction / buildout": [
    { key: "shop", value: "hardware" },
    { key: "shop", value: "doityourself" },
    { key: "office", value: "construction" }
  ]
};

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
  });
  response.end(JSON.stringify(payload));
}

function parseBusinessTypes(searchParams) {
  const repeated = searchParams.getAll("businessTypes").flatMap((value) => value.split(","));
  const single = (searchParams.get("businessTypes") || "").split(",");
  return [...repeated, ...single]
    .map((value) => value.trim())
    .filter(Boolean);
}

function clampLimit(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_LIMIT;
  }
  return Math.min(MAX_LIMIT, Math.max(1, Math.floor(parsed)));
}

function escapeOverpass(value) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function tagFilter(tag) {
  if (tag.value) {
    return `["${escapeOverpass(tag.key)}"="${escapeOverpass(tag.value)}"]`;
  }
  return `["${escapeOverpass(tag.key)}"]`;
}

function tagsForBusinessTypes(types) {
  const tags = types.flatMap((type) => TYPE_TAGS[type] || []);
  const unique = new Map();
  for (const tag of tags) {
    unique.set(`${tag.key}:${tag.value || "*"}`, tag);
  }
  return [...unique.values()].slice(0, 24);
}

function buildOverpassQuery({ city, state, businessTypes, limit }) {
  const cityName = escapeOverpass(city);
  const stateName = escapeOverpass(state);
  const tags = tagsForBusinessTypes(businessTypes);
  const filters = tags.length ? tags : [{ key: "shop" }, { key: "amenity" }, { key: "office" }];
  const selectors = filters.flatMap((tag) => {
    const filter = tagFilter(tag);
    return [
      `node(area.searchArea)${filter}["name"];`,
      `way(area.searchArea)${filter}["name"];`,
      `relation(area.searchArea)${filter}["name"];`
    ];
  });

  return `
[out:json][timeout:25];
area["boundary"="administrative"]["name"="${stateName}"]["admin_level"="4"]->.stateArea;
area(area.stateArea)["boundary"="administrative"]["name"="${cityName}"]->.searchArea;
(
  ${selectors.join("\n  ")}
);
out center tags ${limit};
`;
}

function readableAddress(tags = {}) {
  const house = tags["addr:housenumber"];
  const street = tags["addr:street"];
  const unit = tags["addr:unit"] || tags["addr:suite"];
  const city = tags["addr:city"];
  const state = tags["addr:state"];
  const postcode = tags["addr:postcode"];
  const streetLine = [house, street].filter(Boolean).join(" ");
  const unitLine = unit ? `Unit ${unit}` : "";
  const cityLine = [city, state, postcode].filter(Boolean).join(", ").replace(", ,", ",");
  return [streetLine, unitLine, cityLine].filter(Boolean).join(", ");
}

function categoryFromTags(tags = {}) {
  if (tags.shop) {
    return tags.shop.replace(/_/g, " ");
  }
  if (tags.amenity) {
    return tags.amenity.replace(/_/g, " ");
  }
  if (tags.office) {
    return tags.office.replace(/_/g, " ");
  }
  if (tags.leisure) {
    return tags.leisure.replace(/_/g, " ");
  }
  if (tags.healthcare) {
    return tags.healthcare.replace(/_/g, " ");
  }
  return "business";
}

function coordinatesForElement(element) {
  if (typeof element.lat === "number" && typeof element.lon === "number") {
    return { latitude: element.lat, longitude: element.lon };
  }
  if (element.center && typeof element.center.lat === "number" && typeof element.center.lon === "number") {
    return { latitude: element.center.lat, longitude: element.center.lon };
  }
  return {};
}

function normalizeElement(element, fallbackCity, fallbackState) {
  const tags = element.tags || {};
  const name = tags.name?.trim();
  if (!name) {
    return null;
  }
  const coordinates = coordinatesForElement(element);
  const fallbackAddress = [fallbackCity, fallbackState].filter(Boolean).join(", ");
  return {
    id: `osm-${element.type}-${element.id}`,
    name,
    address: readableAddress(tags) || fallbackAddress,
    phone: tags["contact:phone"] || tags.phone || "",
    category: categoryFromTags(tags),
    latitude: coordinates.latitude,
    longitude: coordinates.longitude,
    status: "New",
    notes: "",
    routeStopNumber: undefined,
    contactAttempts: 0,
    history: [],
    source: "osm_overpass",
    hidden: false,
    bestStop: Boolean(tags.shop || tags.amenity === "restaurant" || tags.amenity === "cafe"),
    website: tags["contact:website"] || tags.website || ""
  };
}

function dedupeBusinesses(businesses) {
  const seen = new Set();
  const result = [];
  for (const business of businesses) {
    const key = `${business.name.toLowerCase()}|${business.address.toLowerCase()}|${business.phone}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(business);
  }
  return result;
}

async function fetchOverpassBusinesses(params) {
  const query = buildOverpassQuery(params);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(OVERPASS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
      body: new URLSearchParams({ data: query }).toString(),
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`Overpass returned ${response.status}`);
    }
    const data = await response.json();
    const normalized = (data.elements || [])
      .map((element) => normalizeElement(element, params.city, params.state))
      .filter(Boolean);
    return dedupeBusinesses(normalized).slice(0, params.limit);
  } finally {
    clearTimeout(timeout);
  }
}

async function handleBusinesses(request, response, url) {
  const city = (url.searchParams.get("city") || "").trim();
  const state = (url.searchParams.get("state") || "").trim();
  const businessTypes = parseBusinessTypes(url.searchParams);
  const limit = clampLimit(url.searchParams.get("limit"));

  if (!city || !state) {
    sendJson(response, 400, { error: "City and state are required." });
    return;
  }

  const cacheKey = JSON.stringify({ city: city.toLowerCase(), state: state.toLowerCase(), businessTypes: [...businessTypes].sort(), limit });
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.createdAt < CACHE_TTL_MS) {
    sendJson(response, 200, { businesses: cached.businesses, source: "cache" });
    return;
  }

  try {
    const businesses = await fetchOverpassBusinesses({ city, state, businessTypes, limit });
    cache.set(cacheKey, { createdAt: Date.now(), businesses });
    sendJson(response, 200, { businesses, source: "osm_overpass" });
  } catch (error) {
    console.error("Overpass search failed", error);
    sendJson(response, 502, {
      error: "Real business search is temporarily unavailable. Try again later or use demo data."
    });
  }
}

const server = createServer((request, response) => {
  const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  if (request.method === "OPTIONS") {
    sendJson(response, 204, {});
    return;
  }
  if (request.method === "GET" && url.pathname === "/health") {
    sendJson(response, 200, { ok: true });
    return;
  }
  if (request.method === "GET" && url.pathname === "/businesses") {
    void handleBusinesses(request, response, url);
    return;
  }
  sendJson(response, 404, { error: "Not found." });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`RouteForge backend listening on http://localhost:${PORT}`);
});
