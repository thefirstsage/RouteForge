import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Modal,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  StatusBar as RNStatusBar
} from "react-native";

import {
  BUSINESS_TYPE_PRESETS,
  BUSINESS_TYPES,
  COMPLETED_ROUTE_STATUSES,
  CONTACT_ATTEMPT_STATUSES,
  FOLLOW_UP_STATUSES,
  PRIMARY_ROUTE_STATUSES,
  SECONDARY_ROUTE_STATUSES,
  US_STATES
} from "./src/constants";
import { DEFAULT_BACKEND_BASE_URL } from "./src/config";
import type { BusinessStop, RouteSession, StopStatus } from "./src/models";
import {
  getGoogleMapsRouteParts,
  openRouteInGoogleMaps,
  openRoutePartInGoogleMaps,
  openStopInGoogleMaps
} from "./src/services/mapsService";
import { MockBusinessProvider } from "./src/services/mockBusinessProvider";
import { completedCount, orderStopsForRoute } from "./src/services/routeService";
import {
  deleteRouteSession,
  loadAppSettings,
  loadHiddenBusinesses,
  loadRouteSessions,
  renameRouteSession,
  saveAppSettings,
  saveHiddenBusiness,
  saveRouteSession
} from "./src/services/storageService";
import { createRealBusinessProvider } from "./src/services/realBusinessProvider";
import { theme } from "./src/theme";
import { hiddenBusinessFromStop } from "./src/utils/normalize";

type Screen = "start" | "results" | "builder" | "today" | "saved" | "manual";
type BusinessFilter = "all" | "best" | "walkable" | "plazas";

type ManualDraft = {
  name: string;
  address: string;
  phone: string;
  notes: string;
};

type FollowUpPrompt = {
  stopId: string;
  status: StopStatus;
} | null;

const initialManualDraft: ManualDraft = {
  name: "",
  address: "",
  phone: "",
  notes: ""
};
const LEGACY_VISIT_STATUS = ["Stopped", "In"].join(" ");

function newId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric"
  });
}

function isoDateDaysFromNow(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function defaultRouteName(city: string, businessTypes: string[]): string {
  const label = businessTypes[0] || "Route";
  return `${city || "RouteForge"} ${label} - ${shortDate(new Date().toISOString())}`;
}

function statusLabel(status: StopStatus): string {
  if (status === "Need Follow-Up") {
    return "Follow-Up";
  }
  return status;
}

function normalizeLegacyStopStatus(status: string): StopStatus {
  return status === LEGACY_VISIT_STATUS ? "Visited" : (status as StopStatus);
}

function normalizeRouteSession(session: RouteSession): RouteSession {
  const stops = session.stops.map((stop) => ({
    ...stop,
    status: normalizeLegacyStopStatus(stop.status)
  }));
  return {
    ...session,
    stops,
    completedCount: completedCount(stops)
  };
}

function isCompletedStop(stop: BusinessStop): boolean {
  return COMPLETED_ROUTE_STATUSES.includes(stop.status);
}

function isWalkableStop(stop: BusinessStop): boolean {
  const category = stop.category.toLowerCase();
  return (
    stop.bestStop ||
    category.includes("plaza") ||
    category.includes("storefront") ||
    category.includes("retail") ||
    category.includes("restaurant") ||
    category.includes("cafe")
  );
}

function isPlazaStop(stop: BusinessStop): boolean {
  const category = stop.category.toLowerCase();
  const name = stop.name.toLowerCase();
  return category.includes("plaza") || category.includes("strip") || name.includes("plaza") || name.includes("shops");
}

function Header({
  subtitle,
  onHome,
  onBack,
  onSavedRoutes,
  backLabel = "Back"
}: {
  subtitle: string;
  onHome: () => void;
  onBack?: () => void;
  onSavedRoutes: () => void;
  backLabel?: string;
}) {
  return (
    <View style={styles.header}>
      <View style={styles.headerActions}>
        <TouchableOpacity style={styles.headerButton} onPress={onHome}>
          <Text style={styles.headerButtonText}>Home</Text>
        </TouchableOpacity>
        {onBack ? (
          <TouchableOpacity style={styles.headerButton} onPress={onBack}>
            <Text style={styles.headerButtonText}>{backLabel}</Text>
          </TouchableOpacity>
        ) : null}
        <TouchableOpacity style={styles.headerButton} onPress={onSavedRoutes}>
          <Text style={styles.headerButtonText}>Saved</Text>
        </TouchableOpacity>
      </View>
      <Text style={styles.appName}>RouteForge</Text>
      <Text style={styles.tagline}>Plan your route. Knock more doors. Close more deals.</Text>
      <Text style={styles.screenSubtitle}>{subtitle}</Text>
    </View>
  );
}

function PrimaryButton({
  label,
  onPress,
  disabled = false
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[styles.primaryButton, disabled && styles.disabledButton]}
      onPress={onPress}
      disabled={disabled}
    >
      <Text style={styles.primaryButtonText}>{label}</Text>
    </TouchableOpacity>
  );
}

function SecondaryButton({
  label,
  onPress,
  danger = false
}: {
  label: string;
  onPress: () => void;
  danger?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[styles.secondaryButton, danger && styles.dangerButton]}
      onPress={onPress}
    >
      <Text style={styles.secondaryButtonText}>{label}</Text>
    </TouchableOpacity>
  );
}

