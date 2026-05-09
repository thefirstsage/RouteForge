# RouteForge Mobile MVP

RouteForge mobile is a local-first field route MVP.

Tagline: Plan your route. Knock more doors. Close more deals.

## What Works

- Enter starting location and city/area.
- Choose state and business types.
- Use quick business type presets.
- Generate real OSM businesses through the local RouteForge backend.
- Fall back to clearly labeled demo data when the backend is unavailable.
- Select stops.
- Save a named route.
- Reopen saved routes.
- Track stop outcomes.
- Track follow-up status and optional follow-up date.
- Hide businesses from future generated results.
- Open one stop or the full route in Google Maps.

## Run

Start the backend first for real businesses:

```powershell
cd C:\Users\User\Documents\Codex\LeadGen\backend\routeforge-api
npm.cmd install
npm.cmd start
```

Find your computer's local IP address:

```powershell
ipconfig
```

Use the IPv4 address on your WiFi/network adapter in the mobile app's `Real data backend` field, for example:

```text
http://192.168.1.25:3001
```

Then start the mobile app.

For development in an emulator, the default backend URL is:

```text
http://localhost:3001
```

For a real phone, `localhost` means the phone itself, so use your PC's LAN IP.

For tester APK builds, use a hosted backend URL instead of localhost. Before building, edit:

```text
src/config.ts
```

Set:

```ts
hosted: "https://your-hosted-routeforge-api.example.com"
```

Then build the APK. The app will use the hosted URL by default.

Hosted backend quick checklist:

1. Deploy `backend/routeforge-api` to Render or another Node host.
2. Test `https://YOUR_HOSTED_URL/health`.
3. Confirm it returns `{ "ok": true, "service": "routeforge-api" }`.
4. Set `hosted` in `src/config.ts`.
5. Rebuild the APK.
6. Test on cellular data before sharing with testers.

From this folder:

```powershell
npm install
npm run start
```

If PowerShell aliases cause issues, use:

```powershell
npm.cmd install
npm.cmd run start
```

If a Codex/PowerShell shell blocks npm script shims with `Access is denied`, run Expo directly:

```powershell
node .\node_modules\expo\bin\cli start
```

## Build Android APK For Testers

Use this when you want an installable Android build for testers who do not have Expo Go or are not on the same WiFi.

From this folder:

```powershell
npm.cmd install
npm.cmd install -g eas-cli
eas login
eas build:configure
eas build --platform android --profile preview
```

If EAS says `git command not found` or `Repair your Git installation`, use this PowerShell command instead:

```powershell
$env:EAS_NO_VCS="1"; eas.cmd build --platform android --profile preview --clear-cache
```

Notes:

- The `preview` profile creates an APK.
- The APK can be installed directly on Android phones.
- The phone may require enabling `Install unknown apps`.
- No Google Play Store release is needed for early testing.
- Production Android releases usually use an AAB instead of an APK.

## Notes

- Real business search uses the backend in `C:\Users\User\Documents\Codex\LeadGen\backend\routeforge-api`.
- OpenStreetMap may not include phone numbers for every business.
- Missing phone numbers show as `Phone not listed`.
- Demo fallback data is clearly labeled and uses fake phone numbers.
- Persistence uses AsyncStorage.
- There is no login, billing, dashboard, embedded map, or desktop migration in this MVP.
