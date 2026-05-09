export const BACKEND_URLS = {
  // Local development only. For a physical phone, replace this in the app with your PC's LAN IP.
  local: "http://localhost:3001",
  // Tester APK builds must use a hosted API URL here, never localhost.
  hosted: ""
};

export const DEFAULT_BACKEND_BASE_URL = BACKEND_URLS.hosted || BACKEND_URLS.local;
