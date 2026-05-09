# RouteForge Mobile MVP Plan

## Goal

RouteForge mobile is a field-first canvassing app for local service businesses. It should help a user enter a work area, generate businesses to visit, select stops, save a route/session, open the route in Google Maps, and track stop outcomes from a phone.

The mobile MVP lives in `mobile/routeforge-mobile/` and does not change the existing Windows PySide6 desktop app.

## Architecture

- **Framework:** Expo + React Native + TypeScript.
- **Navigation:** Lightweight in-app screen state for MVP. This avoids Expo Router setup friction and keeps the first version easy to run. React Navigation can replace this later without changing the data model.
- **Persistence:** AsyncStorage through `@react-native-async-storage/async-storage`.
- **Business generation:** `BusinessProvider` interface with a `MockBusinessProvider` implementation. A future backend or Overpass provider should implement the same interface.
- **Maps:** External Google Maps links only. No embedded map in MVP.

## Screens

1. **Start**
   - Starting location
   - City / area to canvass
   - Business type chips
   - Find Businesses
   - Open Saved Routes

2. **Business Results**
   - Mobile business cards
   - Select/unselect stops
   - Hide / Not Interested
   - Add manually

3. **Route Builder**
   - Selected stops in route order
   - Save Route
   - Open Full Route in Google Maps
   - Start Route

4. **Today’s Route**
   - Highest priority screen
   - Stop cards with phone, address, notes, status, and outcome buttons
   - Outcome buttons save immediately
   - Open Stop in Google Maps

5. **Saved Routes**
   - Reopen saved route
   - Continue route
   - Rename route
   - Delete route

6. **Manual Add Stop**
   - Name, address, phone, notes, status
   - Adds stop to current results/session

## Data Models

- `BusinessStop`
- `RouteSession`
- `HiddenBusiness`

Statuses:

- New
- Stopped In
- Called
- No Answer
- Interested
- Follow Up
- Not Interested
- Done
- Skipped

## Future Phases

1. Replace mock provider with backend-generated businesses.
2. Add optional geocoding/enrichment service.
3. Add better route optimization.
4. Add optional account sync only after the local-first MVP proves useful.

## Out of Scope for MVP

- Authentication
- Accounts
- Billing/subscriptions
- Team features
- Advanced maps
- Dashboards
- Desktop migration
