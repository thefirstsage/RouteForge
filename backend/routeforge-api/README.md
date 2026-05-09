# RouteForge API

Free real-data backend for RouteForge Mobile.

Architecture:

```text
mobile app -> RouteForge API -> OpenStreetMap / Overpass -> normalized BusinessStop results
```

No paid API keys are used.

## Run Locally

```powershell
cd C:\Users\User\Documents\Codex\LeadGen\backend\routeforge-api
npm.cmd install
npm.cmd start
```

Local URL:

```text
http://localhost:3001
```

For a physical phone on the same WiFi, do not use `localhost`. Use your computer's LAN IPv4 address:

```text
http://192.168.1.89:3001
```

## Endpoint

```http
GET /businesses?city=Livonia&state=Michigan&businessTypes=restaurants,retail,gas_stations&limit=40
```

Response is an array of `BusinessStop` objects.

Health check:

```http
GET /health
```

Response:

```json
{ "ok": true, "service": "routeforge-api" }
```

Debug test route:

```http
GET /debug/businesses-test
```

This runs:

```text
city=Livonia
state=Michigan
businessTypes=restaurants
limit=10
```

It returns the Overpass endpoint used, raw element count, normalized result count, the first 3 normalized businesses, and a safe error message if the search fails.

## Notes

- Default limit is `40`.
- Max limit is `80`.
- Cache duration is at least 12 hours.
- Basic per-IP rate limiting is enabled.
- Server logs include incoming search params, Overpass endpoint, query preview, HTTP status, timeout/parse errors, raw element count, and normalized business count.
- Phone numbers are returned only when OSM has `phone` or `contact:phone`.
- Missing phone numbers return an empty string.
- The backend never generates fake phone numbers.
- The mobile app falls back to clearly labeled demo data if this API is unavailable.

## Hosted Tester Builds

Tester APK builds should use a hosted API URL, not `localhost`.

Before building the APK, update:

```text
mobile/routeforge-mobile/src/config.ts
```

Set:

```ts
hosted: "https://your-hosted-routeforge-api.example.com"
```

Then build the APK.

## Render Deployment

1. Push the project to GitHub.
2. In Render, create a new Web Service.
3. Connect the GitHub repository.
4. Set Root Directory:

```text
backend/routeforge-api
```

5. Set Build Command:

```text
npm install
```

6. Set Start Command:

```text
npm start
```

7. Deploy the service.
8. Open:

```text
https://YOUR_RENDER_URL/health
```

Confirm it returns:

```json
{ "ok": true, "service": "routeforge-api" }
```

9. Copy the Render URL into:

```text
mobile/routeforge-mobile/src/config.ts
```

Set:

```ts
hosted: "https://YOUR_RENDER_URL"
```

10. Rebuild the tester APK.

Do not use `localhost` for tester APKs.
