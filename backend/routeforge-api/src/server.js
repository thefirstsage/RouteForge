import { createServer } from "node:http";
import { URL } from "node:url";

const PORT = Number(process.env.PORT || 3001);
const OVERPASS_ENDPOINTS = [
  process.env.OVERPASS_URL,
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.openstreetmap.ru/api/interpreter"
].filter(Boolean);
const CACHE_TTL_MS = 12 * 60 * 60 * 1000;
const DEFAULT_LIMIT = 40;
const MAX_LIMIT = 80;
const REQUEST_TIMEOUT_MS = 30000;
const RATE_LIMIT_WINDOW_MS = 60 * 1000;
const RATE_LIMIT_MAX_REQUESTS = 30;
const IS_DEVELOPMENT = process.env.NODE_ENV !== "production";
const FEEDBACK_MAX_BYTES = 24 * 1024;
const FEEDBACK_TO_EMAIL = process.env.FEEDBACK_TO_EMAIL || "";
const FEEDBACK_FROM_EMAIL = process.env.FEEDBACK_FROM_EMAIL || "RouteForge <onboarding@resend.dev>";
const RESEND_API_KEY = process.env.RESEND_API_KEY || "";

const cache = new Map();
const rateLimitBuckets = new Map();

function logStep(message, details = {}) {
  console.log(`[routeforge-api] ${message}`, details);
}

function errorMessage(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

const TYPE_TAGS = {
  "Strip malls / plazas": [{ key: "shop" }, { key: "amenity", value: "restaurant" }, { key: "amenity", value: "cafe" }],
  Storefronts: [{ key: "shop" }],
  Restaurants: [{ key: "amenity", value: "restaurant" }],
  "Fast food": [{ key: "amenity", value: "fast_food" }],
  "Cafes / bakeries": [{ key: "amenity", value: "cafe" }, { key: "shop", value: "bakery" }],
  "Gas stations": [{ key: "amenity", value: "fuel" }],
  "Retail stores": [{ key: "shop" }],
  "Salons / barbers": [{ key: "shop", value: "hairdresser" }, { key: "shop", value: "beauty" }],
  "Gyms / fitness": [{ key: "leisure", value: "fitness_centre" }, { key: "sport" }],
  Pharmacies: [{ key: "amenity", value: "pharmacy" }],
  "Phone stores": [{ key: "shop", value: "mobile_phone" }, { key: "shop", value: "electronics" }],
  "Jewelry / clothing / shoes": [{ key: "shop", value: "jewelry" }, { key: "shop", value: "clothes" }, { key: "shop", value: "shoes" }],
  "Dry cleaners / laundromats": [{ key: "shop", value: "dry_cleaning" }, { key: "shop", value: "laundry" }, { key: "amenity", value: "laundry" }],
  "Property managers": [{ key: "office", value: "property_management" }, { key: "office", value: "estate_agent" }, { key: "shop", value: "estate_agent" }],
  "Leasing offices": [{ key: "office", value: "estate_agent" }, { key: "office", value: "property_management" }],
  "Medical / dental offices": [{ key: "amenity", value: "dentist" }, { key: "amenity", value: "doctors" }, { key: "healthcare" }],
  "Banks / credit unions": [{ key: "amenity", value: "bank" }],
  "Car washes": [{ key: "amenity", value: "car_wash" }],
  "Auto shops": [{ key: "shop", value: "car_repair" }, { key: "shop", value: "tyres" }, { key: "shop", value: "car" }],
  "New / opening soon": [{ key: "opening_hours" }, { key: "shop" }],
  "Construction / buildout": [{ key: "shop", value: "hardware" }, { key: "shop", value: "doityourself" }, { key: "office", value: "construction" }]
};

const BUSINESS_TYPE_ALIASES = {
  restaurants: "Restaurants",
  restaurant: "Restaurants",
  fast_food: "Fast food",
  fastfood: "Fast food",
  cafes: "Cafes / bakeries",
  cafe: "Cafes / bakeries",
  bakeries: "Cafes / bakeries",
  bakery: "Cafes / bakeries",
  gas_stations: "Gas stations",
  gas_station: "Gas stations",
  fuel: "Gas stations",
  retail: "Retail stores",
  retail_stores: "Retail stores",
  shops: "Retail stores",
  storefronts: "Storefronts",
  salons: "Salons / barbers",
  barbers: "Salons / barbers",
  beauty: "Salons / barbers",
  hairdresser: "Salons / barbers",
  gyms: "Gyms / fitness",
  fitness: "Gyms / fitness",
  pharmacies: "Pharmacies",
  pharmacy: "Pharmacies",
  phone_stores: "Phone stores",
  mobile_phone: "Phone stores",
  clothing: "Jewelry / clothing / shoes",
  shoes: "Jewelry / clothing / shoes",
  jewelry: "Jewelry / clothing / shoes",
  dry_cleaners: "Dry cleaners / laundromats",
  dry_cleaning: "Dry cleaners / laundromats",
  laundromats: "Dry cleaners / laundromats",
  laundry: "Dry cleaners / laundromats",
  property_managers: "Property managers",
  property_management: "Property managers",
  estate_agents: "Property managers",
  offices: "Property managers",
  banks: "Banks / credit unions",
  credit_unions: "Banks / credit unions",
  car_washes: "Car washes",
  car_wash: "Car washes",
  construction: "Construction / buildout",
  opening_soon: "New / opening soon"
};

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
  });
  response.end(JSON.stringify(payload));
}

