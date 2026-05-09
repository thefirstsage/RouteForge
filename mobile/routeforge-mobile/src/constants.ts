import type { StopStatus } from "./models";

export const US_STATES = [
  "Alabama",
  "Alaska",
  "Arizona",
  "Arkansas",
  "California",
  "Colorado",
  "Connecticut",
  "Delaware",
  "Florida",
  "Georgia",
  "Hawaii",
  "Idaho",
  "Illinois",
  "Indiana",
  "Iowa",
  "Kansas",
  "Kentucky",
  "Louisiana",
  "Maine",
  "Maryland",
  "Massachusetts",
  "Michigan",
  "Minnesota",
  "Mississippi",
  "Missouri",
  "Montana",
  "Nebraska",
  "Nevada",
  "New Hampshire",
  "New Jersey",
  "New Mexico",
  "New York",
  "North Carolina",
  "North Dakota",
  "Ohio",
  "Oklahoma",
  "Oregon",
  "Pennsylvania",
  "Rhode Island",
  "South Carolina",
  "South Dakota",
  "Tennessee",
  "Texas",
  "Utah",
  "Vermont",
  "Virginia",
  "Washington",
  "West Virginia",
  "Wisconsin",
  "Wyoming"
];

export const BUSINESS_TYPES = [
  "Strip malls / plazas",
  "Storefronts",
  "Restaurants",
  "Fast food",
  "Cafes / bakeries",
  "Gas stations",
  "Retail stores",
  "Salons / barbers",
  "Gyms / fitness",
  "Pharmacies",
  "Phone stores",
  "Jewelry / clothing / shoes",
  "Dry cleaners / laundromats",
  "Property managers",
  "Leasing offices",
  "Medical / dental offices",
  "Banks / credit unions",
  "Car washes",
  "Auto shops",
  "New / opening soon",
  "Construction / buildout"
];

export const BUSINESS_TYPE_PRESETS = [
  {
    name: "Best storefront route",
    types: ["Strip malls / plazas", "Storefronts", "Retail stores", "Salons / barbers", "Phone stores"]
  },
  {
    name: "Food + retail",
    types: ["Restaurants", "Fast food", "Cafes / bakeries", "Retail stores"]
  },
  {
    name: "Property managers",
    types: ["Property managers", "Leasing offices", "Strip malls / plazas"]
  },
  {
    name: "Exterior cleaning targets",
    types: ["Storefronts", "Gas stations", "Car washes", "Auto shops", "Banks / credit unions"]
  }
];

export const STOP_STATUSES: StopStatus[] = [
  "New",
  "Visited",
  "Turned Away",
  "Manager Not In",
  "Called",
  "No Answer",
  "Interested",
  "Need Follow-Up",
  "Not Interested",
  "Done",
  "Skipped"
];

export const CONTACT_ATTEMPT_STATUSES: StopStatus[] = [
  "Visited",
  "Turned Away",
  "Manager Not In",
  "Called",
  "No Answer"
];

export const FOLLOW_UP_STATUSES: StopStatus[] = [
  "Interested",
  "Need Follow-Up"
];

export const PRIMARY_ROUTE_STATUSES: StopStatus[] = [
  "Visited",
  "Interested",
  "Need Follow-Up",
  "Not Interested",
  "Done"
];

export const SECONDARY_ROUTE_STATUSES: StopStatus[] = [
  "Manager Not In",
  "No Answer",
  "Turned Away",
  "Called",
  "Skipped"
];

export const COMPLETED_ROUTE_STATUSES: StopStatus[] = [
  "Visited",
  "Not Interested",
  "Done",
  "Skipped"
];
