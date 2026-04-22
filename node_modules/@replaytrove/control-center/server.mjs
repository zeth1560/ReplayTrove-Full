import fs from "node:fs";
import path from "node:path";
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
const SCOREBOARD_PENDING_DIR = path.resolve(ROOT, "commands", "scoreboard", "pending");
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

function parseLauncherSupervisionState() {
  let ownerLease = null;
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
      ownerLeaseState = "unavailable";
    }
  }

  let supervisionSnapshot = null;
  if (fs.existsSync(LAUNCHER_SUPERVISION_STATUS_PATH)) {
    try {
      supervisionSnapshot = JSON.parse(
        fs.readFileSync(LAUNCHER_SUPERVISION_STATUS_PATH, "utf8"),
      );
    } catch {
      supervisionSnapshot = null;
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
    };
  }

  return {
    owner: {
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

  const commandRoot = resolveSettingString(
    configDoc,
    "scoreboard.commandsRoot",
    "COMMANDS_ROOT",
    LEGACY_COMMANDS_ROOT,
  );
  const commandRootDivergesFromLegacy =
    normalizePathCaseInsensitive(commandRoot.value) !==
    normalizePathCaseInsensitive(LEGACY_COMMANDS_ROOT);
  const legacyBridgeActive = commandRootDivergesFromLegacy;
  const launcherSupervision = parseLauncherSupervisionState();

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

function enqueueScoreboardSafeReloadCommand(correlationId) {
  // Explicit operator-triggered scoreboard-only reload command enqueue.
  fs.mkdirSync(SCOREBOARD_PENDING_DIR, { recursive: true });
  const created = new Date();
  const createdIso = created.toISOString();
  const id = randomUUID().replace(/-/g, "");
  const ts = createdIso.replace(/[-:.TZ]/g, "").slice(0, 17);
  const fileBase = `${ts}_reload_scoreboard_safe_settings`;
  const tmpPath = path.join(SCOREBOARD_PENDING_DIR, `${fileBase}.tmp`);
  const finalPath = path.join(SCOREBOARD_PENDING_DIR, `${fileBase}.json`);
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
    if (req.method === "OPTIONS") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method === "GET" && req.url === "/api/config") {
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

    if (req.method === "POST" && req.url === "/api/config/validate") {
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

    if (req.method === "POST" && req.url === "/api/config/save") {
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

    if (req.method === "GET" && req.url === "/api/config/export") {
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

    if (req.method === "POST" && req.url === "/api/scoreboard/reload-safe-settings") {
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

    if (req.method === "GET" && req.url === "/api/scoreboard/reload-safe-settings-status") {
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

    if (req.method === "GET" && req.url === "/api/system/status") {
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
