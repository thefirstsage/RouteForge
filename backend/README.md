# RouteForge Backend

Simple local backend for RouteForge mobile real business search.

Phase 1 uses OpenStreetMap / Overpass.

## Run

From `C:\Users\User\Documents\Codex\LeadGen\backend`:

```powershell
npm.cmd install
npm.cmd start
```

The backend starts on:

```text
http://localhost:3001
```

For a real phone, use your computer's LAN IP instead of `localhost`, for example:

```text
http://192.168.1.25:3001
```

## Endpoint

```http
GET /businesses?city=Livonia&state=Michigan&businessTypes=Restaurants,Storefronts&limit=40
```

Response:

```json
{
  "businesses": [],
  "source": "osm_overpass"
}
```

## Notes

- No paid API keys are used.
- Phone numbers are only returned when OpenStreetMap has `phone` or `contact:phone`.
- Missing phone numbers are normal for this phase.
- Results are cached in memory for 12 hours by city/state/business types.
- Limit defaults to 40 and maxes at 80.
- Do not hammer Overpass during testing.

