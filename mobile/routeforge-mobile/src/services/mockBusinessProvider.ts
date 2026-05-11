import type { BusinessProvider, BusinessStop, FindBusinessesRequest } from "../models";
import { isStopHidden } from "../utils/normalize";

const SAMPLE_NAMES = [
  "Main Street Grill",
  "Bright Dental Studio",
  "Oak Plaza Fitness",
  "Cityline Salon",
  "Northside Auto Care",
  "Harvest Coffee",
  "Lakeview Urgent Care",
  "Corner Market",
  "Prime Property Group",
  "Elm Street Bistro",
  "Summit Chiropractic",
  "Greenfield Cleaners",
  "Metro Bike Shop",
  "Horizon Realty",
  "Silver Spoon Cafe",
  "Parkway Pharmacy",
  "Elite Wireless",
  "Diamond Row Jewelers",
  "Fresh Fold Laundry",
  "Commerce Leasing Office",
  "First County Credit Union",
  "Sparkle Bay Car Wash",
  "Buildout Supply Co",
  "Maple Plaza Shops",
  "Quick Bite Burgers",
  "Morning Rise Bakery",
  "ProCare Dental",
  "Iron Core Fitness",
  "Style House Shoes",
  "Clean Stitch Dry Cleaners",
  "Westfield Property Services",
  "Metro Salon Suites",
  "Oak Ridge Bank",
  "Precision Auto Glass",
  "New Leaf Market",
  "The Corner Storefront",
  "Lakeside Phone Repair",
  "Northgate Retail Center",
  "Opening Soon Boutique"
];

const SAMPLE_STREETS = [
  "Main St",
  "Market Ave",
  "Grand River Ave",
  "Center Rd",
  "Oakland Blvd",
  "Commerce Dr"
];

function makeStop(index: number, city: string, state: string, businessTypes: string[]): BusinessStop {
  const category = businessTypes[index % Math.max(businessTypes.length, 1)] || "Retail";
  const name = SAMPLE_NAMES[index % SAMPLE_NAMES.length];
  const street = SAMPLE_STREETS[index % SAMPLE_STREETS.length];
  const bestStop =
    index % 4 === 0 ||
    category === "Property managers" ||
    category === "Strip malls / plazas" ||
    category === "Storefronts";

  return {
    id: `mock-${city.toLowerCase().replace(/\s+/g, "-")}-${index}`,
    name,
    address: `${100 + index * 7} ${street}, ${city}, ${state}`,
    phone: index % 5 === 0 ? "" : `(555) 01${String(index).padStart(2, "0")}`,
    category,
    latitude: 42.35 + index * 0.006,
    longitude: -83.25 - index * 0.006,
    status: "New",
    notes: bestStop ? "Looks like a strong walk-in stop." : "",
    routeStopNumber: undefined,
    contactAttempts: 0,
    history: [],
    source: "mock",
    hidden: false,
    bestStop,
    stopScore: bestStop ? 8 : 4,
    stopTier: bestStop ? "Best Stop" : "Good Stop"
  };
}

export const MockBusinessProvider: BusinessProvider = {
  async findBusinesses(request: FindBusinessesRequest): Promise<BusinessStop[]> {
    const selectedTypeCount = Math.max(request.businessTypes.length, 1);
    const count = Math.min(80, Math.max(24, selectedTypeCount * 5));
    const stops = Array.from({ length: count }, (_item, index) =>
      makeStop(index, request.city || "Target Area", request.state || "Michigan", request.businessTypes)
    );
    return stops.filter((stop) => !isStopHidden(stop, request.hiddenBusinesses));
  }
};