function readJsonBody(request, maxBytes = FEEDBACK_MAX_BYTES) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => {
      body += chunk;
      if (Buffer.byteLength(body, "utf8") > maxBytes) {
        reject(new Error("Request body is too large."));
        request.destroy();
      }
    });
    request.on("end", () => {
      if (!body.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error("Invalid JSON body."));
      }
    });
    request.on("error", reject);
  });
}

function sanitizeText(value, maxLength = 2000) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseBusinessTypes(searchParams) {
  const parsed = searchParams
    .getAll("businessTypes")
    .concat(searchParams.get("businessTypes") || "")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => BUSINESS_TYPE_ALIASES[value.toLowerCase().replace(/[\s-]+/g, "_")] || value);
  return [...new Set(parsed)];
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
  return tag.value
    ? `["${escapeOverpass(tag.key)}"="${escapeOverpass(tag.value)}"]`
    : `["${escapeOverpass(tag.key)}"]`;
}

function tagsForBusinessTypes(types) {
  const tags = types.flatMap((type) => TYPE_TAGS[type] || []);
  const unique = new Map();
  for (const tag of tags) {
    unique.set(`${tag.key}:${tag.value || "*"}`, tag);
  }
  return [...unique.values()].slice(0, 24);
}

function buildAreaSetup({ city, state, useStateArea }) {
  if (useStateArea) {
    return `
area["boundary"="administrative"]["name"="${escapeOverpass(state)}"]["admin_level"="4"]->.stateArea;
area(area.stateArea)["boundary"="administrative"]["name"="${escapeOverpass(city)}"]->.searchArea;`;
  }
  return `area["boundary"="administrative"]["name"="${escapeOverpass(city)}"]->.searchArea;`;
}

function buildOverpassQuery({ city, state, businessTypes, limit, useStateArea = true }) {
  const filters = tagsForBusinessTypes(businessTypes);
  const fallbackFilters = [{ key: "amenity", value: "restaurant" }];
  const selectors = (filters.length ? filters : fallbackFilters).flatMap((tag) => {
    const filter = tagFilter(tag);
    return [
      `node(area.searchArea)${filter}["name"];`,
      `way(area.searchArea)${filter}["name"];`,
      `relation(area.searchArea)${filter}["name"];`
    ];
  });

  return `
[out:json][timeout:30];
${buildAreaSetup({ city, state, useStateArea })}
(
  ${selectors.join("\n  ")}
);
out tags center ${limit};
`;
}

function buildAreaTestQuery({ city, state, useStateArea = true }) {
  if (useStateArea) {
    return `
[out:json][timeout:30];
area["boundary"="administrative"]["name"="${escapeOverpass(state)}"]["admin_level"="4"]->.stateArea;
area(area.stateArea)["boundary"="administrative"]["name"="${escapeOverpass(city)}"];
out ids 1;
`;
  }
  return `
[out:json][timeout:30];
area["boundary"="administrative"]["name"="${escapeOverpass(city)}"];
out ids 1;
`;
}