function FieldLabel({ children }: { children: string }) {
  return <Text style={styles.sectionLabel}>{children}</Text>;
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("start");
  const [startingLocation, setStartingLocation] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("Michigan");
  const [businessTypes, setBusinessTypes] = useState<string[]>(BUSINESS_TYPE_PRESETS[0].types);
  const [businesses, setBusinesses] = useState<BusinessStop[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [savedRoutes, setSavedRoutes] = useState<RouteSession[]>([]);
  const [currentSession, setCurrentSession] = useState<RouteSession | null>(null);
  const [routeName, setRouteName] = useState("");
  const [renamingRouteId, setRenamingRouteId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [manualDraft, setManualDraft] = useState<ManualDraft>(initialManualDraft);
  const [expandedStopId, setExpandedStopId] = useState<string | null>(null);
  const [statePickerOpen, setStatePickerOpen] = useState(false);
  const [businessTypesOpen, setBusinessTypesOpen] = useState(false);
  const [showCustomBusinessTypes, setShowCustomBusinessTypes] = useState(false);
  const [followUpPrompt, setFollowUpPrompt] = useState<FollowUpPrompt>(null);
  const [followUpDateDraft, setFollowUpDateDraft] = useState("");
  const [followUpManualOpen, setFollowUpManualOpen] = useState(false);
  const [businessFilter, setBusinessFilter] = useState<BusinessFilter>("all");
  const [backendBaseUrl, setBackendBaseUrl] = useState(DEFAULT_BACKEND_BASE_URL);
  const [usingDemoData, setUsingDemoData] = useState(false);
  const [dataNotice, setDataNotice] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    void bootstrap();
  }, []);

  const selectedStops = useMemo(() => {
    return orderStopsForRoute(
      businesses.filter((business) => selectedIds.has(business.id)),
      startingLocation
    );
  }, [businesses, selectedIds, startingLocation]);

  const filteredBusinesses = useMemo(() => {
    const filtered = businesses.filter((business) => {
      if (businessFilter === "best") {
        return Boolean(business.bestStop);
      }
      if (businessFilter === "walkable") {
        return isWalkableStop(business);
      }
      if (businessFilter === "plazas") {
        return isPlazaStop(business);
      }
      return true;
    });

    return [...filtered].sort((a, b) => Number(Boolean(b.bestStop)) - Number(Boolean(a.bestStop)));
  }, [businesses, businessFilter]);

  const lastUnfinishedRoute = useMemo(() => {
    return [...savedRoutes]
      .filter((route) => completedCount(route.stops) < route.stops.length)
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())[0] ?? null;
  }, [savedRoutes]);

  const activePresetName = useMemo(() => {
    const sortedTypes = [...businessTypes].sort().join("|");
    return BUSINESS_TYPE_PRESETS.find((preset) => [...preset.types].sort().join("|") === sortedTypes)?.name ?? null;
  }, [businessTypes]);

  const hasUnsavedWork = selectedIds.size > 0 && !currentSession;

  async function bootstrap() {
    const [routes, settings] = await Promise.all([loadRouteSessions(), loadAppSettings()]);
    setSavedRoutes(routes.map(normalizeRouteSession));
    setState(settings.lastSelectedState || "Michigan");
    setBackendBaseUrl(settings.backendBaseUrl || DEFAULT_BACKEND_BASE_URL);
  }

  async function refreshSavedRoutes() {
    const routes = await loadRouteSessions();
    setSavedRoutes(routes.map(normalizeRouteSession));
  }

  function guardedNavigate(nextScreen: Screen, message = "Leave this route? Unsaved changes may be lost.") {
    if (hasUnsavedWork && !["results", "builder", "manual"].includes(nextScreen)) {
      Alert.alert("Leave this route?", message, [
        { text: "Stay", style: "cancel" },
        { text: "Leave", style: "destructive", onPress: () => setScreen(nextScreen) }
      ]);
      return;
    }
    setScreen(nextScreen);
  }

  function goHome() {
    guardedNavigate("start");
  }

  function startNewRoute() {
    setCurrentSession(null);
    setBusinesses([]);
    setSelectedIds(new Set());
    setExpandedStopId(null);
    setUsingDemoData(false);
    setDataNotice("");
    setRouteName("");
    setScreen("start");
  }

  function goBack() {
    if (screen === "results") {
      guardedNavigate("start");
    } else if (screen === "builder") {
      setScreen("results");
    } else if (screen === "today") {
      setScreen("builder");
    } else if (screen === "saved") {
      setScreen("start");
    } else if (screen === "manual") {
      setScreen("results");
    }
  }

  async function chooseState(nextState: string) {
    setState(nextState);
    setStatePickerOpen(false);
    await saveAppSettings({ lastSelectedState: nextState, backendBaseUrl });
  }

  async function updateBackendBaseUrl(nextUrl: string) {
    setBackendBaseUrl(nextUrl);
    await saveAppSettings({ lastSelectedState: state, backendBaseUrl: nextUrl });
  }

  function toggleBusinessType(type: string) {
    setBusinessTypes((current) =>
      current.includes(type)
        ? current.filter((item) => item !== type)
        : [...current, type]
    );
  }

  function applyPreset(types: string[]) {
    setBusinessTypes(types);
    setShowCustomBusinessTypes(false);
  }

  async function findBusinesses() {
    if (!startingLocation.trim() || !city.trim()) {
      Alert.alert("Work area needed", "Enter a starting location and city before finding businesses.");
      return;
    }
    if (!state.trim()) {
      Alert.alert("State needed", "Choose a state before finding businesses.");
      return;
    }
    if (!businessTypes.length) {
      Alert.alert("Choose business types", "Choose at least one business type.");
      return;
    }

    setIsLoading(true);
    try {
      const hiddenBusinesses = await loadHiddenBusinesses();
      const request = {
        startingLocation,
        city,
        state,
        businessTypes,
        hiddenBusinesses
      };
      let results: BusinessStop[];
      let demoMode = false;
      let notice = "";

      try {
        results = await createRealBusinessProvider(backendBaseUrl).findBusinesses(request);
      } catch (error) {
        console.warn("Real business search unavailable", error);
        results = await MockBusinessProvider.findBusinesses(request);
        demoMode = true;
        notice = "Real business search unavailable. Demo data is being shown. Phone numbers are not real.";
        Alert.alert("Demo data", notice);
      }

      setBusinesses(results);
      setSelectedIds(new Set());
      setCurrentSession(null);
      setBusinessFilter("all");
      setUsingDemoData(demoMode);
      setDataNotice(notice);
      setRouteName(defaultRouteName(city, businessTypes));
      setScreen("results");
    } finally {
      setIsLoading(false);
    }
  }

  function toggleSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function hideBusiness(stop: BusinessStop, reason = "Not Interested") {
    await saveHiddenBusiness(hiddenBusinessFromStop(stop, reason));
    setBusinesses((current) => current.filter((business) => business.id !== stop.id));
    setSelectedIds((current) => {
      const next = new Set(current);
      next.delete(stop.id);
      return next;
    });
  }

  function makeSession(stops: BusinessStop[], name = routeName): RouteSession {
    const now = nowIso();
    return {
      id: currentSession?.id || newId("route"),
      name: name.trim() || defaultRouteName(city, businessTypes),
      city,
      state,
      startingLocation,
      businessTypes,
      createdAt: currentSession?.createdAt || now,
      updatedAt: now,
      stops,
      completedCount: completedCount(stops)
    };
  }

  async function saveCurrentRoute(stops = selectedStops, showAlert = true) {
    if (!stops.length) {
      Alert.alert("No stops added", "Add at least one stop before building the route.");
      return null;
    }
    const session = makeSession(stops);
    await saveRouteSession(session);
    setCurrentSession(session);
    setRouteName(session.name);
    await refreshSavedRoutes();
    if (showAlert) {
      Alert.alert("Route saved", `${session.name} was saved with ${session.stops.length} stops.`);
    }
    return session;
  }

  async function startRoute() {
    const session = currentSession || (await saveCurrentRoute(selectedStops, false));
    if (!session) {
      return;
    }
    setCurrentSession(session);
    setScreen("today");
  }

  async function openSelectedRouteInMaps() {
    const session = currentSession || makeSession(selectedStops);
    await openRouteInGoogleMaps(session);
  }

  function requestStopStatus(stopId: string, status: StopStatus) {
    if (FOLLOW_UP_STATUSES.includes(status)) {
      setFollowUpPrompt({ stopId, status });
      setFollowUpDateDraft("");
      setFollowUpManualOpen(false);
      return;
    }
    void updateStopStatus(stopId, status);
  }

  async function saveFollowUpStatus() {
    await saveFollowUpWithDate(followUpDateDraft.trim());
  }

  async function saveFollowUpWithDate(followUpDate?: string) {
    if (!followUpPrompt) {
      return;
    }
    await updateStopStatus(followUpPrompt.stopId, followUpPrompt.status, followUpDate);
    setFollowUpPrompt(null);
    setFollowUpDateDraft("");
    setFollowUpManualOpen(false);
  }

  async function updateStopStatus(stopId: string, status: StopStatus, followUpDate?: string) {
    if (!currentSession) {
      return;
    }
    const now = nowIso();
    const readableTime = new Date().toLocaleString();
    const nextStops = currentSession.stops.map((stop) => {
      if (stop.id !== stopId) {
        return stop;
      }
      const contactAttempts = CONTACT_ATTEMPT_STATUSES.includes(status)
        ? stop.contactAttempts + 1
        : stop.contactAttempts;
      const nextNotes =
        FOLLOW_UP_STATUSES.includes(status) && !followUpDate
          ? stop.notes
            ? `${stop.notes}\nFollow-up needed: no date set`
            : "Follow-up needed: no date set"
          : stop.notes;
      const historyLine = followUpDate
        ? `${readableTime} - ${status} - follow up ${followUpDate}`
        : `${readableTime} - ${status}`;
      return {
        ...stop,
        status,
        contactAttempts,
        notes: nextNotes,
        lastContacted: status === "New" ? stop.lastContacted : now,
        nextFollowUpDate: FOLLOW_UP_STATUSES.includes(status) ? followUpDate || undefined : stop.nextFollowUpDate,
        history: [historyLine, ...stop.history].slice(0, 20)
      };
    });
    const nextSession = {
      ...currentSession,
      stops: nextStops,
      completedCount: completedCount(nextStops),
      updatedAt: now
    };
    setCurrentSession(nextSession);
    if (COMPLETED_ROUTE_STATUSES.includes(status)) {
      setExpandedStopId(null);
    }
    await saveRouteSession(nextSession);
    await refreshSavedRoutes();
  }

  async function deleteHistoryEntry(stopId: string, historyIndex: number) {
    if (!currentSession) {
      return;
    }
    Alert.alert("Remove history entry?", "This only removes the log line. Use the status buttons if the stop status also needs to change.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Remove",
        style: "destructive",
        onPress: () => {
          void (async () => {
            const now = nowIso();
            const nextStops = currentSession.stops.map((stop) => {
              if (stop.id !== stopId) {
                return stop;
              }
              return {
                ...stop,
                history: stop.history.filter((_, index) => index !== historyIndex)
              };
            });
            const nextSession = {
              ...currentSession,
              stops: nextStops,
              updatedAt: now
            };
            setCurrentSession(nextSession);
            await saveRouteSession(nextSession);
            await refreshSavedRoutes();
          })();
        }
      }
    ]);
  }

  async function openSavedRoute(session: RouteSession) {
    const normalizedSession = normalizeRouteSession(session);
    setCurrentSession(normalizedSession);
    setRouteName(normalizedSession.name);
    setStartingLocation(normalizedSession.startingLocation);
    setCity(normalizedSession.city);
    setState(normalizedSession.state || "Michigan");
    setBusinessTypes(normalizedSession.businessTypes);
    setBusinesses(normalizedSession.stops);
    setSelectedIds(new Set(normalizedSession.stops.map((stop) => stop.id)));
    setUsingDemoData(normalizedSession.stops.some((stop) => stop.source === "mock"));
    setDataNotice(normalizedSession.stops.some((stop) => stop.source === "mock") ? "Demo data — phone numbers are not real." : "");
    setExpandedStopId(null);
    setScreen("today");
  }

  async function deleteSavedRoute(id: string) {
    await deleteRouteSession(id);
    if (currentSession?.id === id) {
      setCurrentSession(null);
    }
    await refreshSavedRoutes();
  }

  function startRenameRoute(session: RouteSession) {
    setRenamingRouteId(session.id);
    setRenameDraft(session.name);
  }

  async function saveRenamedRoute(session: RouteSession) {
    const nextName = renameDraft.trim();
    if (!nextName) {
      Alert.alert("Name needed", "Enter a route name.");
      return;
    }
    await renameRouteSession(session.id, nextName);
    if (currentSession?.id === session.id) {
      const renamed = { ...currentSession, name: nextName, updatedAt: nowIso() };
      setCurrentSession(renamed);
      setRouteName(nextName);
    }
    setRenamingRouteId(null);
    setRenameDraft("");
    await refreshSavedRoutes();
  }

  function addManualStop() {
    if (!manualDraft.name.trim() || !manualDraft.address.trim()) {
      Alert.alert("Name and address needed", "Add a business name and address.");
      return;
    }
    const stop: BusinessStop = {
      id: newId("manual"),
      name: manualDraft.name.trim(),
      address: manualDraft.address.trim(),
      phone: manualDraft.phone.trim(),
      category: "Manual",
      status: "New",
      notes: manualDraft.notes.trim(),
      contactAttempts: 0,
      history: [],
      source: "manual",
      hidden: false,
      bestStop: false
    };
    setBusinesses((current) => [stop, ...current]);
    setSelectedIds((current) => new Set(current).add(stop.id));
    setManualDraft(initialManualDraft);
    setScreen("results");
  }

  function renderHeader(subtitle: string) {
    return (
      <Header
        subtitle={subtitle}
        onHome={goHome}
        onBack={screen === "start" ? undefined : goBack}
        onSavedRoutes={() => guardedNavigate("saved")}
        backLabel="Back"
      />
    );
  }

  function renderStatePicker() {
    return (
      <Modal visible={statePickerOpen} animationType="slide">
        <SafeAreaView style={styles.safeArea}>
          <ScrollView contentContainerStyle={styles.page}>
            <Text style={styles.appName}>Choose State</Text>
            {US_STATES.map((item) => (
              <TouchableOpacity
                key={item}
                style={[styles.listOption, item === state && styles.selectedCard]}
                onPress={() => void chooseState(item)}
              >
                <Text style={styles.listOptionText}>{item}</Text>
              </TouchableOpacity>
            ))}
            <SecondaryButton label="Close" onPress={() => setStatePickerOpen(false)} />
          </ScrollView>
        </SafeAreaView>
      </Modal>
    );
  }

  function renderBusinessTypePicker() {
    return (
      <Modal visible={businessTypesOpen} animationType="slide">
        <SafeAreaView style={styles.safeArea}>
          <ScrollView contentContainerStyle={styles.page}>
            <Text style={styles.appName}>Business Types</Text>
            <Text style={styles.screenSubtitle}>Pick a route style first. Customize only if needed.</Text>
            {BUSINESS_TYPE_PRESETS.map((preset) => (
              <TouchableOpacity
                key={preset.name}
                style={[styles.presetCard, activePresetName === preset.name && styles.presetCardActive]}
                onPress={() => applyPreset(preset.types)}
              >
                <Text style={styles.presetTitle}>{activePresetName === preset.name ? "✓ " : ""}{preset.name}</Text>
                <Text style={styles.presetMeta}>{preset.types.slice(0, 3).join(", ")}{preset.types.length > 3 ? "..." : ""}</Text>
              </TouchableOpacity>
            ))}
            <SecondaryButton
              label={showCustomBusinessTypes ? "Hide custom business types" : "Customize business types"}
              onPress={() => setShowCustomBusinessTypes((current) => !current)}
            />
            {showCustomBusinessTypes ? (
              <>
                <Text style={styles.sectionLabel}>{businessTypes.length} categories selected</Text>
                {BUSINESS_TYPES.map((type) => (
                  <TouchableOpacity
                    key={type}
                    style={[styles.listOption, businessTypes.includes(type) && styles.listOptionActive]}
                    onPress={() => toggleBusinessType(type)}
                  >
                    <Text style={styles.listOptionText}>{businessTypes.includes(type) ? "✓ " : ""}{type}</Text>
                  </TouchableOpacity>
                ))}
              </>
            ) : null}
            <PrimaryButton label="Done" onPress={() => setBusinessTypesOpen(false)} />
          </ScrollView>
        </SafeAreaView>
      </Modal>
    );
  }

  function renderFollowUpPrompt() {
    return (
      <Modal visible={followUpPrompt !== null} transparent animationType="fade">
        <View style={styles.modalShade}>
          <View style={styles.modalCard}>
            <Text style={styles.cardTitle}>Follow-up date</Text>
            <Text style={styles.meta}>Pick a quick reminder, or save it without a date.</Text>
            <View style={styles.buttonGrid}>
              <TouchableOpacity style={styles.quickDateButton} onPress={() => void saveFollowUpWithDate(isoDateDaysFromNow(1))}>
                <Text style={styles.quickActionText}>Tomorrow</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.quickDateButton} onPress={() => void saveFollowUpWithDate(isoDateDaysFromNow(3))}>
                <Text style={styles.quickActionText}>3 Days</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.quickDateButton} onPress={() => void saveFollowUpWithDate(isoDateDaysFromNow(7))}>
                <Text style={styles.quickActionText}>1 Week</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.quickDateButton} onPress={() => void saveFollowUpWithDate()}>
                <Text style={styles.quickActionText}>No Date Yet</Text>
              </TouchableOpacity>
            </View>
            <SecondaryButton
              label={followUpManualOpen ? "Hide Manual Date" : "Manual Date"}
              onPress={() => setFollowUpManualOpen((current) => !current)}
            />
            {followUpManualOpen ? (
              <>
                <TextInput
                  style={styles.input}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={theme.colors.faint}
                  value={followUpDateDraft}
                  onChangeText={setFollowUpDateDraft}
                />
                <PrimaryButton label="Save Manual Date" onPress={() => void saveFollowUpStatus()} />
              </>
            ) : null}
            <SecondaryButton
              label="Cancel"
              onPress={() => {
                setFollowUpPrompt(null);
                setFollowUpManualOpen(false);
              }}
            />
          </View>
        </View>
      </Modal>
    );
  }

  function renderRoutePartButtons(session: RouteSession) {
    const parts = getGoogleMapsRouteParts(session);
    if (parts.length <= 1) {
      return null;
    }
    return (
      <View style={styles.routePartsCard}>
        <Text style={styles.cardTitle}>Google Maps route parts</Text>
        <Text style={styles.meta}>
          Google Maps works best with 10 stops at a time. Open each part when you are ready for that section.
        </Text>
        <View style={styles.buttonGrid}>
          {parts.map((part) => (
            <TouchableOpacity
              key={part.index}
              style={styles.routePartButton}
              onPress={() => void openRoutePartInGoogleMaps(session, part.index)}
            >
              <Text style={styles.outcomeButtonText}>Part {part.index + 1}</Text>
              <Text style={styles.routePartText}>{part.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>
    );
  }

  function renderBusinessFilters() {
    const filters: Array<{ key: BusinessFilter; label: string }> = [
      { key: "all", label: "All" },
      { key: "best", label: "Best Stops" },
      { key: "walkable", label: "Walkable" },
      { key: "plazas", label: "Plazas" }
    ];

    return (
      <View style={styles.filterBar}>
        {filters.map((filter) => (
          <TouchableOpacity
            key={filter.key}
            style={[styles.filterChip, businessFilter === filter.key && styles.filterChipActive]}
            onPress={() => setBusinessFilter(filter.key)}
          >
            <Text style={styles.filterChipText}>{filter.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    );
  }

  function renderRouteProgress(session: RouteSession, followUps: number, interested: number) {
    const completed = completedCount(session.stops);
    const percent = session.stops.length ? Math.round((completed / session.stops.length) * 100) : 0;
    return (
      <View style={styles.progressCard}>
        <View style={styles.progressHeader}>
          <Text style={styles.progressTitle}>{percent}% complete</Text>
          <Text style={styles.progressMeta}>{completed}/{session.stops.length} stops</Text>
        </View>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${percent}%` }]} />
        </View>
        <View style={styles.progressStats}>
          <Text style={styles.progressStat}>{followUps} follow-ups</Text>
          <Text style={styles.progressStat}>{interested} interested</Text>
        </View>
      </View>
    );
  }

  const content = (() => {
    if (screen === "start") {
      return (
        <ScrollView contentContainerStyle={styles.page}>
          {renderHeader("Where are we working today?")}
          {lastUnfinishedRoute ? (
            <View style={styles.resumeCard}>
              <Text style={styles.cardTitle}>Resume Last Route</Text>
              <Text style={styles.meta}>{lastUnfinishedRoute.name}</Text>
              <Text style={styles.meta}>
                {lastUnfinishedRoute.city}, {lastUnfinishedRoute.state || "Michigan"} - {completedCount(lastUnfinishedRoute.stops)}/{lastUnfinishedRoute.stops.length} done
              </Text>
              <PrimaryButton label="Resume Last Route" onPress={() => void openSavedRoute(lastUnfinishedRoute)} />
              <SecondaryButton label="Start New Route" onPress={startNewRoute} />
            </View>
          ) : null}
          <View style={styles.heroCard}>
            <Text style={styles.heroTitle}>Where are we working today?</Text>
            <Text style={styles.heroSubtitle}>Pick an area, choose the businesses you want to hit, and build your route.</Text>
            <FieldLabel>Start from</FieldLabel>
            <TextInput
              style={styles.input}
              placeholder="Starting location"
              placeholderTextColor={theme.colors.faint}
              value={startingLocation}
              onChangeText={setStartingLocation}
            />
            <FieldLabel>Work area</FieldLabel>
            <TextInput
              style={styles.input}
              placeholder="City / area"
              placeholderTextColor={theme.colors.faint}
              value={city}
              onChangeText={setCity}
            />
            <FieldLabel>State</FieldLabel>
            <SecondaryButton label={state || "Choose State"} onPress={() => setStatePickerOpen(true)} />
            <FieldLabel>Business types</FieldLabel>
            <SecondaryButton
              label={activePresetName || `${businessTypes.length} types selected`}
              onPress={() => setBusinessTypesOpen(true)}
            />
            <Text style={styles.meta}>{businessTypes.slice(0, 4).join(", ")}{businessTypes.length > 4 ? "..." : ""}</Text>
            <FieldLabel>Real data backend</FieldLabel>
            <TextInput
              style={styles.input}
              placeholder="http://192.168.1.25:3001"
              placeholderTextColor={theme.colors.faint}
              value={backendBaseUrl}
              onChangeText={(value) => void updateBackendBaseUrl(value)}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <Text style={styles.meta}>Use your computer's local IP while the backend is running. If unavailable, RouteForge uses demo data.</Text>
            <PrimaryButton label={isLoading ? "Finding..." : "Find Stops"} onPress={findBusinesses} disabled={isLoading} />
            <SecondaryButton label="Open Saved Route" onPress={() => setScreen("saved")} />
          </View>
        </ScrollView>
      );
    }

    if (screen === "results") {
      return (
        <ScrollView contentContainerStyle={styles.page}>
          {renderHeader(`${businesses.length} businesses found. ${selectedIds.size} stops added.`)}
          {dataNotice ? <Text style={usingDemoData ? styles.demoNotice : styles.helperText}>{dataNotice}</Text> : null}
          <Text style={styles.helperText}>Add stops you want to work today.</Text>
          <View style={styles.actionRow}>
            <PrimaryButton label="Build Route" onPress={() => setScreen("builder")} disabled={!selectedIds.size} />
            <SecondaryButton label="Add Manually" onPress={() => setScreen("manual")} />
          </View>
          {renderBusinessFilters()}
          <Text style={styles.meta}>{filteredBusinesses.length} shown</Text>
          {filteredBusinesses.map((business) => (
            <View key={business.id} style={[styles.card, selectedIds.has(business.id) && styles.selectedCard]}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>{business.name}</Text>
                <View style={styles.badgeRow}>
                  {selectedIds.has(business.id) ? <Text style={styles.selectedRouteBadge}>✓ In Route</Text> : null}
                  {business.source === "mock" ? <Text style={styles.demoBadge}>Demo Data</Text> : null}
                  {business.bestStop ? <Text style={styles.bestBadge}>Best Stop</Text> : null}
                </View>
              </View>
              <Text style={styles.meta}>{business.address}</Text>
              <Text style={styles.meta}>{business.phone || "Phone not listed"}</Text>
              <Text style={styles.meta}>{business.category}</Text>
              <View style={styles.actionRow}>
                <SecondaryButton
                  label={selectedIds.has(business.id) ? "Remove" : "Add Stop"}
                  onPress={() => toggleSelected(business.id)}
                  danger={selectedIds.has(business.id)}
                />
                <SecondaryButton label="Hide / Not Interested" onPress={() => void hideBusiness(business)} danger />
              </View>
            </View>
          ))}
        </ScrollView>
      );
    }

    if (screen === "builder") {
      const mapSession = currentSession || makeSession(selectedStops);
      return (
        <ScrollView contentContainerStyle={styles.page}>
          {renderHeader(`${selectedStops.length} stops ready.`)}
          <Text style={styles.helperText}>Save this route, then open it in Google Maps.</Text>
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Save this route</Text>
            <TextInput
              style={styles.input}
              placeholder="Route name"
              placeholderTextColor={theme.colors.faint}
              value={routeName}
              onChangeText={setRouteName}
            />
            <PrimaryButton label="Save Route" onPress={() => void saveCurrentRoute()} />
            <SecondaryButton label="Open Full Route in Google Maps" onPress={() => void openSelectedRouteInMaps()} />
            <PrimaryButton label="Start Route" onPress={() => void startRoute()} />
          </View>
          {selectedStops.length ? renderRoutePartButtons(mapSession) : null}
          {selectedStops.map((stop) => (
            <View key={stop.id} style={styles.compactStop}>
              <Text style={styles.stopNumber}>Stop {stop.routeStopNumber}</Text>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>{stop.name}</Text>
                {stop.source === "mock" ? <Text style={styles.demoBadge}>Demo Data</Text> : null}
              </View>
              <Text style={styles.meta}>{stop.address}</Text>
              <Text style={styles.meta}>{stop.phone || "Phone not listed"} - {stop.status}</Text>
            </View>
          ))}
        </ScrollView>
      );
    }

    if (screen === "today") {
      const session = currentSession;
      const followUps = session?.stops.filter((stop) => stop.status === "Need Follow-Up" || stop.nextFollowUpDate).length ?? 0;
      const interested = session?.stops.filter((stop) => stop.status === "Interested").length ?? 0;
      const nextStopId = session?.stops.find((stop) => !isCompletedStop(stop))?.id ?? null;
      return (
        <ScrollView contentContainerStyle={styles.page}>
          {renderHeader(
            session
              ? `${session.completedCount}/${session.stops.length} completed - ${followUps} follow-ups - ${interested} interested`
              : "No active route."
          )}
          {!session ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>No active route</Text>
              <PrimaryButton label="Go to Start" onPress={() => setScreen("start")} />
            </View>
          ) : (
            <>
              <Text style={styles.routeNameText}>{session.name}</Text>
              <Text style={styles.helperText}>Tap an outcome after each stop.</Text>
              {renderRouteProgress(session, followUps, interested)}
              <PrimaryButton label="Open Full Route in Google Maps" onPress={() => void openRouteInGoogleMaps(session)} />
              {renderRoutePartButtons(session)}
              {session.stops.map((stop) => {
                const expanded = expandedStopId === stop.id;
                const completed = isCompletedStop(stop) && !expanded;
                if (completed) {
                  return (
                    <View key={stop.id} style={styles.completedStopCard}>
                      <View style={styles.stopTopLine}>
                        <Text style={styles.stopNumber}>Stop {stop.routeStopNumber}</Text>
                        <Text style={styles.completedBadge}>{statusLabel(stop.status)}</Text>
                      </View>
                      <Text style={styles.completedStopTitle}>{stop.name}</Text>
                      <Text style={styles.compactMeta}>{stop.address}</Text>
                      <View style={styles.actionRow}>
                        <SecondaryButton label="Change" onPress={() => setExpandedStopId(stop.id)} />
                        <SecondaryButton label="Maps" onPress={() => void openStopInGoogleMaps(stop)} />
                      </View>
                    </View>
                  );
                }

                return (
                  <View key={stop.id} style={[styles.routeCard, stop.id === nextStopId && styles.nextStopCard]}>
                    <View style={styles.stopTopLine}>
                      <Text style={styles.stopNumber}>Stop {stop.routeStopNumber}</Text>
                      <View style={styles.badgeRow}>
                        {stop.source === "mock" ? <Text style={styles.demoBadge}>Demo Data</Text> : null}
                        {stop.id === nextStopId ? <Text style={styles.nextStopBadge}>Next Stop</Text> : null}
                        <Text style={styles.statusPill}>{statusLabel(stop.status)}</Text>
                      </View>
                    </View>
                    <Text style={styles.routeBusinessName}>{stop.name}</Text>
                    <Text style={styles.routeAddress}>{stop.address}</Text>
                    <View style={styles.primaryActionGrid}>
                      {PRIMARY_ROUTE_STATUSES.map((status) => (
                        <TouchableOpacity
                          key={status}
                          style={[styles.quickActionButton, stop.status === status && styles.quickActionButtonActive]}
                          onPress={() => requestStopStatus(stop.id, status)}
                        >
                          <Text style={styles.quickActionText}>{statusLabel(status)}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                    <Text style={styles.lowEmphasisText}>{stop.phone || "Phone not listed"}</Text>
                    {stop.nextFollowUpDate ? <Text style={styles.followUpText}>Follow-up: {stop.nextFollowUpDate}</Text> : null}
                    {FOLLOW_UP_STATUSES.includes(stop.status) && !stop.nextFollowUpDate ? (
                      <Text style={styles.followUpText}>Follow-up needed: no date set</Text>
                    ) : null}
                    <View style={styles.actionRow}>
                      <SecondaryButton label="Open in Google Maps" onPress={() => void openStopInGoogleMaps(stop)} />
                      <SecondaryButton
                        label={expanded ? "Hide More" : "More"}
                        onPress={() => setExpandedStopId(expanded ? null : stop.id)}
                      />
                    </View>
                    {expanded ? (
                      <View style={styles.expandedArea}>
                        <Text style={styles.sectionLabel}>More actions</Text>
                        <View style={styles.buttonGrid}>
                          {SECONDARY_ROUTE_STATUSES.map((status) => (
                            <TouchableOpacity
                              key={status}
                              style={[styles.outcomeButton, stop.status === status && styles.outcomeButtonActive]}
                              onPress={() => requestStopStatus(stop.id, status)}
                            >
                              <Text style={styles.outcomeButtonText}>{statusLabel(status)}</Text>
                            </TouchableOpacity>
                          ))}
                        </View>
                        <Text style={styles.meta}>Category: {stop.category}</Text>
                        <Text style={styles.notesText}>Notes: {stop.notes || "None yet"}</Text>
                        <Text style={styles.meta}>Attempts: {stop.contactAttempts}</Text>
                        <Text style={styles.sectionLabel}>History</Text>
                        {stop.history.length ? (
                          stop.history.map((entry, index) => (
                            <View key={`${entry}-${index}`} style={styles.historyRow}>
                              <Text style={styles.historyText}>{entry}</Text>
                              <TouchableOpacity
                                style={styles.removeHistoryButton}
                                onPress={() => void deleteHistoryEntry(stop.id, index)}
                              >
                                <Text style={styles.removeHistoryText}>Remove</Text>
                              </TouchableOpacity>
                            </View>
                          ))
                        ) : (
                          <Text style={styles.historyText}>No history yet.</Text>
                        )}
                      </View>
                    ) : null}
                  </View>
                );
              })}
            </>
          )}
        </ScrollView>
      );
    }

    if (screen === "saved") {
      return (
        <ScrollView contentContainerStyle={styles.page}>
          {renderHeader(`${savedRoutes.length} saved routes.`)}
          <PrimaryButton label="Start New Route" onPress={() => setScreen("start")} />
          {savedRoutes.map((route) => (
            <View key={route.id} style={styles.card}>
              <Text style={styles.cardTitle}>{route.name}</Text>
              <Text style={styles.meta}>{route.city}, {route.state || "Michigan"} - {shortDate(route.createdAt)}</Text>
              <Text style={styles.meta}>{route.stops.length} stops - {route.completedCount} completed</Text>
              {renamingRouteId === route.id ? (
                <View style={styles.renameBox}>
                  <TextInput
                    style={styles.input}
                    placeholder="Route name"
                    placeholderTextColor={theme.colors.faint}
                    value={renameDraft}
                    onChangeText={setRenameDraft}
                  />
                  <View style={styles.actionRow}>
                    <SecondaryButton label="Save Name" onPress={() => void saveRenamedRoute(route)} />
                    <SecondaryButton label="Cancel" onPress={() => setRenamingRouteId(null)} />
                  </View>
                </View>
              ) : null}
              <View style={styles.actionRow}>
                <SecondaryButton label="Continue" onPress={() => void openSavedRoute(route)} />
                <SecondaryButton label="Rename" onPress={() => startRenameRoute(route)} />
                <SecondaryButton label="Delete" onPress={() => void deleteSavedRoute(route.id)} danger />
              </View>
            </View>
          ))}
        </ScrollView>
      );
    }

    return (
      <ScrollView contentContainerStyle={styles.page}>
        {renderHeader("Add a business you found in the field.")}
        <View style={styles.card}>
          <TextInput
            style={styles.input}
            placeholder="Business name"
            placeholderTextColor={theme.colors.faint}
            value={manualDraft.name}
            onChangeText={(name) => setManualDraft((current) => ({ ...current, name }))}
          />
          <TextInput
            style={styles.input}
            placeholder="Address"
            placeholderTextColor={theme.colors.faint}
            value={manualDraft.address}
            onChangeText={(address) => setManualDraft((current) => ({ ...current, address }))}
          />
          <TextInput
            style={styles.input}
            placeholder="Phone"
            placeholderTextColor={theme.colors.faint}
            keyboardType="phone-pad"
            value={manualDraft.phone}
            onChangeText={(phone) => setManualDraft((current) => ({ ...current, phone }))}
          />
          <TextInput
            style={[styles.input, styles.notesInput]}
            placeholder="Notes"
            placeholderTextColor={theme.colors.faint}
            value={manualDraft.notes}
            onChangeText={(notes) => setManualDraft((current) => ({ ...current, notes }))}
            multiline
          />
          <PrimaryButton label="Add Stop" onPress={addManualStop} />
          <SecondaryButton label="Cancel" onPress={() => setScreen("results")} />
        </View>
      </ScrollView>
    );
  })();

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />
      {content}
      {renderStatePicker()}
      {renderBusinessTypePicker()}
      {renderFollowUpPrompt()}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: theme.colors.background
  },
  page: {
    padding: theme.spacing.page,
    gap: theme.spacing.gap,
    paddingBottom: 40
  },
  header: {
    gap: 8,
    marginBottom: 8,
    paddingTop: 18 + (RNStatusBar.currentHeight ?? 0)
  },
  headerActions: {
    flexDirection: "row",
    gap: 8,
    justifyContent: "space-between",
    minHeight: 48,
    alignItems: "center",
    marginBottom: 6
  },
  appName: {
    color: theme.colors.text,
    fontSize: 34,
    fontWeight: "900"
  },
  tagline: {
    color: theme.colors.muted,
    fontSize: 13,
    fontWeight: "600"
  },
  screenSubtitle: {
    color: theme.colors.primary,
    fontSize: 16,
    fontWeight: "800"
  },
  headerButton: {
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 44,
    justifyContent: "center"
  },
  headerButtonText: {
    color: theme.colors.text,
    fontWeight: "800"
  },
  card: {
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: theme.spacing.card,
    gap: 12
  },
  heroCard: {
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.primary,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 18,
    gap: 14
  },
  heroTitle: {
    color: theme.colors.text,
    fontSize: 28,
    fontWeight: "900",
    lineHeight: 34
  },
  heroSubtitle: {
    color: theme.colors.muted,
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700"
  },
  resumeCard: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.primary,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 16,
    gap: 12
  },
  selectedCard: {
    borderColor: theme.colors.primary,
    borderWidth: 2
  },
  routeCard: {
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 18,
    gap: 12
  },
  completedStopCard: {
    backgroundColor: theme.colors.panel,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 12,
    gap: 7,
    opacity: 0.78
  },
  routePartsCard: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.primary,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 16,
    gap: 10
  },
  compactStop: {
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.card,
    padding: 14,
    gap: 6
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10
  },
  helperText: {
    color: theme.colors.muted,
    fontSize: 15,
    lineHeight: 21,
    fontWeight: "800"
  },
  demoNotice: {
    color: theme.colors.warning,
    backgroundColor: theme.colors.panel,
    borderColor: theme.colors.warning,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    padding: 12,
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "900"
  },
  demoBadge: {
    color: theme.colors.background,
    backgroundColor: theme.colors.warning,
    borderRadius: theme.radius.chip,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "900"
  },
  stopTopLine: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10
  },
  badgeRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    gap: 6,
    flexShrink: 1
  },
  cardTitle: {
    color: theme.colors.text,
    fontSize: 20,
    fontWeight: "900",
    flexShrink: 1
  },
  sectionLabel: {
    color: theme.colors.muted,
    fontWeight: "800",
    marginTop: 4
  },
  routeNameText: {
    color: theme.colors.text,
    fontSize: 18,
    fontWeight: "900"
  },
  routeBusinessName: {
    color: theme.colors.text,
    fontSize: 24,
    fontWeight: "900",
    lineHeight: 30
  },
  routeAddress: {
    color: theme.colors.muted,
    fontSize: 17,
    lineHeight: 24,
    fontWeight: "700"
  },
  completedStopTitle: {
    color: theme.colors.text,
    fontSize: 17,
    fontWeight: "900"
  },
  compactMeta: {
    color: theme.colors.faint,
    fontSize: 13,
    lineHeight: 18
  },
  input: {
    backgroundColor: theme.colors.panel,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    color: theme.colors.text,
    fontSize: 16,
    padding: 14
  },
  notesInput: {
    minHeight: 100,
    textAlignVertical: "top"
  },
  renameBox: {
    gap: 10
  },
  primaryButton: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.button,
    paddingVertical: 15,
    paddingHorizontal: 16,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 52
  },
  disabledButton: {
    opacity: 0.45
  },
  primaryButtonText: {
    color: theme.colors.background,
    fontWeight: "900",
    fontSize: 16
  },
  secondaryButton: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 46
  },
  dangerButton: {
    borderColor: theme.colors.danger
  },
  secondaryButtonText: {
    color: theme.colors.text,
    fontWeight: "800"
  },
  actionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    alignItems: "center"
  },
  meta: {
    color: theme.colors.muted,
    fontSize: 15,
    lineHeight: 21
  },
  bestBadge: {
    color: theme.colors.background,
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.chip,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "900"
  },
  selectedRouteBadge: {
    color: theme.colors.background,
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.chip,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "900"
  },
  stopNumber: {
    color: theme.colors.primary,
    fontWeight: "900",
    textTransform: "uppercase",
    letterSpacing: 0.5
  },
  statusText: {
    color: theme.colors.primary,
    fontWeight: "900",
    fontSize: 16
  },
  statusPill: {
    color: theme.colors.text,
    backgroundColor: theme.colors.cardSoft,
    borderRadius: theme.radius.chip,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "900"
  },
  completedBadge: {
    color: theme.colors.background,
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.chip,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "900"
  },
  nextStopCard: {
    borderColor: theme.colors.primary,
    borderWidth: 2
  },
  nextStopBadge: {
    color: theme.colors.background,
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.chip,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "900"
  },
  followUpText: {
    color: theme.colors.warning,
    fontWeight: "900",
    fontSize: 14
  },
  lowEmphasisText: {
    color: theme.colors.faint,
    fontSize: 14,
    fontWeight: "700"
  },
  notesText: {
    color: theme.colors.text,
    fontSize: 15,
    lineHeight: 21
  },
  tapHint: {
    color: theme.colors.faint,
    fontWeight: "700"
  },
  expandedArea: {
    gap: 10,
    borderTopColor: theme.colors.border,
    borderTopWidth: 1,
    paddingTop: 10
  },
  buttonGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  primaryActionGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10
  },
  quickActionButton: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingHorizontal: 12,
    paddingVertical: 14,
    minHeight: 52,
    minWidth: 132,
    alignItems: "center",
    justifyContent: "center",
    flexGrow: 1
  },
  quickDateButton: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.primary,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingHorizontal: 12,
    paddingVertical: 14,
    minHeight: 52,
    minWidth: 130,
    alignItems: "center",
    justifyContent: "center",
    flexGrow: 1
  },
  quickActionButtonActive: {
    backgroundColor: theme.colors.primaryDark,
    borderColor: theme.colors.primary
  },
  quickActionText: {
    color: theme.colors.text,
    fontWeight: "900",
    fontSize: 15
  },
  outcomeButton: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingHorizontal: 10,
    paddingVertical: 10
  },
  outcomeButtonActive: {
    backgroundColor: theme.colors.primaryDark,
    borderColor: theme.colors.primary
  },
  outcomeButtonText: {
    color: theme.colors.text,
    fontWeight: "800"
  },
  routePartButton: {
    backgroundColor: theme.colors.primaryDark,
    borderColor: theme.colors.primary,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingHorizontal: 12,
    paddingVertical: 10,
    minWidth: 118,
    gap: 3
  },
  routePartText: {
    color: theme.colors.muted,
    fontSize: 12,
    fontWeight: "700"
  },
  presetCard: {
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 16,
    gap: 6
  },
  presetCardActive: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.primary,
    borderWidth: 2
  },
  presetTitle: {
    color: theme.colors.text,
    fontSize: 18,
    fontWeight: "900"
  },
  presetMeta: {
    color: theme.colors.muted,
    fontSize: 13,
    lineHeight: 18,
    fontWeight: "700"
  },
  filterBar: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  filterChip: {
    backgroundColor: theme.colors.cardSoft,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.chip,
    paddingHorizontal: 12,
    paddingVertical: 9
  },
  filterChipActive: {
    backgroundColor: theme.colors.primaryDark,
    borderColor: theme.colors.primary
  },
  filterChipText: {
    color: theme.colors.text,
    fontWeight: "800",
    fontSize: 13
  },
  progressCard: {
    backgroundColor: theme.colors.cardSoft,
    borderRadius: theme.radius.card,
    padding: 14,
    gap: 10
  },
  progressHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10
  },
  progressTitle: {
    color: theme.colors.text,
    fontWeight: "900",
    fontSize: 20
  },
  progressMeta: {
    color: theme.colors.muted,
    fontWeight: "800"
  },
  progressTrack: {
    height: 10,
    borderRadius: theme.radius.chip,
    backgroundColor: theme.colors.panel,
    overflow: "hidden"
  },
  progressFill: {
    height: "100%",
    borderRadius: theme.radius.chip,
    backgroundColor: theme.colors.primary
  },
  progressStats: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  progressStat: {
    color: theme.colors.faint,
    fontWeight: "800"
  },
  historyRow: {
    backgroundColor: theme.colors.panel,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    padding: 10,
    gap: 8
  },
  historyText: {
    color: theme.colors.muted,
    fontSize: 13,
    lineHeight: 18
  },
  removeHistoryButton: {
    alignSelf: "flex-start",
    borderColor: theme.colors.danger,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    paddingHorizontal: 10,
    paddingVertical: 6
  },
  removeHistoryText: {
    color: theme.colors.danger,
    fontWeight: "900",
    fontSize: 12
  },
  listOption: {
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    padding: 14
  },
  listOptionActive: {
    borderColor: theme.colors.primary,
    backgroundColor: theme.colors.cardSoft
  },
  listOptionText: {
    color: theme.colors.text,
    fontWeight: "800",
    fontSize: 16
  },
  savedMiniRow: {
    backgroundColor: theme.colors.panel,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.button,
    padding: 12,
    gap: 4
  },
  savedMiniTitle: {
    color: theme.colors.text,
    fontWeight: "900",
    fontSize: 16
  },
  modalShade: {
    flex: 1,
    backgroundColor: "rgba(15, 23, 42, 0.82)",
    justifyContent: "center",
    padding: theme.spacing.page
  },
  modalCard: {
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radius.card,
    padding: 18,
    gap: 12
  }
});
