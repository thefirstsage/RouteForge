export const BACKEND_URLS = {
  // Local development only. For a physical phone, replace this in the app with your PC's LAN IP.
  local: "http://localhost:3001",
  // Tester APK builds must use a hosted API URL here, never localhost.
  hosted: "https://routeforge-gqrb.onrender.com"
};

export const DEFAULT_BACKEND_BASE_URL = BACKEND_URLS.hosted || BACKEND_URLS.local;

// Keep backend URLs out of the normal tester UI. Flip this locally only when debugging connection issues.
export const SHOW_BACKEND_DEBUG = false;