function readableAddress(tags = {}) {
  const streetLine = [tags["addr:housenumber"], tags["addr:street"]].filter(Boolean).join(" ");
  const cityLine = [tags["addr:city"], tags["addr:state"], tags["addr:postcode"]].filter(Boolean).join(", ");
  return [streetLine, cityLine].filter(Boolean).join(", ");
}

function categoryFromTags(tags = {}) {
  const value = tags.shop || tags.amenity || tags.office || tags.leisure || tags.healthcare || "business";
  return value.replace(/_/g, " ");
}

function coordinatesForElement(element) {
  if (typeof element.lat === "number" && typeof element.lon === "number") {
    return { latitude: element.lat, longitude: element.lon };
  }
  if (element.center && typeof element.center.lat === "number" && typeof element.center.lon === "number") {
    return { latitude: element.center.lat, longitude: element.center.lon };
  }
  return { latitude: undefined, longitude: undefined };
}

function normalizeElement(element, fallbackCity, fallbackState) {
  const tags = element.tags || {};
  const name = tags.name?.trim();
  if (!name) {
    return null;
  }

  const coordinates = coordinatesForElement(element);
  return {
    id: `osm-${element.type}-${element.id}`,
    name,
    address: readableAddress(tags) || [fallbackCity, fallbackState].filter(Boolean).join(", "),
    phone: tags.phone || tags["contact:phone"] || "",
    category: categoryFromTags(tags),
    latitude: coordinates.latitude,
    longitude: coordinates.longitude,
    status: "New",
    notes: "",
    routeStopNumber: "",
    source: "osm_overpass",
    hidden: false,
    website: tags.website || tags["contact:website"] || ""
  };
}

function normalizedKey(business) {
  return `${business.name.toLowerCase().trim()}|${business.address.toLowerCase().trim()}`;
}

