export type StopStatus =
  | "New"
  | "Visited"
  | "Turned Away"
  | "Manager Not In"
  | "Called"
  | "No Answer"
  | "Interested"
  | "Need Follow-Up"
  | "Not Interested"
  | "Done"
  | "Skipped";

export type BusinessStop = {
  id: string;
  name: string;
  address: string;
  phone: string;
  category: string;
  latitude?: number;
  longitude?: number;
  status: StopStatus;
  notes: string;
  routeStopNumber?: number;
  lastContacted?: string;
  nextFollowUpDate?: string;
  contactAttempts: number;
  history: string[];
  source: "mock" | "manual" | "backend" | "overpass" | "osm_overpass";
  hidden: boolean;
  bestStop?: boolean;
  website?: string;
};

export type RouteSession = {
  id: string;
  name: string;
  city: string;
  state: string;
  startingLocation: string;
  businessTypes: string[];
  createdAt: string;
  updatedAt: string;
  stops: BusinessStop[];
  completedCount: number;
};

export type HiddenBusiness = {
  id: string;
  normalizedName: string;
  normalizedAddress: string;
  phone: string;
  reason: string;
  hiddenAt: string;
};

export type FindBusinessesRequest = {
  startingLocation: string;
  city: string;
  state: string;
  businessTypes: string[];
  hiddenBusinesses: HiddenBusiness[];
};

export type AppSettings = {
  lastSelectedState: string;
  backendBaseUrl?: string;
};

export type BusinessProvider = {
  findBusinesses(request: FindBusinessesRequest): Promise<BusinessStop[]>;
};
