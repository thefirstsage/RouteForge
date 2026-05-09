# RouteForge v0.2.0 Release Notes

This release prepares RouteForge for real-world mobile testing with a hosted backend.

## Highlights

- Added RouteForge mobile app source under `mobile/routeforge-mobile`.
- Added hosted backend API source under `backend/routeforge-api`.
- Backend uses OpenStreetMap / Overpass for real business data.
- Mobile app attempts real business search first.
- Mock/demo data remains available only as a clearly labeled fallback.
- Added visible `Demo Data` badges for mock results.
- Added RouteForge mobile app icon assets.
- Added Android APK build setup with EAS.
- Added Render deployment documentation.

## Render Backend

Use this Render setup:

- Root Directory: `backend/routeforge-api`
- Build Command: `npm install`
- Start Command: `npm start`

After deployment, verify:

```text
https://YOUR_RENDER_URL/health
https://YOUR_RENDER_URL/debug/businesses-test
https://YOUR_RENDER_URL/businesses?city=Livonia&state=Michigan&businessTypes=restaurants&limit=10
```

## Mobile APK Builds

Before building tester APKs, update:

```text
mobile/routeforge-mobile/src/config.ts
```

Set:

```ts
hosted: "https://YOUR_RENDER_URL"
```

Then build with:

```powershell
cd mobile\routeforge-mobile
$env:EAS_NO_VCS="1"; eas.cmd build --platform android --profile preview --clear-cache
```

## Real Data Gate

Before sending an APK to testers:

- Confirm whether it is a demo-data or real-data test.
- For real-data tests, confirm `src/config.ts` points to the hosted Render API.
- Test on cellular data, not only home WiFi.
- Confirm generated results are real businesses.

