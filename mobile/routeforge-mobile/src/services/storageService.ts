import AsyncStorage from "@react-native-async-storage/async-storage";
import type { AppSettings, HiddenBusiness, RouteSession } from "../models";
import { DEFAULT_BACKEND_BASE_URL } from "../config";

const ROUTES_KEY = "routeforge.routeSessions.v1";
const HIDDEN_KEY = "routeforge.hiddenBusinesses.v1";
const SETTINGS_KEY = "routeforge.settings.v1";

async function readJson<T>(key: string, fallback: T): Promise<T> {
  const raw = await AsyncStorage.getItem(key);
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

async function writeJson<T>(key: string, value: T): Promise<void> {
  await AsyncStorage.setItem(key, JSON.stringify(value));
}

export async function loadRouteSessions(): Promise<RouteSession[]> {
  return readJson<RouteSession[]>(ROUTES_KEY, []);
}

export async function saveRouteSession(session: RouteSession): Promise<void> {
  const sessions = await loadRouteSessions();
  const next = [session, ...sessions.filter((item) => item.id !== session.id)];
  await writeJson(ROUTES_KEY, next);
}

export async function deleteRouteSession(id: string): Promise<void> {
  const sessions = await loadRouteSessions();
  await writeJson(
    ROUTES_KEY,
    sessions.filter((session) => session.id !== id)
  );
}

export async function renameRouteSession(id: string, name: string): Promise<void> {
  const sessions = await loadRouteSessions();
  await writeJson(
    ROUTES_KEY,
    sessions.map((session) =>
      session.id === id ? { ...session, name, updatedAt: new Date().toISOString() } : session
    )
  );
}

export async function loadHiddenBusinesses(): Promise<HiddenBusiness[]> {
  return readJson<HiddenBusiness[]>(HIDDEN_KEY, []);
}

export async function saveHiddenBusiness(hidden: HiddenBusiness): Promise<void> {
  const hiddenBusinesses = await loadHiddenBusinesses();
  const duplicate = hiddenBusinesses.some(
    (item) =>
      (item.phone && item.phone === hidden.phone) ||
      (item.normalizedName === hidden.normalizedName &&
        item.normalizedAddress === hidden.normalizedAddress)
  );
  if (duplicate) {
    return;
  }
  await writeJson(HIDDEN_KEY, [hidden, ...hiddenBusinesses]);
}

export async function loadAppSettings(): Promise<AppSettings> {
  return readJson<AppSettings>(SETTINGS_KEY, {
    lastSelectedState: "Michigan",
    backendBaseUrl: DEFAULT_BACKEND_BASE_URL
  });
}

export async function saveAppSettings(settings: AppSettings): Promise<void> {
  await writeJson(SETTINGS_KEY, settings);
}
