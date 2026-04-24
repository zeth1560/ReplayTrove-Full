import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import {
  CURRENT_SCHEMA_VERSION,
  migrateConfigDocument,
  validateConfig,
  defaultConfig,
} from "@replaytrove/config";

const API_PORT = Number(process.env.REPLAYTROVE_CONTROL_CENTER_API_PORT || 4311);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const SETTINGS_PATH = process.env.REPLAYTROVE_SETTINGS_FILE
  ? path.resolve(process.env.REPLAYTROVE_SETTINGS_FILE)
  : path.resolve(ROOT, "config", "settings.json");
const SCOREBOARD_SAFE_RELOAD_STATUS_PATH = path.resolve(
  ROOT,
  "scoreboard",
  "reload_safe_settings_status.json",
);
const REPLAY_PIPELINE_LOG_PATH = path.resolve(
  ROOT,
  "state",
  "save_replay_and_trigger_log.txt",
);
const LEGACY_COMMANDS_ROOT = path.resolve(ROOT, "commands");
const LAUNCHER_OWNER_LEASE_PATH = path.resolve(
  ROOT,
  "launcher",
  "supervision_owner_lease.json",
);
const LAUNCHER_SUPERVISION_STATUS_PATH = path.resolve(
  ROOT,
  "launcher",
  "supervision_status.json",
);
const LAUNCHER_SUPERVISION_DESIRED_STATE_PATH = path.resolve(
  ROOT,
  "launcher",
  "supervision_desired_state.json",
);

const SUPERVISION_MANAGED_COMPONENTS = [
  "worker",
  "scoreboard",
  "obs",
  "encoder_watchdog",
];