function dedupeBusinesses(businesses) {
  const seen = new Set();
  const result = [];
  for (const business of businesses) {
    const key = normalizedKey(business);
    if (!key.trim() || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(business);
  }
  return result;
}

function clientKey(request) {
  const forwardedFor = request.headers["x-forwarded-for"];
  if (typeof forwardedFor === "string" && forwardedFor.trim()) {
    return forwardedFor.split(",")[0].trim();
  }
  return request.socket.remoteAddress || "unknown";
}

function isRateLimited(request) {
  const key = clientKey(request);
  const now = Date.now();
  const bucket = rateLimitBuckets.get(key);
  if (!bucket || now - bucket.startedAt > RATE_LIMIT_WINDOW_MS) {
    rateLimitBuckets.set(key, { startedAt: now, count: 1 });
    return false;
  }
  bucket.count += 1;
  return bucket.count > RATE_LIMIT_MAX_REQUESTS;
}

async function postOverpass(endpoint, query) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    logStep("Overpass request", {
      endpoint,
      bodyPreview: query.replace(/\s+/g, " ").trim().slice(0, 700)
    });
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        Accept: "application/json",
        "User-Agent": "RouteForge/0.1 field-sales-route-planner"
      },
      body: new URLSearchParams({ data: query }).toString(),
      signal: controller.signal
    });
    logStep("Overpass response", { endpoint, status: response.status, ok: response.ok });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`Overpass returned ${response.status}: ${text.slice(0, 300)}`);
    }
    try {
      return JSON.parse(text);
    } catch (error) {
      logStep("Overpass JSON parse error", { endpoint, error: errorMessage(error), bodyPreview: text.slice(0, 300) });
      throw new Error(`Could not parse Overpass JSON: ${errorMessage(error)}`);
    }
  } catch (error) {
    if (error?.name === "AbortError") {
      logStep("Overpass timeout", { endpoint, timeoutMs: REQUEST_TIMEOUT_MS });
      throw new Error(`Overpass request timed out after ${REQUEST_TIMEOUT_MS}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function postOverpassWithFallback(query) {
  const errors = [];
  for (const endpoint of OVERPASS_ENDPOINTS) {
    try {
      const data = await postOverpass(endpoint, query);
      return { data, endpoint, errors };
    } catch (error) {
      const message = errorMessage(error);
      errors.push({ endpoint, error: message });
      logStep("Overpass endpoint failed", { endpoint, error: message });
    }
  }
  throw new Error(`All Overpass endpoints failed: ${errors.map((item) => `${item.endpoint}: ${item.error}`).join(" | ")}`);
}

async function fetchOverpassBusinesses(params) {
  logStep("Business search requested", params);
  let useStateArea = true;
  let areaQuery = buildAreaTestQuery({ ...params, useStateArea });
  const areaResult = await postOverpassWithFallback(areaQuery);
  let areaCount = areaResult.data.elements?.length || 0;
  logStep("Area lookup result", { endpoint: areaResult.endpoint, rawElementCount: areaCount, useStateArea });
  let finalAreaResult = areaResult;

  if (!areaCount) {
    useStateArea = false;
    areaQuery = buildAreaTestQuery({ ...params, useStateArea });
    const fallbackAreaResult = await postOverpassWithFallback(areaQuery);
    areaCount = fallbackAreaResult.data.elements?.length || 0;
    finalAreaResult = fallbackAreaResult;
    logStep("Fallback city-only area lookup result", {
      endpoint: fallbackAreaResult.endpoint,
      rawElementCount: areaCount,
      useStateArea
    });
  }

  if (!areaCount) {
    const error = new Error("Could not find search area for city/state.");
    error.debug = {
      endpoint: finalAreaResult.endpoint,
      city: params.city,
      state: params.state,
      areaQuery: areaQuery.trim()
    };
    throw error;
  }

  const query = buildOverpassQuery({ ...params, useStateArea });
  const result = await postOverpassWithFallback(query);
  const rawElements = result.data.elements || [];
  logStep("Business raw elements", { endpoint: result.endpoint, rawElementCount: rawElements.length });
  const businesses = rawElements
    .map((element) => normalizeElement(element, params.city, params.state))
    .filter(Boolean);
  const normalized = dedupeBusinesses(businesses).slice(0, params.limit);
  logStep("Business normalization complete", {
    endpoint: result.endpoint,
    normalizedResultCount: normalized.length
  });

  return {
    endpoint: result.endpoint,
    rawElementCount: rawElements.length,
    normalizedResultCount: normalized.length,
    businesses: normalized,
    errors: [...finalAreaResult.errors, ...result.errors],
    areaLookupUsedState: useStateArea
  };
}

async function handleBusinesses(response, url) {
  const city = (url.searchParams.get("city") || "").trim();
  const state = (url.searchParams.get("state") || "").trim();
  const businessTypes = parseBusinessTypes(url.searchParams);
  const limit = clampLimit(url.searchParams.get("limit"));

  if (!city || !state) {
    sendJson(response, 400, { error: "City and state are required." });
    return;
  }

  const cacheKey = JSON.stringify({
    city: city.toLowerCase(),
    state: state.toLowerCase(),
    businessTypes: [...businessTypes].sort(),
    limit
  });
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.createdAt < CACHE_TTL_MS) {
    sendJson(response, 200, cached.businesses);
    return;
  }

  try {
    const result = await fetchOverpassBusinesses({ city, state, businessTypes, limit });
    cache.set(cacheKey, { createdAt: Date.now(), businesses: result.businesses });
    sendJson(response, 200, result.businesses);
  } catch (error) {
    const message = errorMessage(error);
    console.error("Overpass search failed", error);
    sendJson(response, 502, {
      error: "Real business search is temporarily unavailable. Demo data can be used in the mobile app.",
      ...(IS_DEVELOPMENT ? { debug: { message, details: error.debug } } : {})
    });
  }
}

async function handleDebugBusinessesTest(response) {
  const params = {
    city: "Livonia",
    state: "Michigan",
    businessTypes: ["Restaurants"],
    limit: 10
  };
  try {
    const result = await fetchOverpassBusinesses(params);
    sendJson(response, 200, {
      ok: true,
      endpointUsed: result.endpoint,
      areaLookupUsedState: result.areaLookupUsedState,
      rawElementCount: result.rawElementCount,
      normalizedResultCount: result.normalizedResultCount,
      first3: result.businesses.slice(0, 3),
      endpointErrors: IS_DEVELOPMENT ? result.errors : undefined
    });
  } catch (error) {
    sendJson(response, 502, {
      ok: false,
      error: errorMessage(error),
      details: IS_DEVELOPMENT ? error.debug : undefined
    });
  }
}

async function sendFeedbackEmail(feedback) {
  if (!RESEND_API_KEY || !FEEDBACK_TO_EMAIL) {
    logStep("Feedback received without email provider configured", {
      type: feedback.type,
      name: feedback.name,
      email: feedback.email,
      messagePreview: feedback.message.slice(0, 160)
    });
    return { sent: false, configured: false };
  }

  const subject = `RouteForge feedback: ${feedback.type}`;
  const html = `
    <h2>RouteForge Feedback</h2>
    <p><strong>Type:</strong> ${escapeHtml(feedback.type)}</p>
    <p><strong>Name:</strong> ${escapeHtml(feedback.name || "Not provided")}</p>
    <p><strong>Email:</strong> ${escapeHtml(feedback.email || "Not provided")}</p>
    <p><strong>Screen:</strong> ${escapeHtml(feedback.screen || "Unknown")}</p>
    <p><strong>Route:</strong> ${escapeHtml(feedback.routeName || "None")}</p>
    <p><strong>App:</strong> ${escapeHtml(feedback.appVersion || "RouteForge Mobile")}</p>
    <hr />
    <p style="white-space: pre-wrap;">${escapeHtml(feedback.message)}</p>
  `;

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${RESEND_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      from: FEEDBACK_FROM_EMAIL,
      to: [FEEDBACK_TO_EMAIL],
      subject,
      html,
      reply_to: feedback.email || undefined
    })
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Feedback email provider returned ${response.status}: ${text.slice(0, 300)}`);
  }
  return { sent: true, configured: true };
}

