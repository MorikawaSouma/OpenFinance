import { useSyncExternalStore } from "react";

export type DebugSnapshot = {
  navigationType: string;
  routeChangeCount: number;
  lastRouteChangeAt: string | null;
  beforeUnloadCount: number;
  visibilityHiddenCount: number;
  componentMounts: Record<string, number>;
  componentUnmounts: Record<string, number>;
  renderCount: Record<string, number>;
  avgRenderMs: Record<string, number>;
  sse: {
    openCount: number;
    closeCount: number;
    errorCount: number;
    reconnectCount: number;
    lastConnectedAt: string | null;
    lastDisconnectedAt: string | null;
    lastErrorAt: string | null;
    reconnectDelaysMs: number[];
  };
  stateUpdateCount: Record<string, number>;
  lastUpdatedAt: string | null;
};

declare global {
  interface Window {
    __OF_DEBUG__?: DebugSnapshot;
  }
}

const listeners = new Set<() => void>();

const snapshot: DebugSnapshot = {
  navigationType: "unknown",
  routeChangeCount: 0,
  lastRouteChangeAt: null,
  beforeUnloadCount: 0,
  visibilityHiddenCount: 0,
  componentMounts: {},
  componentUnmounts: {},
  renderCount: {},
  avgRenderMs: {},
  sse: {
    openCount: 0,
    closeCount: 0,
    errorCount: 0,
    reconnectCount: 0,
    lastConnectedAt: null,
    lastDisconnectedAt: null,
    lastErrorAt: null,
    reconnectDelaysMs: [],
  },
  stateUpdateCount: {},
  lastUpdatedAt: null,
};

function nowIso() {
  return new Date().toISOString();
}

function publish() {
  snapshot.lastUpdatedAt = nowIso();
  if (typeof window !== "undefined") {
    window.__OF_DEBUG__ = getSnapshot();
  }
  for (const listener of listeners) {
    listener();
  }
}

function bumpCounter(target: Record<string, number>, key: string, amount = 1) {
  target[key] = (target[key] ?? 0) + amount;
}

function detectNavigationType() {
  if (typeof window === "undefined" || typeof performance === "undefined") return;
  const [entry] = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[];
  if (entry?.type) {
    snapshot.navigationType = entry.type;
  }
}

detectNavigationType();

export function recordRouteChange(pathname: string) {
  snapshot.routeChangeCount += 1;
  snapshot.lastRouteChangeAt = `${nowIso()} ${pathname}`;
  publish();
}

export function recordBeforeUnload() {
  snapshot.beforeUnloadCount += 1;
  publish();
}

export function recordVisibilityChange(hidden: boolean) {
  if (hidden) {
    snapshot.visibilityHiddenCount += 1;
    publish();
  }
}

export function recordComponentMount(componentName: string) {
  bumpCounter(snapshot.componentMounts, componentName);
  publish();
}

export function recordComponentUnmount(componentName: string) {
  bumpCounter(snapshot.componentUnmounts, componentName);
  publish();
}

export function recordRender(componentName: string, elapsedMs: number) {
  bumpCounter(snapshot.renderCount, componentName);
  const prevCount = snapshot.renderCount[componentName];
  const prevAvg = snapshot.avgRenderMs[componentName] ?? 0;
  const nextAvg = prevCount <= 1 ? elapsedMs : (prevAvg * (prevCount - 1) + elapsedMs) / prevCount;
  snapshot.avgRenderMs[componentName] = Number(nextAvg.toFixed(3));
  publish();
}

export function recordStateUpdate(key: string) {
  bumpCounter(snapshot.stateUpdateCount, key);
  publish();
}

export function recordSseOpen() {
  snapshot.sse.openCount += 1;
  snapshot.sse.lastConnectedAt = nowIso();
  publish();
}

export function recordSseClose() {
  snapshot.sse.closeCount += 1;
  snapshot.sse.lastDisconnectedAt = nowIso();
  publish();
}

export function recordSseError() {
  snapshot.sse.errorCount += 1;
  snapshot.sse.lastErrorAt = nowIso();
  publish();
}

export function recordSseReconnect(delayMs: number) {
  snapshot.sse.reconnectCount += 1;
  snapshot.sse.reconnectDelaysMs = [...snapshot.sse.reconnectDelaysMs.slice(-19), delayMs];
  publish();
}

export function resetDebugSnapshot() {
  snapshot.routeChangeCount = 0;
  snapshot.lastRouteChangeAt = null;
  snapshot.beforeUnloadCount = 0;
  snapshot.visibilityHiddenCount = 0;
  snapshot.componentMounts = {};
  snapshot.componentUnmounts = {};
  snapshot.renderCount = {};
  snapshot.avgRenderMs = {};
  snapshot.sse = {
    openCount: 0,
    closeCount: 0,
    errorCount: 0,
    reconnectCount: 0,
    lastConnectedAt: null,
    lastDisconnectedAt: null,
    lastErrorAt: null,
    reconnectDelaysMs: [],
  };
  snapshot.stateUpdateCount = {};
  detectNavigationType();
  publish();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): DebugSnapshot {
  return {
    ...snapshot,
    componentMounts: { ...snapshot.componentMounts },
    componentUnmounts: { ...snapshot.componentUnmounts },
    renderCount: { ...snapshot.renderCount },
    avgRenderMs: { ...snapshot.avgRenderMs },
    stateUpdateCount: { ...snapshot.stateUpdateCount },
    sse: {
      ...snapshot.sse,
      reconnectDelaysMs: [...snapshot.sse.reconnectDelaysMs],
    },
  };
}

export function useDebugSnapshot() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