/** Path only: strips ?query, #hash, trailing slash; handles absolute request-URIs some clients send. */
function requestPathname(url) {
  const raw = typeof url === "string" && url.length > 0 ? url : "/";
  let pathPart = raw;
  if (!raw.startsWith("/")) {
    try {
      pathPart = new URL(raw).pathname || "/";
    } catch {
      const q0 = raw.indexOf("?");
      pathPart = q0 === -1 ? raw : raw.slice(0, q0);
    }
  } else {
    const q = raw.indexOf("?");
    pathPart = q === -1 ? raw : raw.slice(0, q);
  }
  const h = pathPart.indexOf("#");
  if (h !== -1) pathPart = pathPart.slice(0, h);
  if (pathPart.length > 1 && pathPart.endsWith("/")) pathPart = pathPart.slice(0, -1);
  return pathPart || "/";
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(payload, null, 2));
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk.toString("utf8");
      if (raw.length > 4 * 1024 * 1024) {
        reject(new Error("Request body too large"));
      }
    });
    req.on("end", () => {
      if (!raw.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function loadDiskConfig() {
  if (!fs.existsSync(SETTINGS_PATH)) {
    return {
      found: false,
      configPath: SETTINGS_PATH,
      rawDocument: defaultConfig,
      migratedDocument: defaultConfig,
      schemaVersion: defaultConfig.schemaVersion,
      migrated: false,
    };
  }

  const rawText = fs.readFileSync(SETTINGS_PATH, "utf8");
  const rawDocument = JSON.parse(rawText);
  const migratedDocument = migrateConfigDocument(rawDocument);
  const schemaVersion =
    rawDocument && typeof rawDocument === "object" ? rawDocument.schemaVersion ?? null : null;

  return {
    found: true,
    configPath: SETTINGS_PATH,
    rawDocument,
    migratedDocument,
    schemaVersion,
    migrated: !deepEqual(rawDocument, migratedDocument),
  };
}

function validateCandidateDocument(candidate) {
  if (typeof candidate !== "object" || candidate === null || Array.isArray(candidate)) {
    return {
      ok: false,
      errors: 1,
      warnings: 0,
      issues: [
        {
          severity: "error",
          code: "invalid_payload",
          message: "config must be a JSON object.",
          path: "config",
        },
      ],
      migrated: false,
      schemaVersion: null,
      effectiveSchemaVersion: CURRENT_SCHEMA_VERSION,
      migratedDocument: null,
    };
  }
  const migratedDocument = migrateConfigDocument(candidate);
  const report = validateConfig(migratedDocument);
  return {
    ok: report.ok,
    errors: report.errors,
    warnings: report.warnings,
    issues: report.issues,
    migrated: !deepEqual(candidate, migratedDocument),
    schemaVersion:
      candidate && typeof candidate === "object" ? candidate.schemaVersion ?? null : null,
    effectiveSchemaVersion: migratedDocument?.schemaVersion ?? CURRENT_SCHEMA_VERSION,
    migratedDocument,
  };
}

function atomicSaveConfig(candidate) {
  const dir = path.dirname(SETTINGS_PATH);
  fs.mkdirSync(dir, { recursive: true });

  const tempPath = `${SETTINGS_PATH}.tmp-${Date.now()}-${process.pid}`;
  const backupPath = `${SETTINGS_PATH}.bak-${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const payload = `${JSON.stringify(candidate, null, 2)}\n`;
  fs.writeFileSync(tempPath, payload, "utf8");

  let createdBackupPath = null;
  const existedBefore = fs.existsSync(SETTINGS_PATH);
  if (existedBefore) {
    fs.copyFileSync(SETTINGS_PATH, backupPath);
    createdBackupPath = backupPath;
    fs.rmSync(SETTINGS_PATH, { force: true });
  }

  try {
    fs.renameSync(tempPath, SETTINGS_PATH);
  } catch (err) {
    if (createdBackupPath && fs.existsSync(createdBackupPath) && !fs.existsSync(SETTINGS_PATH)) {
      fs.copyFileSync(createdBackupPath, SETTINGS_PATH);
    }
    throw err;
  } finally {
    if (fs.existsSync(tempPath)) {
      fs.rmSync(tempPath, { force: true });
    }
  }

  return { backupPath: createdBackupPath, existedBefore };
}

function normalizePathCaseInsensitive(p) {
  return path.resolve(String(p || "")).replace(/\//g, "\\").toLowerCase();
}

function envNonEmpty(name) {
  const value = process.env[name];
  return typeof value === "string" && value.trim() !== "";
}

function resolveSettingString(document, unifiedPath, envName, fallback) {
  const [section, key] = unifiedPath.split(".");
  const fromUnified = document?.[section]?.[key];
  if (typeof fromUnified === "string" && fromUnified.trim() !== "") {
    return { value: fromUnified.trim(), source: "unified" };
  }
  const envValue = process.env[envName];
  if (typeof envValue === "string" && envValue.trim() !== "") {
    return { value: envValue.trim(), source: "env" };
  }
  return { value: fallback, source: "default" };
}

function resolveSettingInt(document, unifiedPath, envName, fallback, minimum = 1) {
  const [section, key] = unifiedPath.split(".");
  const fromUnified = document?.[section]?.[key];
  if (typeof fromUnified === "number" && Number.isFinite(fromUnified)) {
    const n = Math.trunc(fromUnified);
    if (n >= minimum) return { value: n, source: "unified" };
  }
  const envValue = process.env[envName];
  if (typeof envValue === "string" && envValue.trim() !== "") {
    const n = Number.parseInt(envValue.trim(), 10);
    if (Number.isFinite(n) && n >= minimum) {
      return { value: n, source: "env" };
    }
  }
  return { value: fallback, source: "default" };
}

/** Install root for resolving relative paths in unified config (matches appliance layout). */
function resolveReplayTroveBase(configDoc) {
  const raw = configDoc?.general?.replayTroveRoot;
  if (typeof raw === "string" && raw.trim() !== "") {
    const t = raw.trim();
    if (path.isAbsolute(t)) {
      return path.resolve(t);
    }
    return path.resolve(ROOT, t);
  }
  return ROOT;
}

/**
 * Same precedence as send_command.ps1 / scoreboard: unified scoreboard.commandsRoot,
 * then COMMANDS_ROOT env, then repo commands tree. Relative values join replayTroveRoot (or ROOT).
 */
function resolveCommandsRootAbsolute(configDoc) {
  const resolved = resolveSettingString(
    configDoc,
    "scoreboard.commandsRoot",
    "COMMANDS_ROOT",
    LEGACY_COMMANDS_ROOT,
  );
  let raw = String(resolved.value || "").trim();
  if (!raw) {
    raw = LEGACY_COMMANDS_ROOT;
  }
  const absoluteRoot = path.isAbsolute(raw)
    ? path.resolve(raw)
    : path.resolve(resolveReplayTroveBase(configDoc), raw);
  return { absoluteRoot, source: resolved.source };
}

function parseReplayPipelineLog() {
  if (!fs.existsSync(REPLAY_PIPELINE_LOG_PATH)) {
    return {
      logFound: false,
      trust: null,
      outcome: null,
      lastCorrelationId: null,
    };
  }
  const raw = fs.readFileSync(REPLAY_PIPELINE_LOG_PATH, "utf8");
  const lines = raw.split(/\r?\n/).filter((line) => line.trim() !== "");
  const parseLineBits = (line) => {
    const stamp = line.slice(0, 23).trim();
    const cidMatch = line.match(/\bcid=([0-9a-fA-F-]+)/);
    return { stamp, cid: cidMatch ? cidMatch[1] : null };
  };
  let trust = null;
  let outcome = null;
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (!trust && line.includes("trust_category=")) {
      const bits = parseLineBits(line);
      const trustMatch = line.match(/\btrust_category=([a-z_]+)/i);
      trust = {
        timestamp: bits.stamp || null,
        correlationId: bits.cid,
        category: trustMatch ? trustMatch[1] : null,
      };
    }
    if (!outcome && (line.includes("pipeline=success") || line.includes("pipeline=fail"))) {
      const bits = parseLineBits(line);
      outcome = {
        timestamp: bits.stamp || null,
        correlationId: bits.cid,
        success: line.includes("pipeline=success"),
      };
    }
    if (trust && outcome) break;
  }
  return {
    logFound: true,
    trust,
    outcome,
    lastCorrelationId: outcome?.correlationId ?? trust?.correlationId ?? null,
  };
}

function parseIsoDate(value) {
  if (typeof value !== "string" || value.trim() === "") return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function humanizeAgeSeconds(ageSec) {
  if (ageSec == null || !Number.isFinite(ageSec)) return null;
  if (ageSec < 60) return `${Math.round(ageSec)}s`;
  if (ageSec < 3600) return `${Math.round(ageSec / 60)}m`;
  if (ageSec < 86400) return `${(ageSec / 3600).toFixed(1)}h`;
  return `${(ageSec / 86400).toFixed(1)}d`;
}

/**
 * @param {ReturnType<typeof parseLauncherSupervisionState>} supervision
 * @param {object} configDoc
 */
function enrichLauncherSupervisionFreshness(supervision, configDoc) {
  const pollObj = resolveSettingInt(
    configDoc,
    "launcher.supervisionPollSec",
    "REPLAYTROVE_SUPERVISION_POLL_SEC",
    5,
    1,
  );
  const poll = pollObj.value;
  const supervisionTickStaleSec = Math.max(25, poll * 4);
  const desiredStateInfoStaleSec = Math.max(120, poll * 24);

  /** @type {"fresh"|"stale"|"unavailable"|"corrupt"|"unknown"} */
  let leaseFresh = "unavailable";
  let leaseAgeSec = null;
  const leaseTimeout =
    supervision.owner?.leaseTimeoutSec != null && Number.isFinite(supervision.owner.leaseTimeoutSec)
      ? supervision.owner.leaseTimeoutSec
      : 20;
  const leaseState = supervision.owner?.state;
  if (leaseState === "corrupt") {
    leaseFresh = "corrupt";
  } else if (!fs.existsSync(LAUNCHER_OWNER_LEASE_PATH)) {
    leaseFresh = "unavailable";
  } else {
    const leaseDt = parseIsoDate(supervision.owner?.updatedAt);
    if (!leaseDt) {
      leaseFresh = "unknown";
    } else {
      leaseAgeSec = Math.max(0, (Date.now() - leaseDt.getTime()) / 1000);
      leaseFresh = leaseAgeSec <= leaseTimeout ? "fresh" : "stale";
    }
  }

  /** @type {"fresh"|"stale"|"unavailable"|"corrupt"|"unknown"} */
  let statusFresh = "unavailable";
  let statusAgeSec = null;
  if (supervision.supervisionStatusArtifact === "corrupt") {
    statusFresh = "corrupt";
  } else if (supervision.supervisionStatusArtifact === "missing") {
    statusFresh = "unavailable";
  } else {
    const snapDt = parseIsoDate(supervision.snapshotTimestamp);
    if (!snapDt) {
      statusFresh = "unknown";
    } else {
      statusAgeSec = Math.max(0, (Date.now() - snapDt.getTime()) / 1000);
      statusFresh = statusAgeSec <= supervisionTickStaleSec ? "fresh" : "stale";
    }
  }

  const dp = supervision.desiredStatePersisted;
  /** @type {"fresh"|"stale"|"unavailable"|"corrupt"|"unknown"} */
  let desiredFresh = "unavailable";
  let desiredAgeSec = null;
  if (dp.fileState === "corrupt") {
    desiredFresh = "corrupt";
  } else if (dp.fileState === "missing") {
    desiredFresh = "unavailable";
  } else {
    const dDt = parseIsoDate(dp.updatedAt);
    if (!dDt) {
      desiredFresh = "unknown";
    } else {
      desiredAgeSec = Math.max(0, (Date.now() - dDt.getTime()) / 1000);
      desiredFresh = desiredAgeSec <= desiredStateInfoStaleSec ? "fresh" : "stale";
    }
  }

  const artifactFreshness = {
    ownerLease: {
      state: leaseFresh,
      ageSeconds: leaseAgeSec != null ? Math.round(leaseAgeSec * 10) / 10 : null,
      thresholdSeconds:
        leaseFresh === "corrupt" || leaseFresh === "unavailable" ? null : leaseTimeout,
      humanAge: humanizeAgeSeconds(leaseAgeSec),
      basis: "updated_at vs lease_timeout_sec",
    },
    supervisionStatus: {
      state: statusFresh,
      ageSeconds: statusAgeSec != null ? Math.round(statusAgeSec * 10) / 10 : null,
      thresholdSeconds:
        statusFresh === "corrupt" || statusFresh === "unavailable" ? null : supervisionTickStaleSec,
      humanAge: humanizeAgeSeconds(statusAgeSec),
      basis: `snapshot timestamp vs max(25, supervisionPollSec*4); poll_sec=${poll} (${pollObj.source})`,
    },
    desiredState: {
      state: desiredFresh,
      ageSeconds: desiredAgeSec != null ? Math.round(desiredAgeSec * 10) / 10 : null,
      thresholdSeconds:
        desiredFresh === "corrupt" || desiredFresh === "unavailable"
          ? null
          : desiredStateInfoStaleSec,
      humanAge: humanizeAgeSeconds(desiredAgeSec),
      basis: `updated_at vs max(120, supervisionPollSec*24); poll_sec=${poll}`,
    },
  };

  const managedComponents = supervision.managedComponents.map((row) => {
    let liveRowFreshness = /** @type {"fresh"|"stale"|"unknown"|"unavailable"} */ ("unknown");
    if (statusFresh === "corrupt" || statusFresh === "unavailable") {
      liveRowFreshness = "unavailable";
    } else if (statusFresh === "unknown") {
      liveRowFreshness = "unknown";
    } else if (statusFresh === "stale") {
      liveRowFreshness = "stale";
    } else {
      const obsDt = parseIsoDate(row.lastObservedAt);
      if (!obsDt) {
        liveRowFreshness = "unknown";
      } else {
        const rowAge = Math.max(0, (Date.now() - obsDt.getTime()) / 1000);
        liveRowFreshness = rowAge <= supervisionTickStaleSec ? "fresh" : "stale";
      }
    }
    return { ...row, liveRowFreshness };
  });

  return {
    ...supervision,
    managedComponents,
    artifactFreshness,
  };
}

function parseSupervisionDesiredStatePersisted() {
  const out = {
    fileRelative: "launcher/supervision_desired_state.json",
    fileState: /** @type {"missing" | "corrupt" | "available"} */ ("missing"),
    updatedAt: /** @type {string | null} */ (null),
    updateReason: /** @type {string | null} */ (null),
    schemaVersion: /** @type {number | null} */ (null),
    components: /** @type {Record<string, "running" | "stopped" | null>} */ ({}),
  };
  for (const name of SUPERVISION_MANAGED_COMPONENTS) {
    out.components[name] = null;
  }
  if (!fs.existsSync(LAUNCHER_SUPERVISION_DESIRED_STATE_PATH)) {
    return out;
  }
  try {
    const raw = fs.readFileSync(LAUNCHER_SUPERVISION_DESIRED_STATE_PATH, "utf8");
    const j = JSON.parse(raw);
    out.fileState = "available";
    out.updatedAt = typeof j.updated_at === "string" ? j.updated_at : null;
    out.updateReason = typeof j.update_reason === "string" ? j.update_reason : null;
    out.schemaVersion = Number.isFinite(Number(j.schema_version)) ? Number(j.schema_version) : null;
    const blob =
      j && typeof j === "object" && j.components && typeof j.components === "object"
        ? j.components
        : j;
    for (const name of SUPERVISION_MANAGED_COMPONENTS) {
      const v = blob && typeof blob === "object" ? blob[name] : undefined;
      if (v === "running" || v === "stopped") {
        out.components[name] = v;
      } else {
        out.components[name] = null;
      }
    }
  } catch {
    out.fileState = "corrupt";
    for (const name of SUPERVISION_MANAGED_COMPONENTS) {
      out.components[name] = null;
    }
  }
  return out;
}

function parseLauncherSupervisionState() {
  let ownerLease = null;
  /** @type {"active"|"graceful_shutdown"|"stale"|"unavailable"|"corrupt"} */
  let ownerLeaseState = "unavailable";
  if (fs.existsSync(LAUNCHER_OWNER_LEASE_PATH)) {
    try {
      ownerLease = JSON.parse(fs.readFileSync(LAUNCHER_OWNER_LEASE_PATH, "utf8"));
      const updatedAt = parseIsoDate(ownerLease?.updated_at);
      const timeoutSec =
        typeof ownerLease?.lease_timeout_sec === "number" && ownerLease.lease_timeout_sec > 0
          ? ownerLease.lease_timeout_sec
          : 20;
      const ageSec = updatedAt
        ? Math.max(0, (Date.now() - updatedAt.getTime()) / 1000)
        : Number.POSITIVE_INFINITY;
      const gracefulReasons = new Set(["shutdown", "stopped_by_operator", "supervision_disabled"]);
      if (gracefulReasons.has(String(ownerLease?.reason || ""))) {
        ownerLeaseState = "graceful_shutdown";
      } else if (Number.isFinite(ageSec) && ageSec <= timeoutSec) {
        ownerLeaseState = "active";
      } else {
        ownerLeaseState = "stale";
      }
    } catch {
      ownerLeaseState = "corrupt";
    }
  }

  let supervisionSnapshot = null;
  /** @type {"missing"|"corrupt"|"available"} */
  let supervisionStatusArtifact = "missing";
  if (fs.existsSync(LAUNCHER_SUPERVISION_STATUS_PATH)) {
    try {
      supervisionSnapshot = JSON.parse(
        fs.readFileSync(LAUNCHER_SUPERVISION_STATUS_PATH, "utf8"),
      );
      supervisionStatusArtifact = "available";
    } catch {
      supervisionSnapshot = null;
      supervisionStatusArtifact = "corrupt";
    }
  }

  const components = {};
  const rawComponents =
    supervisionSnapshot &&
    typeof supervisionSnapshot === "object" &&
    supervisionSnapshot.components &&
    typeof supervisionSnapshot.components === "object"
      ? supervisionSnapshot.components
      : {};
  for (const [name, info] of Object.entries(rawComponents)) {
    components[name] = {
      desiredStateLive:
        info && typeof info === "object" && typeof info.desired_state === "string"
          ? info.desired_state
          : null,
      lastObservedAt:
        info && typeof info === "object" && typeof info.last_observed_at === "string"
          ? info.last_observed_at
          : null,
      lastClassification:
        info && typeof info === "object" && typeof info.last_classification === "string"
          ? info.last_classification
          : null,
      lastReason:
        info && typeof info === "object" && typeof info.last_reason === "string"
          ? info.last_reason
          : null,
      lastRestartAt:
        info && typeof info === "object" && typeof info.last_restart_at === "string"
          ? info.last_restart_at
          : null,
      lastRestartReason:
        info && typeof info === "object" && typeof info.last_restart_reason === "string"
          ? info.last_restart_reason
          : null,
      consecutiveUnhealthy:
        info && typeof info === "object" && Number.isFinite(Number(info.consecutive_unhealthy))
          ? Number(info.consecutive_unhealthy)
          : null,
    };
  }

  const desiredStatePersisted = parseSupervisionDesiredStatePersisted();
  const managedComponents = SUPERVISION_MANAGED_COMPONENTS.map((name) => {
    const info = components[name] || {};
    const persisted = desiredStatePersisted.components[name];
    return {
      name,
      desiredPersisted:
        persisted === "running" || persisted === "stopped" ? persisted : "unknown",
      desiredLive:
        info.desiredStateLive === "running" || info.desiredStateLive === "stopped"
          ? info.desiredStateLive
          : null,
      lastClassification: info.lastClassification ?? null,
      lastReason: info.lastReason ?? null,
      lastRestartAt: info.lastRestartAt ?? null,
      lastRestartReason: info.lastRestartReason ?? null,
      lastObservedAt: info.lastObservedAt ?? null,
      consecutiveUnhealthy: info.consecutiveUnhealthy ?? null,
    };
  });

  return {
    supervisionStatusArtifact,
    owner: {
      leaseFileRelative: "launcher/supervision_owner_lease.json",
      state: ownerLeaseState,
      active: ownerLeaseState === "active",
      ownerId:
        ownerLease && typeof ownerLease.owner_id === "string" ? ownerLease.owner_id : null,
      pid: ownerLease && Number.isFinite(Number(ownerLease.pid)) ? Number(ownerLease.pid) : null,
      hostname:
        ownerLease && typeof ownerLease.hostname === "string" ? ownerLease.hostname : null,
      createdAt:
        ownerLease && typeof ownerLease.created_at === "string" ? ownerLease.created_at : null,
      updatedAt:
        ownerLease && typeof ownerLease.updated_at === "string" ? ownerLease.updated_at : null,
      reason: ownerLease && typeof ownerLease.reason === "string" ? ownerLease.reason : null,
      leaseTimeoutSec:
        ownerLease && Number.isFinite(Number(ownerLease.lease_timeout_sec))
          ? Number(ownerLease.lease_timeout_sec)
          : null,
    },
    snapshotTimestamp:
      supervisionSnapshot && typeof supervisionSnapshot.timestamp === "string"
        ? supervisionSnapshot.timestamp
        : null,
    supervisionStatusFileRelative: "launcher/supervision_status.json",
    desiredStatePersisted,
    managedComponents,
    components,
  };
}

async function buildSystemStatus() {
  const loaded = loadDiskConfig();
  const configDoc = loaded.migratedDocument || defaultConfig;

  const replayHost = resolveSettingString(
    configDoc,
    "worker.httpReplayTriggerHost",
    "REPLAY_TRIGGER_HTTP_HOST",
    "127.0.0.1",
  );
  const replayPort = resolveSettingInt(
    configDoc,
    "worker.httpReplayTriggerPort",
    "REPLAY_TRIGGER_HTTP_PORT",
    18765,
    1,
  );
  const replayTimeout = resolveSettingInt(
    configDoc,
    "worker.httpReplayTriggerTimeoutSec",
    "REPLAY_TRIGGER_HTTP_TIMEOUT_SEC",
    45,
    1,
  );
  const canonicalTokenConfigured = envNonEmpty("REPLAY_CANONICAL_TOKEN");

  let replayHttpReachable = null;
  let replayHttpReachabilityError = null;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1500);
    const response = await fetch(
      `http://${replayHost.value}:${replayPort.value}/health`,
      { method: "GET", signal: controller.signal },
    );
    clearTimeout(timeoutId);
    replayHttpReachable = response.ok;
  } catch (err) {
    replayHttpReachable = false;
    replayHttpReachabilityError = err instanceof Error ? err.message : String(err);
  }

  const replayLog = parseReplayPipelineLog();

  const obsHost = resolveSettingString(
    configDoc,
    "scoreboard.obsWebsocketHost",
    "OBS_WEBSOCKET_HOST",
    "localhost",
  );
  const obsPort = resolveSettingInt(
    configDoc,
    "scoreboard.obsWebsocketPort",
    "OBS_WEBSOCKET_PORT",
    4455,
    1,
  );
  const obsPasswordSource = (() => {
    const v = configDoc?.scoreboard?.obsWebsocketPassword;
    if (typeof v === "string" && v.trim() !== "") return "unified";
    if (envNonEmpty("OBS_WEBSOCKET_PASSWORD")) return "env";
    return "default";
  })();
  const obsPasswordConfigured =
    obsPasswordSource === "unified" ||
    obsPasswordSource === "env";

  const commandsRootResolved = resolveCommandsRootAbsolute(configDoc);
  const commandRoot = {
    value: commandsRootResolved.absoluteRoot,
    source: commandsRootResolved.source,
  };
  const commandRootDivergesFromLegacy =
    normalizePathCaseInsensitive(commandRoot.value) !==
    normalizePathCaseInsensitive(LEGACY_COMMANDS_ROOT);
  const legacyBridgeActive = commandRootDivergesFromLegacy;
  const launcherSupervision = enrichLauncherSupervisionFreshness(
    parseLauncherSupervisionState(),
    configDoc,
  );

  return {
    replayReadiness: {
      replayHttpHost: replayHost,
      replayHttpPort: replayPort,
      replayHttpTimeoutSec: replayTimeout,
      replayHttpReachable,
      replayHttpReachabilityError,
      canonicalTokenConfigured,
    },
    replayRecentActivity: {
      lastTrustCategory: replayLog.trust?.category ?? null,
      lastReplayTimestamp:
        replayLog.outcome?.timestamp ?? replayLog.trust?.timestamp ?? null,
      lastReplaySucceeded: replayLog.outcome?.success ?? null,
      lastReplayCorrelationId: replayLog.lastCorrelationId,
      replayLogFound: replayLog.logFound,
    },
    obsSummary: {
      obsWebsocketHost: obsHost,
      obsWebsocketPort: obsPort,
      obsWebsocketPasswordConfigured: obsPasswordConfigured,
      obsWebsocketPasswordSource: obsPasswordSource,
    },
    commandBus: {
      commandsRoot: commandRoot,
      legacyBridgeActive,
      configuredRootDivergesFromLegacy: commandRootDivergesFromLegacy,
      legacyRoot: LEGACY_COMMANDS_ROOT,
    },
    launcherSupervision,
  };
}

function looksLikeMpvExecutablePath(p) {
  if (typeof p !== "string" || !p.trim()) return false;
  const norm = p.trim().replace(/\\/g, "/").toLowerCase();
  return norm.endsWith("/mpv.exe") || norm.endsWith("/mpv");
}

function resolveFfmpegPathForEncoderDiscovery(configDoc) {
  const p = configDoc?.obsFfmpegPaths?.ffmpegPath;
  if (typeof p === "string" && p.trim()) {
    const t = p.trim();
    if (looksLikeMpvExecutablePath(t)) {
      return defaultConfig.obsFfmpegPaths.ffmpegPath;
    }
    return t;
  }
  return defaultConfig.obsFfmpegPaths.ffmpegPath;
}

function getEncoderDevicesFromDiscovery() {
  const loaded = loadDiskConfig();
  const configDoc = loaded.migratedDocument || defaultConfig;
  const ffmpegPath = resolveFfmpegPathForEncoderDiscovery(configDoc);
  const encoderDir = path.resolve(ROOT, "encoder");
  const scriptPath = path.join(encoderDir, "list_uvc_devices.py");
  if (!fs.existsSync(scriptPath)) {
    return {
      ok: false,
      error: "script_missing",
      message: `Encoder discovery script missing: ${scriptPath}`,
    };
  }
  const pythonExe =
    (process.env.REPLAYTROVE_PYTHON && process.env.REPLAYTROVE_PYTHON.trim()) ||
    (process.platform === "win32" ? "python" : "python3");
  const result = spawnSync(pythonExe, [scriptPath, "--json", "--ffmpeg", ffmpegPath], {
    cwd: encoderDir,
    env: { ...process.env, FFMPEG_PATH: ffmpegPath },
    encoding: "utf8",
    maxBuffer: 12 * 1024 * 1024,
  });
  if (result.error) {
    return {
      ok: false,
      error: "spawn_failed",
      message: result.error.message || String(result.error),
    };
  }
  const out = (result.stdout || "").trim();
  if (!out) {
    return {
      ok: false,
      error: "empty_output",
      message: "Discovery script produced no stdout.",
      stderr: (result.stderr || "").slice(0, 4000),
    };
  }
  try {
    const parsed = JSON.parse(out);
    console.error(
      `[replaytrove-control-center] encoder devices discovery devicesOk=${Boolean(parsed?.ok)} video=${parsed?.videoDevices?.length ?? 0} audio=${parsed?.audioDevices?.length ?? 0} ffmpegPath=${ffmpegPath}`,
    );
    return { ok: true, data: parsed, ffmpegPathUsed: ffmpegPath };
  } catch (err) {
    return {
      ok: false,
      error: "invalid_json",
      message: err instanceof Error ? err.message : String(err),
      stdoutExcerpt: out.slice(0, 2000),
      stderr: (result.stderr || "").slice(0, 4000),
    };
  }
}

function enqueueScoreboardSafeReloadCommand(correlationId) {
  const loaded = loadDiskConfig();
  const configDoc = loaded.migratedDocument || defaultConfig;
  const { absoluteRoot, source: commandsRootSource } = resolveCommandsRootAbsolute(configDoc);
  const pendingDir = path.join(absoluteRoot, "scoreboard", "pending");
  console.error(
    `[replaytrove-control-center] enqueue scoreboard command pendingDir=${pendingDir} commandsRootSource=${commandsRootSource} sourceApp=control-center action=reload_scoreboard_safe_settings`,
  );
  fs.mkdirSync(pendingDir, { recursive: true });
  const created = new Date();
  const createdIso = created.toISOString();
  const id = randomUUID().replace(/-/g, "");
  const ts = createdIso.replace(/[-:.TZ]/g, "").slice(0, 17);
  const fileBase = `${ts}_reload_scoreboard_safe_settings`;
  const tmpPath = path.join(pendingDir, `${fileBase}.tmp`);
  const finalPath = path.join(pendingDir, `${fileBase}.json`);
  const payload = {
    id,
    action: "reload_scoreboard_safe_settings",
    created_at: createdIso,
    source: "control-center",
    args: { correlation_id: correlationId ?? randomUUID() },
  };
  fs.writeFileSync(tmpPath, JSON.stringify(payload), "utf8");
  fs.renameSync(tmpPath, finalPath);
  return { id, path: finalPath, correlationId: payload.args.correlation_id };
}

const server = createServer(async (req, res) => {
  try {
    const pathOnly = requestPathname(req.url);

    if (req.method === "OPTIONS") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method === "GET" && pathOnly === "/api/config") {
      const loaded = loadDiskConfig();
      const validation = validateCandidateDocument(loaded.migratedDocument);
      sendJson(res, 200, {
        ok: true,
        configPath: loaded.configPath,
        found: loaded.found,
        schemaVersion: loaded.schemaVersion,
        migrated: loaded.migrated,
        validation: {
          ok: validation.ok,
          errors: validation.errors,
          warnings: validation.warnings,
          issues: validation.issues,
        },
        config: loaded.migratedDocument,
      });
      return;
    }

    if (req.method === "POST" && pathOnly === "/api/config/validate") {
      const body = await readJsonBody(req);
      const candidate = body?.config;
      const validation = validateCandidateDocument(candidate);
      sendJson(res, validation.ok ? 200 : 400, {
        ok: validation.ok,
        errors: validation.errors,
        warnings: validation.warnings,
        issues: validation.issues,
        schemaVersion: validation.schemaVersion,
        effectiveSchemaVersion: validation.effectiveSchemaVersion,
        migrated: validation.migrated,
      });
      return;
    }

    if (req.method === "POST" && pathOnly === "/api/config/save") {
      const body = await readJsonBody(req);
      const candidate = body?.config;
      const validation = validateCandidateDocument(candidate);
      if (!validation.ok) {
        sendJson(res, 400, {
          ok: false,
          message: "Validation failed; config not saved.",
          errors: validation.errors,
          warnings: validation.warnings,
          issues: validation.issues,
          migrated: validation.migrated,
        });
        return;
      }

      // Preserve unknown keys by saving the candidate shape (not schema-stripped parsed object).
      const { backupPath } = atomicSaveConfig(candidate);
      sendJson(res, 200, {
        ok: true,
        configPath: SETTINGS_PATH,
        backupPath,
        migrated: validation.migrated,
        effectiveSchemaVersion: validation.effectiveSchemaVersion,
        warnings: validation.warnings,
        issues: validation.issues,
      });
      return;
    }

    if (req.method === "GET" && pathOnly === "/api/config/export") {
      const loaded = loadDiskConfig();
      res.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Disposition": 'attachment; filename="settings.export.json"',
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
      });
      res.end(`${JSON.stringify(loaded.rawDocument, null, 2)}\n`);
      return;
    }

    if (req.method === "POST" && pathOnly === "/api/scoreboard/reload-safe-settings") {
      // Queue-only endpoint; apply/reject result is produced by scoreboard process.
      const body = await readJsonBody(req);
      const queued = enqueueScoreboardSafeReloadCommand(body?.correlationId);
      sendJson(res, 200, {
        ok: true,
        commandId: queued.id,
        commandPath: queued.path,
        correlationId: queued.correlationId,
        message:
          "Reload command queued. Only scoreboard safe monitoring intervals are applied live.",
      });
      return;
    }

    if (req.method === "GET" && pathOnly === "/api/scoreboard/reload-safe-settings-status") {
      // Read-only view of last scoreboard reload outcome artifact.
      if (!fs.existsSync(SCOREBOARD_SAFE_RELOAD_STATUS_PATH)) {
        sendJson(res, 200, {
          ok: true,
          found: false,
          statusPath: SCOREBOARD_SAFE_RELOAD_STATUS_PATH,
        });
        return;
      }
      const raw = fs.readFileSync(SCOREBOARD_SAFE_RELOAD_STATUS_PATH, "utf8");
      const parsed = JSON.parse(raw);
      sendJson(res, 200, {
        ok: true,
        found: true,
        statusPath: SCOREBOARD_SAFE_RELOAD_STATUS_PATH,
        status: parsed,
      });
      return;
    }

    if (req.method === "GET" && pathOnly === "/api/encoder/devices") {
      const discovery = getEncoderDevicesFromDiscovery();
      if (!discovery.ok) {
        sendJson(res, 500, {
          ok: false,
          error: discovery.error,
          message: discovery.message,
          stderr: discovery.stderr,
          stdoutExcerpt: discovery.stdoutExcerpt,
        });
        return;
      }
      const d = discovery.data;
      sendJson(res, 200, {
        ok: true,
        ffmpegPathUsed: discovery.ffmpegPathUsed,
        devicesOk: Boolean(d?.ok),
        platform: d?.platform,
        videoDevices: d?.videoDevices ?? [],
        audioDevices: d?.audioDevices ?? [],
        parseNote: d?.parseNote,
        rawExcerpt: d?.rawExcerpt,
        ffmpegPath: d?.ffmpegPath,
        ffmpegReturnCode: d?.ffmpegReturnCode,
      });
      return;
    }

    if (req.method === "GET" && pathOnly === "/api/system/status") {
      const status = await buildSystemStatus();
      sendJson(res, 200, { ok: true, status });
      return;
    }

    sendJson(res, 404, { ok: false, message: "Not found" });
  } catch (error) {
    sendJson(res, 500, {
      ok: false,
      message: error instanceof Error ? error.message : "Internal server error",
    });
  }
});

server.listen(API_PORT, "127.0.0.1", () => {
  console.log(`[control-center-api] listening on http://127.0.0.1:${API_PORT}`);
  console.log(`[control-center-api] settings path: ${SETTINGS_PATH}`);
});