async function handleFeedback(request, response) {
  try {
    const body = await readJsonBody(request);
    const feedback = {
      type: sanitizeText(body.type || "Feedback", 80),
      name: sanitizeText(body.name, 120),
      email: sanitizeText(body.email, 160),
      message: sanitizeText(body.message, 4000),
      screen: sanitizeText(body.screen, 80),
      routeName: sanitizeText(body.routeName, 160),
      appVersion: sanitizeText(body.appVersion || "RouteForge Mobile", 80)
    };

    if (!feedback.message || feedback.message.length < 4) {
      sendJson(response, 400, { error: "Please enter a little more detail before sending." });
      return;
    }

    const emailResult = await sendFeedbackEmail(feedback);
    if (!emailResult.configured) {
      sendJson(response, 503, {
        error: "Feedback email is not configured on this server."
      });
      return;
    }
    sendJson(response, 200, { ok: true, message: "Feedback sent." });
  } catch (error) {
    console.error("Feedback submission failed", error);
    sendJson(response, 500, {
      error: "Could not send feedback right now. Please try again.",
      ...(IS_DEVELOPMENT ? { debug: errorMessage(error) } : {})
    });
  }
}

createServer((request, response) => {
  const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  if (request.method === "OPTIONS") {
    sendJson(response, 204, {});
    return;
  }
  if (request.method === "GET" && url.pathname === "/health") {
    sendJson(response, 200, { ok: true, service: "routeforge-api" });
    return;
  }
  if (request.method === "GET" && url.pathname === "/debug/businesses-test") {
    void handleDebugBusinessesTest(response);
    return;
  }
  if (request.method === "GET" && url.pathname === "/businesses") {
    if (isRateLimited(request)) {
      sendJson(response, 429, { error: "Too many requests. Please wait a minute and try again." });
      return;
    }
    void handleBusinesses(response, url);
    return;
  }
  if (request.method === "POST" && url.pathname === "/feedback") {
    if (isRateLimited(request)) {
      sendJson(response, 429, { error: "Too many requests. Please wait a minute and try again." });
      return;
    }
    void handleFeedback(request, response);
    return;
  }
  sendJson(response, 404, { error: "Not found." });
}).listen(PORT, "0.0.0.0", () => {
  console.log(`RouteForge API listening on http://localhost:${PORT}`);
});