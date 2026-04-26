import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { defaultConfig } from "../../../packages/config/src/defaults.js";
import { AppConfigSchema, type AppConfig } from "../../../packages/config/src/schema.js";

const STORAGE_KEY = "replaytrove-control-center-config";
const API_BASE = "http://127.0.0.1:4311";

type SectionKey = keyof AppConfig;
type GroupName =
  | "General"
  | "Paths and Storage"
  | "Replay Processing"
  | "Playback and MPV"
  | "Launcher Startup"
  | "Status and Monitoring"
  | "Timing and Retries"
  | "Encoder (UVC)"
  | "Integrations";

type DangerousType = "startup" | "runtime" | "conflict";

type FieldMeta = {
  key: string;
  label: string;
  help?: string;
  placeholder?: string;
  group: GroupName;
  restartRequired: boolean;
  hotReloadCandidate: boolean;
  advanced: boolean;
  dangerous: boolean;
  surfacedInForm: boolean;
  impact?: string;
  dangerousType?: DangerousType;
};

type SourceResolved<T> = {
  value: T;
  source: "unified" | "env" | "default";
};

type ArtifactFreshness = {
  state: string;
  ageSeconds: number | null;
  thresholdSeconds: number | null;
  humanAge: string | null;
  basis?: string;
};

type SystemStatus = {
  replayReadiness: {
    replayHttpHost: SourceResolved<string>;
    replayHttpPort: SourceResolved<number>;
    replayHttpTimeoutSec: SourceResolved<number>;
    replayHttpReachable: boolean | null;
    replayHttpReachabilityError: string | null;
    canonicalTokenConfigured: boolean;
  };
  replayRecentActivity: {
    lastTrustCategory: string | null;
    lastReplayTimestamp: string | null;
    lastReplaySucceeded: boolean | null;
    lastReplayCorrelationId: string | null;
    replayLogFound: boolean;
  };
  obsSummary: {
    obsWebsocketHost: SourceResolved<string>;
    obsWebsocketPort: SourceResolved<number>;
    obsWebsocketPasswordConfigured: boolean;
    obsWebsocketPasswordSource: "unified" | "env" | "default";
  };
  commandBus: {
    commandsRoot: SourceResolved<string>;
    legacyBridgeActive: boolean;
    configuredRootDivergesFromLegacy: boolean;
    legacyRoot: string;
  };
  launcherSupervision: {
    supervisionStatusArtifact?: "missing" | "corrupt" | "available";
    artifactFreshness?: {
      ownerLease: ArtifactFreshness;
      supervisionStatus: ArtifactFreshness;
      desiredState: ArtifactFreshness;
    };
    owner: {
      leaseFileRelative?: string;
      state: "active" | "graceful_shutdown" | "stale" | "unavailable" | "corrupt";
      active: boolean;
      ownerId: string | null;
      pid: number | null;
      hostname: string | null;
      createdAt: string | null;
      updatedAt: string | null;
      reason: string | null;
      leaseTimeoutSec: number | null;
    };
    snapshotTimestamp: string | null;
    supervisionStatusFileRelative?: string;
    desiredStatePersisted: {
      fileRelative: string;
      fileState: "missing" | "corrupt" | "available";
      updatedAt: string | null;
      updateReason: string | null;
      schemaVersion: number | null;
      components: Record<string, "running" | "stopped" | null>;
    };
    managedComponents: Array<{
      name: string;
      desiredPersisted: "running" | "stopped" | "unknown";
      desiredLive: "running" | "stopped" | null;
      lastClassification: string | null;
      lastReason: string | null;
      lastRestartAt: string | null;
      lastRestartReason: string | null;
      lastObservedAt: string | null;
      consecutiveUnhealthy: number | null;
      liveRowFreshness?: "fresh" | "stale" | "unknown" | "unavailable";
    }>;
    components: Record<
      string,
      {
        desiredStateLive?: string | null;
        lastObservedAt?: string | null;
        lastClassification: string | null;
        lastReason: string | null;
        lastRestartAt: string | null;
        lastRestartReason: string | null;
        consecutiveUnhealthy?: number | null;
      }
    >;
  };
};

const SECTION_LABELS: Record<SectionKey, string> = {
  schemaVersion: "Schema",
  general: "General",
  webApp: "Web App",
  worker: "Worker",
  scoreboard: "Scoreboard",
  launcher: "Launcher",
  cleaner: "Cleaner",
  obsFfmpegPaths: "OBS / FFmpeg / Paths",
  encoder: "Encoder (UVC)",
  storage: "Storage",
  picklePlanner: "Pickle Planner",
};

function cloneDefault(): AppConfig {
  return JSON.parse(JSON.stringify(defaultConfig)) as AppConfig;
}

function safeParseJson<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

function looksLikeMpvExecutablePath(p: string): boolean {
  const t = p.trim();
  if (!t) return false;
  const norm = t.replace(/\\/g, "/").toLowerCase();
  return norm.endsWith("/mpv.exe") || norm.endsWith("/mpv");
}

function fieldLabel(label: string, help?: string) {
  return (
    <label style={{ display: "block", marginBottom: 8 }}>
      <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
      {help ? <div style={{ fontSize: 12, color: "#555" }}>{help}</div> : null}
    </label>
  );
}

function fieldHelp(help?: string) {
  if (!help) return null;
  return <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>{help}</div>;
}

function supervisionFreshnessLine(title: string, f: ArtifactFreshness | undefined) {
  if (!f) return null;
  const parts: string[] = [f.state];
  if (f.humanAge != null) parts.push(`~${f.humanAge} old`);
  if (
    f.thresholdSeconds != null &&
    f.state !== "corrupt" &&
    f.state !== "unavailable"
  ) {
    parts.push(`stale if older than ${f.thresholdSeconds}s`);
  }
  return (
    <div style={{ fontSize: 11, color: "#555", marginBottom: 4 }} title={f.basis}>
      <span style={{ fontWeight: 600 }}>{title}:</span> {parts.join(" · ")}
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  background: "#f7f8fa",
  padding: 12,
  borderRadius: 8,
  border: "1px solid #e3e6eb",
};

const sectionCardStyle: React.CSSProperties = {
  border: "1px solid #e3e6eb",
  borderRadius: 10,
  padding: 12,
  marginBottom: 12,
  background: "#ffffff",
};

function getByPath(obj: unknown, key: string): unknown {
  const parts = key.split(".");
  let cur: any = obj;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = cur[p];
  }
  return cur;
}

const FIELD_META: FieldMeta[] = [
  {
    key: "worker.httpReplayTriggerHost",
    label: "Worker replay trigger host",
    help: "Host for the worker POST /replay listener (usually 127.0.0.1). See docs/operator-replay-trigger-runbook.md.",
    placeholder: "127.0.0.1",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.watchFolder",
    label: "Worker watch folder",
    help: "Folder monitored for incoming clips.",
    placeholder: "C:\\ReplayTrove\\clips",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Worker may stop seeing new clips.",
    dangerousType: "runtime",
  },
  {
    key: "worker.instantReplaySource",
    label: "Instant replay source path",
    help: "Canonical instant replay file location.",
    placeholder: "C:\\ReplayTrove\\INSTANTREPLAY.mkv",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Replay ingest may fail if file is missing or wrong.",
    dangerousType: "runtime",
  },
  {
    key: "worker.longClipsFolder",
    label: "Long clips folder",
    help: "Folder scanned for longer clips.",
    placeholder: "C:\\ReplayTrove\\long_clips",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Long-clip ingest path may break.",
    dangerousType: "runtime",
  },
  {
    key: "worker.workerStatusJsonPath",
    label: "Worker status JSON path",
    help: "Path where worker writes health/status summary.",
    placeholder: "C:\\ReplayTrove\\status.json",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.workerConcurrency",
    label: "Worker concurrency",
    help: "Maximum number of worker jobs processed concurrently.",
    placeholder: "1",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.uploadRetries",
    label: "Upload retries",
    help: "Retry count for upload failures.",
    placeholder: "3",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.uploadRetryDelaySeconds",
    label: "Upload retry delay seconds",
    help: "Delay between upload retries.",
    placeholder: "3",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.replayScoreboardAutoSyncIntervalSeconds",
    label: "Replay auto-sync interval seconds",
    help: "Polling interval for replay auto-sync path.",
    placeholder: "0",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.httpReplayTriggerPort",
    label: "Worker replay trigger port",
    help: "Appliance default is 18765; Companion/Stream Deck must match. Guide: docs/operator-replay-trigger-runbook.md.",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Replay trigger service may fail if port conflicts.",
    dangerousType: "conflict",
  },
  {
    key: "worker.httpReplayTriggerTimeoutSec",
    label: "Worker replay trigger timeout seconds",
    help: "Timeout for canonical replay HTTP trigger waits.",
    placeholder: "45",
    group: "Timing and Retries",
    restartRequired: false,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.enableReplayScoreboardAutoSync",
    label: "Enable replay scoreboard auto-sync",
    help: "Non-canonical replay path; keep off unless intentionally used.",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "worker.replayBufferDeleteSourceAfterSuccess",
    label: "Delete replay source after success",
    help: "Deletes source replay file after successful processing.",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "Source replay files are removed after processing.",
    dangerousType: "runtime",
  },
  {
    key: "worker.httpReplayTriggerEnabled",
    label: "Enable worker replay trigger HTTP",
    help: "Leave on for normal appliance replay (canonical script uses POST /replay). See docs/operator-replay-trigger-runbook.md.",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Replay trigger API will be disabled.",
    dangerousType: "runtime",
  },
  {
    key: "scoreboard.stateFile",
    label: "Scoreboard state file",
    help: "State file used by scoreboard for persisted UI state.",
    placeholder: "state.json",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Scoreboard may fail to restore or persist state.",
    dangerousType: "runtime",
  },
  {
    key: "worker.enableInstantReplayBackgroundIngest",
    label: "Enable background ingest loop",
    help: "Legacy/emergency/testing; canonical path is HTTP + save_replay_and_trigger.ps1. See docs/operator-replay-trigger-runbook.md.",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Changes replay ingest behavior path (non-canonical).",
    dangerousType: "runtime",
  },
  {
    key: "scoreboard.slideshowDir",
    label: "Scoreboard slideshow directory",
    help: "Folder with slideshow images shown on idle scoreboard.",
    placeholder: "C:\\Users\\admin\\Dropbox\\slideshow",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.replayUnavailableImage",
    label: "Replay unavailable image path",
    help: "Image shown when replay clip is unavailable.",
    placeholder: "assets/replay_unavailable.png",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.replayBufferLoadingDir",
    label: "Replay buffer loading animation directory",
    help: "Folder for replay loading indicator frames.",
    placeholder: "assets/replay_buffer_loading",
    group: "Playback and MPV",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.launcherStatusJsonPath",
    label: "Launcher status JSON path",
    help: "Status file path read by launcher/watch loops.",
    placeholder: "C:\\ReplayTrove\\launcher\\scoreboard_status.json",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.replayFileMaxAgeSeconds",
    label: "Replay file max age seconds",
    help: "Ignore stale replay files older than this age.",
    placeholder: "120",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.replayTransitionTimeoutMs",
    label: "Replay transition timeout ms",
    help: "Recovery timeout for replay transitions.",
    placeholder: "90000",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.replayEnabled",
    label: "Enable scoreboard replay",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Replay display function can be disabled.",
    dangerousType: "runtime",
  },
  {
    key: "scoreboard.slideshowEnabled",
    label: "Enable slideshow",
    help: "Allow idle slideshow mode.",
    group: "Playback and MPV",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.mpvEmbedded",
    label: "Use embedded MPV playback",
    help: "Embed MPV inside scoreboard UI.",
    group: "Playback and MPV",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.obsStatusIndicatorEnabled",
    label: "Show OBS status indicator",
    help: "Display OBS availability status on scoreboard.",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.obsWebsocketHost",
    label: "Scoreboard OBS websocket host",
    help: "OBS websocket host used by scoreboard health and status checks.",
    placeholder: "localhost",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.obsWebsocketPort",
    label: "Scoreboard OBS websocket port",
    help: "OBS websocket port used by scoreboard health and status checks.",
    placeholder: "4455",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "Scoreboard OBS connectivity checks can fail if port is wrong.",
    dangerousType: "conflict",
  },
  {
    key: "scoreboard.obsWebsocketPassword",
    label: "Scoreboard OBS websocket password",
    help: "OBS websocket password used by scoreboard checks and replay save calls.",
    placeholder: "",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "OBS websocket checks and replay save can fail if password is wrong.",
    dangerousType: "runtime",
  },
  {
    key: "scoreboard.encoderStatusEnabled",
    label: "Show encoder status indicator",
    help: "Display encoder status panel on scoreboard.",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "scoreboard.replayVideoPath",
    label: "Scoreboard replay video path",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Replay playback may fail to locate video.",
    dangerousType: "runtime",
  },
  {
    key: "launcher.obsDir",
    label: "Launcher OBS directory",
    help: "Directory used to locate OBS executable.",
    placeholder: "C:\\Program Files\\obs-studio\\bin\\64bit",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "Launcher may fail to locate OBS binaries.",
    dangerousType: "startup",
  },
  {
    key: "obsFfmpegPaths.mpvPath",
    label: "MPV executable path",
    help: "Used for scoreboard / replay playback when MPV is enabled.",
    group: "Playback and MPV",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Replay playback may fail to launch.",
    dangerousType: "startup",
  },
  {
    key: "launcher.enableControlApp",
    label: "Start control app from launcher",
    help: "Enable startup of control app (Companion/StreamDeck).",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Control app will not start from launcher.",
    dangerousType: "startup",
  },
  {
    key: "obsFfmpegPaths.obsExecutable",
    label: "OBS executable path",
    help: "Full path to obs64.exe (or equivalent).",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "OBS may fail to start or restart.",
    dangerousType: "startup",
  },
  {
    key: "launcher.controlAppProcessName",
    label: "Control app process name",
    help: "Process name used for readiness/process checks.",
    placeholder: "Companion",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.readinessObsSec",
    label: "Readiness timeout for OBS seconds",
    help: "How long launcher waits for OBS readiness.",
    placeholder: "120",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.readinessPythonSec",
    label: "Readiness timeout for Python apps seconds",
    help: "How long launcher waits for worker/scoreboard readiness.",
    placeholder: "90",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.focusRetryMs",
    label: "Focus retry milliseconds",
    help: "Delay between scoreboard focus retries.",
    placeholder: "500",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "obsFfmpegPaths.ffmpegPath",
    label: "FFmpeg executable path",
    help: "Must be ffmpeg.exe (not mpv). Also used for encoder device discovery (Refresh device list on Encoder tab).",
    group: "Replay Processing",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Clip processing and remux can fail.",
    dangerousType: "runtime",
  },
  {
    key: "encoder.uvcVideoDevice",
    label: "UVC / DirectShow video device",
    help: "Use the dropdown (after Refresh device list) or type the exact ffmpeg DirectShow name. Leave empty to use encoder .env UVC_VIDEO_DEVICE.",
    group: "Encoder (UVC)",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "encoder.uvcAudioDevice",
    label: "UVC / DirectShow audio device",
    help: "Use the dropdown (after Refresh) or type the exact name. Leave empty to use encoder .env UVC_AUDIO_DEVICE.",
    group: "Encoder (UVC)",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.scoreboardStatusWatch",
    label: "Enable scoreboard status watch loop",
    help: "Controls screensaver watch loop behavior.",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.pauseOnError",
    label: "Pause launcher on error",
    help: "Pause on startup failures for interactive troubleshooting.",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.debugMode",
    label: "Launcher debug mode",
    help: "Use visible python.exe windows instead of pythonw.exe.",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "launcher.enableWorker",
    label: "Start Worker from launcher",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Worker app will not start from launcher.",
    dangerousType: "startup",
  },
  {
    key: "launcher.enableScoreboard",
    label: "Start Scoreboard from launcher",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Scoreboard app will not start from launcher.",
    dangerousType: "startup",
  },
  {
    key: "launcher.enableObs",
    label: "Start OBS from launcher",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "OBS process will not start from launcher.",
    dangerousType: "startup",
  },
  {
    key: "launcher.workerDir",
    label: "Launcher worker directory",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Launcher may fail to find Worker app.",
    dangerousType: "startup",
  },
  {
    key: "launcher.scoreboardDir",
    label: "Launcher scoreboard directory",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Launcher may fail to find Scoreboard app.",
    dangerousType: "startup",
  },
  {
    key: "launcher.encoderDir",
    label: "Launcher encoder directory",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "Launcher may fail to find Encoder app.",
    dangerousType: "startup",
  },
  {
    key: "launcher.controlAppExe",
    label: "Control app executable",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Control app may fail to start.",
    dangerousType: "startup",
  },
  {
    key: "launcher.scoreboardStatusPollSec",
    label: "Scoreboard status poll interval",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "general.replayTroveRoot",
    label: "ReplayTrove root directory",
    help: "Base path for the appliance install; many other paths are relative to this.",
    placeholder: "C:\\ReplayTrove",
    group: "Paths and Storage",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Most path-based services may resolve files incorrectly.",
    dangerousType: "runtime",
  },
  {
    key: "general.timezone",
    label: "Timezone (IANA)",
    help: "Example: America/New_York or UTC.",
    placeholder: "UTC",
    group: "General",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "general.operatorMode",
    label: "Operator mode",
    help: "Appliance vs development behavior for tooling and defaults.",
    group: "General",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "May change how scripts and services expect the machine to be used.",
    dangerousType: "runtime",
  },
  {
    key: "webApp.enabled",
    label: "Enable bundled web app",
    help: "When on, the stack may start the operator web UI on the configured port.",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Web UI will not start from unified config when disabled.",
    dangerousType: "startup",
  },
  {
    key: "webApp.port",
    label: "Web app port",
    group: "Launcher Startup",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "Web app may fail if port conflicts.",
    dangerousType: "conflict",
  },
  {
    key: "cleaner.enabled",
    label: "Cleaner enabled",
    help: "Whether log cleanup / retention tasks run.",
    group: "Status and Monitoring",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: true,
    surfacedInForm: true,
    impact: "Logs may accumulate if disabled.",
    dangerousType: "runtime",
  },
  {
    key: "cleaner.maxLogAgeDays",
    label: "Max log age (days)",
    help: "Logs older than this may be pruned when cleaner runs.",
    placeholder: "14",
    group: "Timing and Retries",
    restartRequired: true,
    hotReloadCandidate: true,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "storage.s3PreviewPrefix",
    label: "S3 preview key prefix",
    help: "Prefix for preview objects in object storage (if used by your deployment).",
    placeholder: "previews",
    group: "Integrations",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "storage.supabaseBookingsTable",
    label: "Supabase bookings table name",
    help: "Table used for booking-related integration.",
    placeholder: "bookings",
    group: "Integrations",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "picklePlanner.enabled",
    label: "Pickle Planner enabled",
    help: "Enable Pickle Planner integration features.",
    group: "Integrations",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "picklePlanner.baseUrl",
    label: "Pickle Planner base URL",
    help: "HTTPS base URL for the Pickle Planner API.",
    placeholder: "https://example.com",
    group: "Integrations",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: false,
    dangerous: false,
    surfacedInForm: true,
  },
  {
    key: "schemaVersion",
    label: "Config schema version",
    help: "Unified settings schema revision. Usually matches the bundled default; change only if you know migrations apply.",
    placeholder: "1",
    group: "General",
    restartRequired: true,
    hotReloadCandidate: false,
    advanced: true,
    dangerous: true,
    surfacedInForm: true,
    impact: "Mismatch can cause validation or migration issues on load.",
    dangerousType: "runtime",
  },
];

function App() {
  const [config, setConfig] = useState<AppConfig>(cloneDefault());
  const [status, setStatus] = useState<string>("Loading config from API...");
  const [active, setActive] = useState<SectionKey>("general");
  const [validationIssues, setValidationIssues] = useState<
    Array<{ severity: string; code: string; message: string; path?: string }>
  >([]);
  const [diagnostics, setDiagnostics] = useState<{
    configPath: string;
    found: boolean;
    schemaVersion: number | null;
    migrated: boolean;
    validationOk: boolean;
    backupPath: string | null;
  }>({
    configPath: "",
    found: false,
    schemaVersion: null,
    migrated: false,
    validationOk: false,
    backupPath: null,
  });
  const [lastSavedAt, setLastSavedAt] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [pendingDangerConfirm, setPendingDangerConfirm] = useState<
    { key: string; oldValue: unknown; newValue: unknown; meta?: FieldMeta }[]
  >([]);
  const [saveSummary, setSaveSummary] = useState<{
    changed: string[];
    restart: string[];
    dangerous: string[];
  } | null>(null);
  const [reloadSummary, setReloadSummary] = useState<{
    ok: boolean;
    message: string;
    commandId?: string;
    correlationId?: string;
  } | null>(null);
  const [reloadStatusArtifact, setReloadStatusArtifact] = useState<{
    found: boolean;
    statusPath?: string;
    status?: {
      timestamp?: string;
      correlation_id?: string;
      status?: string;
      applied_fields?: string[];
      rejection_reason?: string;
      schema_version?: number | null;
    };
  } | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [encoderDiscovery, setEncoderDiscovery] = useState<{
    loading: boolean;
    error: string | null;
    devicesOk: boolean;
    videoDevices: { name: string; devicePath?: string }[];
    audioDevices: { name: string }[];
    ffmpegPathUsed?: string;
    parseNote?: string;
  } | null>(null);
  const encoderDevicesAutoRefreshRef = useRef(false);
  const [showScoreboardObsPassword, setShowScoreboardObsPassword] =
    useState<boolean>(false);
  const metaByKey = useMemo(
    () => new Map(FIELD_META.map((m) => [m.key, m])),
    [],
  );
  const getMeta = (key: string): FieldMeta => {
    const meta = metaByKey.get(key);
    if (!meta) {
      return {
        key,
        label: key,
        group: "Status and Monitoring",
        restartRequired: true,
        hotReloadCandidate: false,
        advanced: true,
        dangerous: false,
        surfacedInForm: false,
      };
    }
    return meta;
  };

  const surfacedFormFields = useMemo(
    () =>
      [
        "worker.httpReplayTriggerHost",
        "worker.httpReplayTriggerPort",
        "worker.httpReplayTriggerTimeoutSec",
        "worker.watchFolder",
        "worker.instantReplaySource",
        "worker.longClipsFolder",
        "worker.workerStatusJsonPath",
        "worker.workerConcurrency",
        "worker.uploadRetries",
        "worker.uploadRetryDelaySeconds",
        "worker.replayScoreboardAutoSyncIntervalSeconds",
        "worker.httpReplayTriggerEnabled",
        "worker.enableInstantReplayBackgroundIngest",
        "worker.enableReplayScoreboardAutoSync",
        "worker.replayBufferDeleteSourceAfterSuccess",
        "scoreboard.stateFile",
        "scoreboard.replayVideoPath",
        "scoreboard.slideshowDir",
        "scoreboard.replayUnavailableImage",
        "scoreboard.replayBufferLoadingDir",
        "scoreboard.launcherStatusJsonPath",
        "scoreboard.replayFileMaxAgeSeconds",
        "scoreboard.replayTransitionTimeoutMs",
        "scoreboard.replayEnabled",
        "scoreboard.slideshowEnabled",
        "scoreboard.mpvEmbedded",
        "scoreboard.obsWebsocketHost",
        "scoreboard.obsWebsocketPort",
        "scoreboard.obsWebsocketPassword",
        "scoreboard.obsStatusIndicatorEnabled",
        "scoreboard.encoderStatusEnabled",
        "launcher.workerDir",
        "launcher.scoreboardDir",
        "launcher.encoderDir",
        "launcher.obsDir",
        "launcher.enableWorker",
        "launcher.enableScoreboard",
        "launcher.enableObs",
        "launcher.enableControlApp",
        "launcher.controlAppExe",
        "launcher.controlAppProcessName",
        "launcher.readinessObsSec",
        "launcher.readinessPythonSec",
        "launcher.focusRetryMs",
        "launcher.scoreboardStatusPollSec",
        "launcher.scoreboardStatusWatch",
        "launcher.pauseOnError",
        "launcher.debugMode",
        "encoder.uvcVideoDevice",
        "encoder.uvcAudioDevice",
        "obsFfmpegPaths.ffmpegPath",
        "obsFfmpegPaths.obsExecutable",
        "obsFfmpegPaths.mpvPath",
        "general.replayTroveRoot",
        "general.timezone",
        "general.operatorMode",
        "webApp.enabled",
        "webApp.port",
        "cleaner.enabled",
        "cleaner.maxLogAgeDays",
        "storage.s3PreviewPrefix",
        "storage.supabaseBookingsTable",
        "picklePlanner.enabled",
        "picklePlanner.baseUrl",
        "schemaVersion",
      ] as const,
    [],
  );

  React.useEffect(() => {
    void loadFromApi();
    void loadScoreboardReloadStatus();
    void loadSystemStatus();
    const draft = localStorage.getItem(STORAGE_KEY);
    if (draft) {
      setStatus("Loaded disk config. Draft data is available locally.");
    }
  }, []);

  const refreshEncoderDevices = useCallback(async () => {
    setEncoderDiscovery((prev) => ({
      loading: true,
      error: null,
      devicesOk: prev?.devicesOk ?? false,
      videoDevices: prev?.videoDevices ?? [],
      audioDevices: prev?.audioDevices ?? [],
      ffmpegPathUsed: prev?.ffmpegPathUsed,
      parseNote: prev?.parseNote,
    }));
    try {
      const res = await fetch(`${API_BASE}/api/encoder/devices`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok || !data?.ok) {
        setEncoderDiscovery((prev) => ({
          loading: false,
          error: String(data?.message ?? data?.error ?? `HTTP ${res.status}`),
          devicesOk: false,
          videoDevices: prev?.videoDevices ?? [],
          audioDevices: prev?.audioDevices ?? [],
          ffmpegPathUsed: prev?.ffmpegPathUsed,
          parseNote: prev?.parseNote,
        }));
        return;
      }
      setEncoderDiscovery({
        loading: false,
        error: null,
        devicesOk: Boolean(data.devicesOk),
        videoDevices: Array.isArray(data.videoDevices) ? data.videoDevices : [],
        audioDevices: Array.isArray(data.audioDevices) ? data.audioDevices : [],
        ffmpegPathUsed: data.ffmpegPathUsed ? String(data.ffmpegPathUsed) : undefined,
        parseNote: data.parseNote ? String(data.parseNote) : undefined,
      });
    } catch (e) {
      setEncoderDiscovery((prev) => ({
        loading: false,
        error: String(e),
        devicesOk: false,
        videoDevices: prev?.videoDevices ?? [],
        audioDevices: prev?.audioDevices ?? [],
        ffmpegPathUsed: prev?.ffmpegPathUsed,
        parseNote: prev?.parseNote,
      }));
    }
  }, []);

  useEffect(() => {
    if (active !== "encoder") return;
    if (encoderDevicesAutoRefreshRef.current) return;
    encoderDevicesAutoRefreshRef.current = true;
    void refreshEncoderDevices();
  }, [active, refreshEncoderDevices]);

  async function loadSystemStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/system/status`);
      const data = await res.json();
      if (!res.ok || !data?.ok) {
        setSystemStatus(null);
        return;
      }
      setSystemStatus(data.status as SystemStatus);
    } catch {
      setSystemStatus(null);
    }
  }

  function sourceBadge(source: "unified" | "env" | "default" | string) {
    return (
      <span style={{ background: "#efefef", borderRadius: 6, padding: "1px 6px", fontSize: 11 }}>
        {source}
      </span>
    );
  }

  React.useEffect(() => {
    const missing = surfacedFormFields.filter((k) => {
      const m = metaByKey.get(k);
      return !m || !m.surfacedInForm;
    });
    if (missing.length > 0) {
      console.warn("Control Center metadata missing for surfaced fields:", missing);
    }
    const missingPresentation = surfacedFormFields.filter((k) => {
      const m = metaByKey.get(k);
      return !m || !m.label || !m.label.trim();
    });
    if (missingPresentation.length > 0) {
      console.warn("Control Center presentation metadata missing labels:", missingPresentation);
    }
  }, [metaByKey, surfacedFormFields]);

  const [jsonDraft, setJsonDraft] = useState("");
  useEffect(() => {
    setJsonDraft(JSON.stringify(config[active], null, 2));
  }, [active, config]);

  function setSection(section: SectionKey, nextValue: unknown) {
    setConfig((prev) => ({ ...prev, [section]: nextValue } as AppConfig));
  }

  function updateWorker<K extends keyof AppConfig["worker"]>(
    key: K,
    value: AppConfig["worker"][K],
  ) {
    setSection("worker", { ...config.worker, [key]: value });
  }

  function updateScoreboard<K extends keyof AppConfig["scoreboard"]>(
    key: K,
    value: AppConfig["scoreboard"][K],
  ) {
    setSection("scoreboard", { ...config.scoreboard, [key]: value });
  }

  function updateLauncher<K extends keyof AppConfig["launcher"]>(
    key: K,
    value: AppConfig["launcher"][K],
  ) {
    setSection("launcher", { ...config.launcher, [key]: value });
  }

  function updateEncoder<K extends keyof AppConfig["encoder"]>(
    key: K,
    value: AppConfig["encoder"][K],
  ) {
    setSection("encoder", { ...config.encoder, [key]: value });
  }

  function updateGeneral<K extends keyof AppConfig["general"]>(
    key: K,
    value: AppConfig["general"][K],
  ) {
    setSection("general", { ...config.general, [key]: value });
  }

  function updateWebApp<K extends keyof AppConfig["webApp"]>(
    key: K,
    value: AppConfig["webApp"][K],
  ) {
    setSection("webApp", { ...config.webApp, [key]: value });
  }

  function updateCleaner<K extends keyof AppConfig["cleaner"]>(
    key: K,
    value: AppConfig["cleaner"][K],
  ) {
    setSection("cleaner", { ...config.cleaner, [key]: value });
  }

  function updateObsFfmpeg<K extends keyof AppConfig["obsFfmpegPaths"]>(
    key: K,
    value: AppConfig["obsFfmpegPaths"][K],
  ) {
    setSection("obsFfmpegPaths", { ...config.obsFfmpegPaths, [key]: value });
  }

  function updateStorage<K extends keyof AppConfig["storage"]>(
    key: K,
    value: AppConfig["storage"][K],
  ) {
    setSection("storage", { ...config.storage, [key]: value });
  }

  function updatePicklePlanner<K extends keyof AppConfig["picklePlanner"]>(
    key: K,
    value: AppConfig["picklePlanner"][K],
  ) {
    setSection("picklePlanner", { ...config.picklePlanner, [key]: value });
  }

  function applyJsonDraft(section: SectionKey) {
    const parsed = safeParseJson<unknown>(jsonDraft);
    if (parsed === null) {
      setStatus(`Invalid JSON in ${SECTION_LABELS[section]} section.`);
      return;
    }
    setConfig((prev) => ({ ...prev, [section]: parsed } as AppConfig));
    setStatus(`Updated ${SECTION_LABELS[section]} in memory.`);
  }

  async function loadFromApi() {
    try {
      const res = await fetch(`${API_BASE}/api/config`);
      const data = await res.json();
      if (!res.ok || !data?.ok) {
        setStatus(`Failed to load config: ${data?.message ?? res.statusText}`);
        return;
      }
      setConfig(data.config as AppConfig);
      setDiagnostics({
        configPath: String(data.configPath ?? ""),
        found: Boolean(data.found),
        schemaVersion:
          typeof data.schemaVersion === "number" ? data.schemaVersion : null,
        migrated: Boolean(data.migrated),
        validationOk: Boolean(data.validation?.ok),
        backupPath: null,
      });
      setValidationIssues((data.validation?.issues ?? []) as typeof validationIssues);
      setStatus("Loaded config from disk.");
    } catch (err) {
      setStatus(`Failed to load config API: ${String(err)}`);
    }
  }

  async function validateCurrent() {
    const shape = AppConfigSchema.safeParse(config);
    if (!shape.success) {
      const issue = shape.error.issues[0];
      setStatus(
        `Client validation failed: ${issue.message}${issue.path.length ? ` @ ${issue.path.join(".")}` : ""}`,
      );
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/config/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      const data = await res.json();
      setValidationIssues((data.issues ?? []) as typeof validationIssues);
      setDiagnostics((prev) => ({
        ...prev,
        schemaVersion:
          typeof data.schemaVersion === "number" ? data.schemaVersion : prev.schemaVersion,
        migrated: Boolean(data.migrated),
        validationOk: Boolean(data.ok),
      }));
      if (data.ok) {
        setStatus(
          data.warnings > 0
            ? `Validation passed with ${data.warnings} warning(s).`
            : "Validation passed.",
        );
      } else {
        setStatus(`Validation failed with ${data.errors ?? "unknown"} error(s).`);
      }
    } catch (err) {
      setStatus(`Validation API failed: ${String(err)}`);
    }
  }

  function saveLocal() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config, null, 2));
    setStatus("Saved to browser local storage.");
  }

  function loadLocal() {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      setStatus("No local storage save found.");
      return;
    }
    const parsed = safeParseJson<AppConfig>(raw);
    if (!parsed) {
      setStatus("Saved local config is invalid JSON.");
      return;
    }
    setConfig(parsed);
    setStatus("Loaded draft from browser local storage.");
  }

  function resetSection(section: SectionKey) {
    const defaults = cloneDefault();
    setConfig((prev) => ({ ...prev, [section]: defaults[section] }));
    setStatus(`Reset ${SECTION_LABELS[section]} to defaults.`);
  }

  function exportFile() {
    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/config/export`);
        if (!res.ok) {
          setStatus(`Export failed: ${res.statusText}`);
          return;
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "settings.export.json";
        a.click();
        URL.revokeObjectURL(a.href);
        setStatus("Exported config from API.");
      } catch (err) {
        setStatus(`Export failed: ${String(err)}`);
      }
    })();
  }

  function importFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = safeParseJson<AppConfig>(String(reader.result ?? ""));
      if (!parsed) {
        setStatus("Import failed: invalid JSON.");
        return;
      }
      void (async () => {
        try {
          const res = await fetch(`${API_BASE}/api/config/validate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config: parsed }),
          });
          const data = await res.json();
          setValidationIssues((data.issues ?? []) as typeof validationIssues);
          if (!data.ok) {
            setStatus(
              `Import rejected: ${data.errors ?? "unknown"} validation error(s).`,
            );
            return;
          }
          setConfig(parsed);
          setDiagnostics((prev) => ({
            ...prev,
            schemaVersion:
              typeof data.schemaVersion === "number" ? data.schemaVersion : prev.schemaVersion,
            migrated: Boolean(data.migrated),
            validationOk: true,
          }));
          setStatus("Imported config accepted and loaded into draft.");
        } catch (err) {
          setStatus(`Import validation failed: ${String(err)}`);
        }
      })();
    };
    reader.readAsText(file);
  }

  async function saveToDisk(skipDangerConfirm = false) {
    await validateCurrent();
    const loaded = await fetch(`${API_BASE}/api/config`);
    const loadedJson = await loaded.json();
    const existing = loadedJson?.config ?? {};
    const changed = FIELD_META.filter(
      (m) => JSON.stringify(getByPath(existing, m.key)) !== JSON.stringify(getByPath(config, m.key)),
    ).map((m) => ({
      key: m.key,
      oldValue: getByPath(existing, m.key),
      newValue: getByPath(config, m.key),
      meta: m,
    }));
    const dangerous = changed.filter((c) => c.meta?.dangerous);
    if (!skipDangerConfirm && dangerous.length > 0 && pendingDangerConfirm.length === 0) {
      setPendingDangerConfirm(dangerous);
      setStatus("Confirm dangerous setting changes before save.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/config/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      const data = await res.json();
      setValidationIssues((data.issues ?? []) as typeof validationIssues);
      if (!res.ok || !data.ok) {
        setStatus(data.message ?? "Save failed.");
        return;
      }
      const savedAt = new Date().toLocaleString();
      setLastSavedAt(savedAt);
      const changedKeys = changed.map((c) => c.key);
      const restartKeys = changed.filter((c) => c.meta?.restartRequired).map((c) => c.key);
      const dangerousKeys = changed.filter((c) => c.meta?.dangerous).map((c) => c.key);
      setSaveSummary({ changed: changedKeys, restart: restartKeys, dangerous: dangerousKeys });
      setPendingDangerConfirm([]);
      setDiagnostics((prev) => ({
        ...prev,
        configPath: String(data.configPath ?? prev.configPath),
        schemaVersion:
          typeof data.effectiveSchemaVersion === "number"
            ? data.effectiveSchemaVersion
            : prev.schemaVersion,
        migrated: Boolean(data.migrated),
        validationOk: true,
        backupPath: data.backupPath ? String(data.backupPath) : null,
      }));
      setStatus("Config saved safely to disk.");
    } catch (err) {
      setStatus(`Save request failed: ${String(err)}`);
    }
  }

  async function applySafeLiveSettingsToScoreboard() {
    try {
      const res = await fetch(`${API_BASE}/api/scoreboard/reload-safe-settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok || !data?.ok) {
        setReloadSummary({
          ok: false,
          message: data?.message ?? "Failed to queue reload command.",
        });
        return;
      }
      setReloadSummary({
        ok: true,
        message:
          "Reload command queued (not yet confirmed applied). Only scoreboard monitoring intervals are eligible for live apply; restart remains safest for all other settings.",
        commandId: String(data.commandId ?? ""),
        correlationId: String(data.correlationId ?? ""),
      });
      await loadScoreboardReloadStatus();
    } catch (err) {
      setReloadSummary({
        ok: false,
        message: `Failed to queue reload command: ${String(err)}`,
      });
    }
  }

  async function loadScoreboardReloadStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/scoreboard/reload-safe-settings-status`);
      const data = await res.json();
      if (!res.ok || !data?.ok) {
        return;
      }
      setReloadStatusArtifact({
        found: Boolean(data.found),
        statusPath: String(data.statusPath ?? ""),
        status: data.status ?? undefined,
      });
    } catch {
      // keep UI quiet on status read misses
    }
  }

  const sectionKeys = Object.keys(SECTION_LABELS) as SectionKey[];

  function renderEncoderForm() {
    const vids = encoderDiscovery?.videoDevices ?? [];
    const auds = encoderDiscovery?.audioDevices ?? [];
    const currentVid = config.encoder.uvcVideoDevice;
    const currentAud = config.encoder.uvcAudioDevice;
    const showUnlistedVid = currentVid !== "" && !vids.some((d) => d.name === currentVid);
    const showUnlistedAud = currentAud !== "" && !auds.some((d) => d.name === currentAud);
    return (
      <div>
        <p style={{ fontSize: 13, color: "#444", maxWidth: 720 }}>
          Names must match ffmpeg device listing (Windows: DirectShow). Unified values override encoder{" "}
          <code>.env</code> when non-empty. Save config and restart the encoder for changes to apply.
        </p>
        <div style={{ marginBottom: 16 }}>
          <button type="button" onClick={() => void refreshEncoderDevices()} disabled={encoderDiscovery?.loading}>
            {encoderDiscovery?.loading ? "Refreshing…" : "Refresh device list"}
          </button>
          {encoderDiscovery?.error ? (
            <div style={{ color: "#a40000", marginTop: 8 }}>{encoderDiscovery.error}</div>
          ) : null}
          {encoderDiscovery && !encoderDiscovery.loading && !encoderDiscovery.devicesOk ? (
            <div style={{ color: "#a65b00", marginTop: 8 }}>
              No devices were parsed. Confirm FFmpeg path and drivers.{" "}
              {encoderDiscovery.parseNote ? `(${encoderDiscovery.parseNote})` : null}
            </div>
          ) : null}
        </div>
        <div style={{ marginBottom: 16 }}>
          {fieldLabel("FFmpeg path (for discovery)", getMeta("obsFfmpegPaths.ffmpegPath").help)}
          {looksLikeMpvExecutablePath(config.obsFfmpegPaths.ffmpegPath) ? (
            <div style={{ color: "#a40000", marginBottom: 8, fontSize: 13, maxWidth: 640 }}>
              This path is MPV. Set MPV under OBS / FFmpeg / Paths, and put your real{" "}
              <code>ffmpeg.exe</code> here so Refresh device list and the encoder work.
            </div>
          ) : null}
          <input
            style={{ width: "100%", maxWidth: 640 }}
            value={config.obsFfmpegPaths.ffmpegPath}
            onChange={(e) =>
              setConfig((prev) => ({
                ...prev,
                obsFfmpegPaths: { ...prev.obsFfmpegPaths, ffmpegPath: e.target.value },
              }))
            }
          />
          {encoderDiscovery?.ffmpegPathUsed ? (
            <div style={{ fontSize: 11, color: "#666", marginTop: 4 }}>
              Last discovery run used: {encoderDiscovery.ffmpegPathUsed}
            </div>
          ) : null}
        </div>
        <div style={{ marginBottom: 16 }}>
          {fieldLabel(getMeta("encoder.uvcVideoDevice").label, getMeta("encoder.uvcVideoDevice").help)}
          <div style={{ fontSize: 12, color: "#555", marginBottom: 6 }}>Discovered devices (from FFmpeg)</div>
          <select
            style={{ width: "100%", maxWidth: 640, marginBottom: 8, display: "block" }}
            value={currentVid}
            onChange={(e) => updateEncoder("uvcVideoDevice", e.target.value)}
          >
            <option value="">(Empty — use encoder .env / default)</option>
            {showUnlistedVid ? (
              <option value={currentVid}>
                Current (not in last discovery): {currentVid.length > 72 ? `${currentVid.slice(0, 72)}…` : currentVid}
              </option>
            ) : null}
            {vids.map((d, i) => (
              <option key={`vid-${i}-${d.name}`} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
          <div style={{ fontSize: 12, color: "#555", marginBottom: 6 }}>Exact video device string (saved to config)</div>
          <input
            style={{ width: "100%", maxWidth: 640 }}
            value={config.encoder.uvcVideoDevice}
            onChange={(e) => updateEncoder("uvcVideoDevice", e.target.value)}
            placeholder="Must match ffmpeg DirectShow name exactly"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          {fieldLabel(getMeta("encoder.uvcAudioDevice").label, getMeta("encoder.uvcAudioDevice").help)}
          <div style={{ fontSize: 12, color: "#555", marginBottom: 6 }}>Discovered devices (from FFmpeg)</div>
          <select
            style={{ width: "100%", maxWidth: 640, marginBottom: 8, display: "block" }}
            value={currentAud}
            onChange={(e) => updateEncoder("uvcAudioDevice", e.target.value)}
          >
            <option value="">(Empty — use encoder .env / default)</option>
            {showUnlistedAud ? (
              <option value={currentAud}>
                Current (not in last discovery): {currentAud.length > 72 ? `${currentAud.slice(0, 72)}…` : currentAud}
              </option>
            ) : null}
            {auds.map((d, i) => (
              <option key={`aud-${i}-${d.name}`} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
          <div style={{ fontSize: 12, color: "#555", marginBottom: 6 }}>Exact audio device string (saved to config)</div>
          <input
            style={{ width: "100%", maxWidth: 640 }}
            value={config.encoder.uvcAudioDevice}
            onChange={(e) => updateEncoder("uvcAudioDevice", e.target.value)}
            placeholder="Must match ffmpeg DirectShow name exactly"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
      </div>
    );
  }

  function renderGeneralForm() {
    const meta = (key: string) => getMeta(key);
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div style={{ gridColumn: "1 / -1" }}>
          {fieldLabel(meta("general.replayTroveRoot").label, meta("general.replayTroveRoot").help)}
          <input
            style={{ width: "100%", maxWidth: 720 }}
            placeholder={meta("general.replayTroveRoot").placeholder}
            value={config.general.replayTroveRoot}
            onChange={(e) => updateGeneral("replayTroveRoot", e.target.value)}
          />
        </div>
        <div>
          {fieldLabel(meta("general.timezone").label, meta("general.timezone").help)}
          <input
            style={{ width: "100%", maxWidth: 480 }}
            placeholder={meta("general.timezone").placeholder}
            value={config.general.timezone}
            onChange={(e) => updateGeneral("timezone", e.target.value)}
          />
        </div>
        <div>
          {fieldLabel(meta("general.operatorMode").label, meta("general.operatorMode").help)}
          <select
            style={{ width: "100%", maxWidth: 320, padding: 8 }}
            value={config.general.operatorMode}
            onChange={(e) =>
              updateGeneral("operatorMode", e.target.value as AppConfig["general"]["operatorMode"])
            }
          >
            <option value="appliance">appliance</option>
            <option value="development">development</option>
          </select>
        </div>
      </div>
    );
  }

  function renderWebAppForm() {
    const meta = (key: string) => getMeta(key);
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>
          <label style={{ display: "block" }}>
            <input
              type="checkbox"
              checked={config.webApp.enabled}
              onChange={(e) => updateWebApp("enabled", e.target.checked)}
            />{" "}
            {meta("webApp.enabled").label}
          </label>
          {fieldHelp(meta("webApp.enabled").help)}
        </div>
        <div>
          {fieldLabel(meta("webApp.port").label, meta("webApp.port").help)}
          <input
            type="number"
            min={1}
            max={65535}
            style={{ width: "100%", maxWidth: 240 }}
            value={config.webApp.port}
            onChange={(e) => updateWebApp("port", Number(e.target.value) || 1)}
          />
        </div>
      </div>
    );
  }

  function renderCleanerForm() {
    const meta = (key: string) => getMeta(key);
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>
          <label style={{ display: "block" }}>
            <input
              type="checkbox"
              checked={config.cleaner.enabled}
              onChange={(e) => updateCleaner("enabled", e.target.checked)}
            />{" "}
            {meta("cleaner.enabled").label}
          </label>
          {fieldHelp(meta("cleaner.enabled").help)}
        </div>
        <div>
          {fieldLabel(meta("cleaner.maxLogAgeDays").label, meta("cleaner.maxLogAgeDays").help)}
          <input
            type="number"
            min={1}
            style={{ width: "100%", maxWidth: 240 }}
            value={config.cleaner.maxLogAgeDays}
            onChange={(e) => updateCleaner("maxLogAgeDays", Math.max(1, Number(e.target.value) || 1))}
          />
        </div>
      </div>
    );
  }

  function renderObsFfmpegForm() {
    const meta = (key: string) => getMeta(key);
    return (
      <div>
        <p style={{ fontSize: 13, color: "#444", maxWidth: 720 }}>
          Used by launcher, worker, scoreboard, and encoder device discovery. Save config and restart
          affected services after changes.
        </p>
        <div style={{ marginBottom: 16 }}>
          {fieldLabel(meta("obsFfmpegPaths.obsExecutable").label, meta("obsFfmpegPaths.obsExecutable").help)}
          <input
            style={{ width: "100%", maxWidth: 720 }}
            value={config.obsFfmpegPaths.obsExecutable}
            onChange={(e) => updateObsFfmpeg("obsExecutable", e.target.value)}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          {fieldLabel(meta("obsFfmpegPaths.ffmpegPath").label, meta("obsFfmpegPaths.ffmpegPath").help)}
          {looksLikeMpvExecutablePath(config.obsFfmpegPaths.ffmpegPath) ? (
            <div style={{ color: "#a40000", marginBottom: 8, fontSize: 13, maxWidth: 720 }}>
              This path is MPV. Use the MPV field below for playback; this field must be{" "}
              <code>ffmpeg.exe</code>.
            </div>
          ) : null}
          <input
            style={{ width: "100%", maxWidth: 720 }}
            value={config.obsFfmpegPaths.ffmpegPath}
            onChange={(e) => updateObsFfmpeg("ffmpegPath", e.target.value)}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          {fieldLabel(meta("obsFfmpegPaths.mpvPath").label, meta("obsFfmpegPaths.mpvPath").help)}
          <input
            style={{ width: "100%", maxWidth: 720 }}
            value={config.obsFfmpegPaths.mpvPath}
            onChange={(e) => updateObsFfmpeg("mpvPath", e.target.value)}
          />
        </div>
      </div>
    );
  }

  function renderStorageForm() {
    const meta = (key: string) => getMeta(key);
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>
          {fieldLabel(meta("storage.s3PreviewPrefix").label, meta("storage.s3PreviewPrefix").help)}
          <input
            style={{ width: "100%", maxWidth: 480 }}
            placeholder={meta("storage.s3PreviewPrefix").placeholder}
            value={config.storage.s3PreviewPrefix}
            onChange={(e) => updateStorage("s3PreviewPrefix", e.target.value)}
          />
        </div>
        <div>
          {fieldLabel(meta("storage.supabaseBookingsTable").label, meta("storage.supabaseBookingsTable").help)}
          <input
            style={{ width: "100%", maxWidth: 480 }}
            placeholder={meta("storage.supabaseBookingsTable").placeholder}
            value={config.storage.supabaseBookingsTable}
            onChange={(e) => updateStorage("supabaseBookingsTable", e.target.value)}
          />
        </div>
      </div>
    );
  }

  function renderPicklePlannerForm() {
    const meta = (key: string) => getMeta(key);
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>
          <label style={{ display: "block" }}>
            <input
              type="checkbox"
              checked={config.picklePlanner.enabled}
              onChange={(e) => updatePicklePlanner("enabled", e.target.checked)}
            />{" "}
            {meta("picklePlanner.enabled").label}
          </label>
          {fieldHelp(meta("picklePlanner.enabled").help)}
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          {fieldLabel(meta("picklePlanner.baseUrl").label, meta("picklePlanner.baseUrl").help)}
          <input
            style={{ width: "100%", maxWidth: 720 }}
            placeholder={meta("picklePlanner.baseUrl").placeholder}
            value={config.picklePlanner.baseUrl}
            onChange={(e) => updatePicklePlanner("baseUrl", e.target.value)}
          />
        </div>
      </div>
    );
  }

  function renderSchemaForm() {
    const meta = getMeta("schemaVersion");
    return (
      <div>
        {fieldLabel(meta.label, meta.help)}
        <input
          type="number"
          min={1}
          step={1}
          style={{ width: "100%", maxWidth: 200 }}
          value={config.schemaVersion}
          onChange={(e) =>
            setConfig((prev) => ({
              ...prev,
              schemaVersion: Math.max(1, Math.floor(Number(e.target.value) || 1)),
            }))
          }
        />
      </div>
    );
  }

  function renderWorkerForm() {
    const renderMeta = (key: string) => {
      const meta = getMeta(key);
      if (!meta) return null;
      return (
        <div style={{ fontSize: 12, display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
          {meta.restartRequired ? <span style={{ background: "#fff4cc", padding: "2px 6px", borderRadius: 6 }}>Restart required</span> : null}
          {meta.hotReloadCandidate ? <span style={{ background: "#e8f3ff", padding: "2px 6px", borderRadius: 6 }}>Hot-reload candidate</span> : null}
          {meta.advanced ? <span style={{ background: "#efefef", padding: "2px 6px", borderRadius: 6 }}>Advanced</span> : null}
          {meta.dangerous ? <span style={{ background: "#ffe3e3", padding: "2px 6px", borderRadius: 6 }}>Dangerous ({meta.dangerousType})</span> : null}
        </div>
      );
    };
    const meta = (key: string) => getMeta(key);
    const renderCheckbox = (
      key: string,
      checked: boolean,
      onChange: (checked: boolean) => void,
    ) => (
      <div>
        <label style={{ display: "block" }}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
          />{" "}
          {meta(key).label}
        </label>
        {fieldHelp(meta(key).help)}
        {renderMeta(key)}
      </div>
    );
    return (
      <div>
        <button onClick={() => setShowAdvanced((v) => !v)} style={{ marginBottom: 10 }}>
          {showAdvanced ? "Hide advanced settings" : "Show advanced settings"}
        </button>
        <div style={{ fontSize: 12, color: "#555", marginBottom: 10 }}>
          Advanced-only settings remain in JSON editor when not surfaced in form.
        </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>
          {fieldLabel(meta("worker.httpReplayTriggerHost").label, meta("worker.httpReplayTriggerHost").help)}
          <input placeholder={meta("worker.httpReplayTriggerHost")?.placeholder} value={config.worker.httpReplayTriggerHost} onChange={(e) => updateWorker("httpReplayTriggerHost", e.target.value)} />
          {renderMeta("worker.httpReplayTriggerHost")}
        </div>
        <div>
          {fieldLabel(meta("worker.httpReplayTriggerPort").label, meta("worker.httpReplayTriggerPort").help)}
          <input type="number" placeholder={meta("worker.httpReplayTriggerPort")?.placeholder} value={config.worker.httpReplayTriggerPort} onChange={(e) => updateWorker("httpReplayTriggerPort", Number(e.target.value) || 1)} />
          {renderMeta("worker.httpReplayTriggerPort")}
        </div>
        <div>
          {fieldLabel(meta("worker.httpReplayTriggerTimeoutSec").label, meta("worker.httpReplayTriggerTimeoutSec").help)}
          <input type="number" placeholder={meta("worker.httpReplayTriggerTimeoutSec")?.placeholder} value={config.worker.httpReplayTriggerTimeoutSec} onChange={(e) => updateWorker("httpReplayTriggerTimeoutSec", Number(e.target.value) || 1)} />
          {renderMeta("worker.httpReplayTriggerTimeoutSec")}
        </div>
        <div>
          {fieldLabel(meta("worker.watchFolder").label, meta("worker.watchFolder").help)}
          <input placeholder={meta("worker.watchFolder")?.placeholder} value={config.worker.watchFolder} onChange={(e) => updateWorker("watchFolder", e.target.value)} />
          {renderMeta("worker.watchFolder")}
        </div>
        <div>
          {fieldLabel(meta("worker.instantReplaySource").label, meta("worker.instantReplaySource").help)}
          <input placeholder={meta("worker.instantReplaySource")?.placeholder} value={config.worker.instantReplaySource} onChange={(e) => updateWorker("instantReplaySource", e.target.value)} />
          {renderMeta("worker.instantReplaySource")}
        </div>
        <div>
          {fieldLabel(meta("worker.longClipsFolder").label, meta("worker.longClipsFolder").help)}
          <input placeholder={meta("worker.longClipsFolder").placeholder} value={config.worker.longClipsFolder} onChange={(e) => updateWorker("longClipsFolder", e.target.value)} />
          {renderMeta("worker.longClipsFolder")}
        </div>
        <div>
          {fieldLabel(meta("worker.workerStatusJsonPath").label, meta("worker.workerStatusJsonPath").help)}
          <input placeholder={meta("worker.workerStatusJsonPath").placeholder} value={config.worker.workerStatusJsonPath} onChange={(e) => updateWorker("workerStatusJsonPath", e.target.value)} />
          {renderMeta("worker.workerStatusJsonPath")}
        </div>
        <div>
          {fieldLabel(meta("worker.workerConcurrency").label, meta("worker.workerConcurrency").help)}
          <input type="number" placeholder={meta("worker.workerConcurrency").placeholder} value={config.worker.workerConcurrency} onChange={(e) => updateWorker("workerConcurrency", Number(e.target.value) || 1)} />
          {renderMeta("worker.workerConcurrency")}
        </div>
        <div>
          {fieldLabel(meta("worker.uploadRetries").label, meta("worker.uploadRetries").help)}
          <input type="number" placeholder={meta("worker.uploadRetries").placeholder} value={config.worker.uploadRetries} onChange={(e) => updateWorker("uploadRetries", Number(e.target.value) || 0)} />
          {renderMeta("worker.uploadRetries")}
        </div>
        <div>
          {fieldLabel(meta("worker.uploadRetryDelaySeconds").label, meta("worker.uploadRetryDelaySeconds").help)}
          <input type="number" step="0.1" placeholder={meta("worker.uploadRetryDelaySeconds").placeholder} value={config.worker.uploadRetryDelaySeconds} onChange={(e) => updateWorker("uploadRetryDelaySeconds", Number(e.target.value) || 0)} />
          {renderMeta("worker.uploadRetryDelaySeconds")}
        </div>
        <div>
          {fieldLabel(meta("worker.replayScoreboardAutoSyncIntervalSeconds").label, meta("worker.replayScoreboardAutoSyncIntervalSeconds").help)}
          <input type="number" step="0.1" placeholder={meta("worker.replayScoreboardAutoSyncIntervalSeconds").placeholder} value={config.worker.replayScoreboardAutoSyncIntervalSeconds} onChange={(e) => updateWorker("replayScoreboardAutoSyncIntervalSeconds", Number(e.target.value) || 0)} />
          {renderMeta("worker.replayScoreboardAutoSyncIntervalSeconds")}
        </div>
        {renderCheckbox("worker.httpReplayTriggerEnabled", config.worker.httpReplayTriggerEnabled, (v) =>
          updateWorker("httpReplayTriggerEnabled", v),
        )}
        {renderCheckbox(
          "worker.enableInstantReplayBackgroundIngest",
          config.worker.enableInstantReplayBackgroundIngest,
          (v) => updateWorker("enableInstantReplayBackgroundIngest", v),
        )}
        {renderCheckbox(
          "worker.enableReplayScoreboardAutoSync",
          config.worker.enableReplayScoreboardAutoSync,
          (v) => updateWorker("enableReplayScoreboardAutoSync", v),
        )}
        {renderCheckbox(
          "worker.replayBufferDeleteSourceAfterSuccess",
          config.worker.replayBufferDeleteSourceAfterSuccess,
          (v) => updateWorker("replayBufferDeleteSourceAfterSuccess", v),
        )}
      </div>
      </div>
    );
  }

  function renderScoreboardForm() {
    const renderMeta = (key: string) => {
      const meta = getMeta(key);
      if (!meta) return null;
      return (
        <div style={{ fontSize: 12, display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
          {meta.restartRequired ? <span style={{ background: "#fff4cc", padding: "2px 6px", borderRadius: 6 }}>Restart required</span> : null}
          {meta.hotReloadCandidate ? <span style={{ background: "#e8f3ff", padding: "2px 6px", borderRadius: 6 }}>Hot-reload candidate</span> : null}
          {meta.advanced ? <span style={{ background: "#efefef", padding: "2px 6px", borderRadius: 6 }}>Advanced</span> : null}
          {meta.dangerous ? <span style={{ background: "#ffe3e3", padding: "2px 6px", borderRadius: 6 }}>Dangerous ({meta.dangerousType})</span> : null}
        </div>
      );
    };
    const renderCheckbox = (
      key: string,
      checked: boolean,
      onChange: (checked: boolean) => void,
    ) => (
      <div>
        <label style={{ display: "block" }}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
          />{" "}
          {getMeta(key).label}
        </label>
        {fieldHelp(getMeta(key).help)}
        {renderMeta(key)}
      </div>
    );
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>{fieldLabel(getMeta("scoreboard.stateFile").label, getMeta("scoreboard.stateFile").help)}<input placeholder={getMeta("scoreboard.stateFile").placeholder} value={config.scoreboard.stateFile} onChange={(e) => updateScoreboard("stateFile", e.target.value)} />{renderMeta("scoreboard.stateFile")}</div>
        <div>{fieldLabel(getMeta("scoreboard.replayVideoPath").label, getMeta("scoreboard.replayVideoPath").help)}<input placeholder={getMeta("scoreboard.replayVideoPath").placeholder} value={config.scoreboard.replayVideoPath} onChange={(e) => updateScoreboard("replayVideoPath", e.target.value)} />{renderMeta("scoreboard.replayVideoPath")}</div>
        <div>{fieldLabel(getMeta("scoreboard.slideshowDir").label, getMeta("scoreboard.slideshowDir").help)}<input placeholder={getMeta("scoreboard.slideshowDir").placeholder} value={config.scoreboard.slideshowDir} onChange={(e) => updateScoreboard("slideshowDir", e.target.value)} />{renderMeta("scoreboard.slideshowDir")}</div>
        <div>{fieldLabel(getMeta("scoreboard.replayUnavailableImage").label, getMeta("scoreboard.replayUnavailableImage").help)}<input placeholder={getMeta("scoreboard.replayUnavailableImage").placeholder} value={config.scoreboard.replayUnavailableImage} onChange={(e) => updateScoreboard("replayUnavailableImage", e.target.value)} />{renderMeta("scoreboard.replayUnavailableImage")}</div>
        <div>{fieldLabel(getMeta("scoreboard.replayBufferLoadingDir").label, getMeta("scoreboard.replayBufferLoadingDir").help)}<input placeholder={getMeta("scoreboard.replayBufferLoadingDir").placeholder} value={config.scoreboard.replayBufferLoadingDir} onChange={(e) => updateScoreboard("replayBufferLoadingDir", e.target.value)} />{renderMeta("scoreboard.replayBufferLoadingDir")}</div>
        <div>{fieldLabel(getMeta("scoreboard.launcherStatusJsonPath").label, getMeta("scoreboard.launcherStatusJsonPath").help)}<input placeholder={getMeta("scoreboard.launcherStatusJsonPath").placeholder} value={config.scoreboard.launcherStatusJsonPath} onChange={(e) => updateScoreboard("launcherStatusJsonPath", e.target.value)} />{renderMeta("scoreboard.launcherStatusJsonPath")}</div>
        <div>{fieldLabel(getMeta("scoreboard.replayFileMaxAgeSeconds").label, getMeta("scoreboard.replayFileMaxAgeSeconds").help)}<input type="number" placeholder={getMeta("scoreboard.replayFileMaxAgeSeconds").placeholder} value={config.scoreboard.replayFileMaxAgeSeconds} onChange={(e) => updateScoreboard("replayFileMaxAgeSeconds", Number(e.target.value) || 0)} />{renderMeta("scoreboard.replayFileMaxAgeSeconds")}</div>
        <div>{fieldLabel(getMeta("scoreboard.replayTransitionTimeoutMs").label, getMeta("scoreboard.replayTransitionTimeoutMs").help)}<input type="number" placeholder={getMeta("scoreboard.replayTransitionTimeoutMs").placeholder} value={config.scoreboard.replayTransitionTimeoutMs} onChange={(e) => updateScoreboard("replayTransitionTimeoutMs", Number(e.target.value) || 1000)} />{renderMeta("scoreboard.replayTransitionTimeoutMs")}</div>
        <div>{fieldLabel(getMeta("scoreboard.obsWebsocketHost").label, getMeta("scoreboard.obsWebsocketHost").help)}<input placeholder={getMeta("scoreboard.obsWebsocketHost").placeholder} value={config.scoreboard.obsWebsocketHost} onChange={(e) => updateScoreboard("obsWebsocketHost", e.target.value)} />{renderMeta("scoreboard.obsWebsocketHost")}</div>
        <div>{fieldLabel(getMeta("scoreboard.obsWebsocketPort").label, getMeta("scoreboard.obsWebsocketPort").help)}<input type="number" placeholder={getMeta("scoreboard.obsWebsocketPort").placeholder} value={config.scoreboard.obsWebsocketPort} onChange={(e) => updateScoreboard("obsWebsocketPort", Number(e.target.value) || 1)} />{renderMeta("scoreboard.obsWebsocketPort")}</div>
        <div>
          {fieldLabel(getMeta("scoreboard.obsWebsocketPassword").label, getMeta("scoreboard.obsWebsocketPassword").help)}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type={showScoreboardObsPassword ? "text" : "password"}
              placeholder={getMeta("scoreboard.obsWebsocketPassword").placeholder}
              value={config.scoreboard.obsWebsocketPassword}
              onChange={(e) => updateScoreboard("obsWebsocketPassword", e.target.value)}
            />
            <button type="button" onClick={() => setShowScoreboardObsPassword((v) => !v)}>
              {showScoreboardObsPassword ? "Hide" : "Reveal"}
            </button>
          </div>
          {renderMeta("scoreboard.obsWebsocketPassword")}
        </div>
        {renderCheckbox("scoreboard.replayEnabled", config.scoreboard.replayEnabled, (v) =>
          updateScoreboard("replayEnabled", v),
        )}
        {renderCheckbox(
          "scoreboard.slideshowEnabled",
          config.scoreboard.slideshowEnabled,
          (v) => updateScoreboard("slideshowEnabled", v),
        )}
        {renderCheckbox("scoreboard.mpvEmbedded", config.scoreboard.mpvEmbedded, (v) =>
          updateScoreboard("mpvEmbedded", v),
        )}
        {renderCheckbox(
          "scoreboard.obsStatusIndicatorEnabled",
          config.scoreboard.obsStatusIndicatorEnabled,
          (v) => updateScoreboard("obsStatusIndicatorEnabled", v),
        )}
        {renderCheckbox(
          "scoreboard.encoderStatusEnabled",
          config.scoreboard.encoderStatusEnabled,
          (v) => updateScoreboard("encoderStatusEnabled", v),
        )}
      </div>
    );
  }

  function renderLauncherForm() {
    const renderMeta = (key: string) => {
      const meta = getMeta(key);
      if (!meta) return null;
      return (
        <div style={{ fontSize: 12, display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
          {meta.restartRequired ? <span style={{ background: "#fff4cc", padding: "2px 6px", borderRadius: 6 }}>Restart required</span> : null}
          {meta.hotReloadCandidate ? <span style={{ background: "#e8f3ff", padding: "2px 6px", borderRadius: 6 }}>Hot-reload candidate</span> : null}
          {meta.advanced ? <span style={{ background: "#efefef", padding: "2px 6px", borderRadius: 6 }}>Advanced</span> : null}
          {meta.dangerous ? <span style={{ background: "#ffe3e3", padding: "2px 6px", borderRadius: 6 }}>Dangerous ({meta.dangerousType})</span> : null}
        </div>
      );
    };
    const renderCheckbox = (
      key: string,
      checked: boolean,
      onChange: (checked: boolean) => void,
    ) => (
      <div>
        <label style={{ display: "block" }}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
          />{" "}
          {getMeta(key).label}
        </label>
        {fieldHelp(getMeta(key).help)}
        {renderMeta(key)}
      </div>
    );
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
        <div>{fieldLabel(getMeta("launcher.workerDir").label, getMeta("launcher.workerDir").help)}<input placeholder={getMeta("launcher.workerDir").placeholder} value={config.launcher.workerDir} onChange={(e) => updateLauncher("workerDir", e.target.value)} />{renderMeta("launcher.workerDir")}</div>
        <div>{fieldLabel(getMeta("launcher.scoreboardDir").label, getMeta("launcher.scoreboardDir").help)}<input placeholder={getMeta("launcher.scoreboardDir").placeholder} value={config.launcher.scoreboardDir} onChange={(e) => updateLauncher("scoreboardDir", e.target.value)} />{renderMeta("launcher.scoreboardDir")}</div>
        <div>{fieldLabel(getMeta("launcher.encoderDir").label, getMeta("launcher.encoderDir").help)}<input placeholder={getMeta("launcher.encoderDir").placeholder} value={config.launcher.encoderDir} onChange={(e) => updateLauncher("encoderDir", e.target.value)} />{renderMeta("launcher.encoderDir")}</div>
        <div>{fieldLabel(getMeta("launcher.obsDir").label, getMeta("launcher.obsDir").help)}<input placeholder={getMeta("launcher.obsDir").placeholder} value={config.launcher.obsDir} onChange={(e) => updateLauncher("obsDir", e.target.value)} />{renderMeta("launcher.obsDir")}</div>
        {renderCheckbox("launcher.enableWorker", config.launcher.enableWorker, (v) =>
          updateLauncher("enableWorker", v),
        )}
        {renderCheckbox(
          "launcher.enableScoreboard",
          config.launcher.enableScoreboard,
          (v) => updateLauncher("enableScoreboard", v),
        )}
        {renderCheckbox("launcher.enableObs", config.launcher.enableObs, (v) =>
          updateLauncher("enableObs", v),
        )}
        {renderCheckbox(
          "launcher.enableControlApp",
          config.launcher.enableControlApp,
          (v) => updateLauncher("enableControlApp", v),
        )}
        <div>{fieldLabel(getMeta("launcher.controlAppExe").label, getMeta("launcher.controlAppExe").help)}<input placeholder={getMeta("launcher.controlAppExe").placeholder} value={config.launcher.controlAppExe} onChange={(e) => updateLauncher("controlAppExe", e.target.value)} />{renderMeta("launcher.controlAppExe")}</div>
        <div>{fieldLabel(getMeta("launcher.controlAppProcessName").label, getMeta("launcher.controlAppProcessName").help)}<input placeholder={getMeta("launcher.controlAppProcessName").placeholder} value={config.launcher.controlAppProcessName} onChange={(e) => updateLauncher("controlAppProcessName", e.target.value)} />{renderMeta("launcher.controlAppProcessName")}</div>
        <div>{fieldLabel(getMeta("launcher.readinessObsSec").label, getMeta("launcher.readinessObsSec").help)}<input type="number" placeholder={getMeta("launcher.readinessObsSec").placeholder} value={config.launcher.readinessObsSec} onChange={(e) => updateLauncher("readinessObsSec", Number(e.target.value) || 1)} />{renderMeta("launcher.readinessObsSec")}</div>
        <div>{fieldLabel(getMeta("launcher.readinessPythonSec").label, getMeta("launcher.readinessPythonSec").help)}<input type="number" placeholder={getMeta("launcher.readinessPythonSec").placeholder} value={config.launcher.readinessPythonSec} onChange={(e) => updateLauncher("readinessPythonSec", Number(e.target.value) || 1)} />{renderMeta("launcher.readinessPythonSec")}</div>
        <div>{fieldLabel(getMeta("launcher.focusRetryMs").label, getMeta("launcher.focusRetryMs").help)}<input type="number" placeholder={getMeta("launcher.focusRetryMs").placeholder} value={config.launcher.focusRetryMs} onChange={(e) => updateLauncher("focusRetryMs", Number(e.target.value) || 10)} />{renderMeta("launcher.focusRetryMs")}</div>
        <div>{fieldLabel(getMeta("launcher.scoreboardStatusPollSec").label, getMeta("launcher.scoreboardStatusPollSec").help)}<input type="number" placeholder={getMeta("launcher.scoreboardStatusPollSec").placeholder} value={config.launcher.scoreboardStatusPollSec} onChange={(e) => updateLauncher("scoreboardStatusPollSec", Number(e.target.value) || 1)} />{renderMeta("launcher.scoreboardStatusPollSec")}</div>
        {renderCheckbox(
          "launcher.scoreboardStatusWatch",
          config.launcher.scoreboardStatusWatch,
          (v) => updateLauncher("scoreboardStatusWatch", v),
        )}
        {renderCheckbox("launcher.pauseOnError", config.launcher.pauseOnError, (v) =>
          updateLauncher("pauseOnError", v),
        )}
        {renderCheckbox("launcher.debugMode", config.launcher.debugMode, (v) =>
          updateLauncher("debugMode", v),
        )}
      </div>
    );
  }

  return (
    <main style={{ fontFamily: "Segoe UI, Arial, sans-serif", padding: 16, maxWidth: 1240 }}>
      <h1>ReplayTrove Control Center</h1>
      <p style={{ color: "#444", marginTop: 0 }}>{status}</p>

      <div style={{ ...sectionCardStyle }}>
        <h3 style={{ marginTop: 0 }}>System Status / Readiness</h3>
        <div style={{ marginBottom: 10 }}>
          <button onClick={() => void loadSystemStatus()}>Refresh Status</button>
        </div>
        {!systemStatus ? (
          <div style={{ color: "#666" }}>
            Status unavailable. Ensure Control Center API is running.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(280px, 1fr))", gap: 12 }}>
            <div style={panelStyle}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Replay pipeline readiness</div>
              <div style={{ fontSize: 12, color: "#555", marginBottom: 8 }}>
                Operator replay buttons / ports: <code style={{ fontSize: 11 }}>docs/operator-replay-trigger-runbook.md</code>
              </div>
              <div>
                Host: {systemStatus.replayReadiness.replayHttpHost.value}{" "}
                {sourceBadge(systemStatus.replayReadiness.replayHttpHost.source)}
              </div>
              <div>
                Port: {systemStatus.replayReadiness.replayHttpPort.value}{" "}
                {sourceBadge(systemStatus.replayReadiness.replayHttpPort.source)}
              </div>
              <div>
                Timeout: {systemStatus.replayReadiness.replayHttpTimeoutSec.value}s{" "}
                {sourceBadge(systemStatus.replayReadiness.replayHttpTimeoutSec.source)}
              </div>
              <div>
                Replay HTTP reachable:{" "}
                {systemStatus.replayReadiness.replayHttpReachable === null
                  ? "unknown"
                  : systemStatus.replayReadiness.replayHttpReachable
                  ? "yes"
                  : "no"}
              </div>
              {systemStatus.replayReadiness.replayHttpReachabilityError ? (
                <div style={{ color: "#a65b00", fontSize: 12 }}>
                  Reachability note: {systemStatus.replayReadiness.replayHttpReachabilityError}
                </div>
              ) : null}
              <div>
                Canonical token configured:{" "}
                {systemStatus.replayReadiness.canonicalTokenConfigured ? "yes" : "no"}
              </div>
            </div>

            <div style={panelStyle}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Replay trust / recent activity</div>
              <div>
                Last trust category:{" "}
                {systemStatus.replayRecentActivity.lastTrustCategory ?? "unknown"}
              </div>
              <div>
                Last replay timestamp:{" "}
                {systemStatus.replayRecentActivity.lastReplayTimestamp ?? "unknown"}
              </div>
              <div>
                Last replay success:{" "}
                {systemStatus.replayRecentActivity.lastReplaySucceeded === null
                  ? "unknown"
                  : systemStatus.replayRecentActivity.lastReplaySucceeded
                  ? "success"
                  : "failure"}
              </div>
              <div>
                Last replay correlation/request id:{" "}
                {systemStatus.replayRecentActivity.lastReplayCorrelationId ?? "unknown"}
              </div>
              <div>
                Replay activity log found:{" "}
                {systemStatus.replayRecentActivity.replayLogFound ? "yes" : "no"}
              </div>
            </div>

            <div style={panelStyle}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>OBS connection config summary</div>
              <div>
                Host: {systemStatus.obsSummary.obsWebsocketHost.value}{" "}
                {sourceBadge(systemStatus.obsSummary.obsWebsocketHost.source)}
              </div>
              <div>
                Port: {systemStatus.obsSummary.obsWebsocketPort.value}{" "}
                {sourceBadge(systemStatus.obsSummary.obsWebsocketPort.source)}
              </div>
              <div>
                Password configured:{" "}
                {systemStatus.obsSummary.obsWebsocketPasswordConfigured ? "yes" : "no"}
              </div>
              <div>
                Password source: {sourceBadge(systemStatus.obsSummary.obsWebsocketPasswordSource)}
              </div>
            </div>

            <div style={panelStyle}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Command bus status</div>
              <div>
                Commands root: {systemStatus.commandBus.commandsRoot.value}{" "}
                {sourceBadge(systemStatus.commandBus.commandsRoot.source)}
              </div>
              <div>
                Legacy bridge active: {systemStatus.commandBus.legacyBridgeActive ? "yes" : "no"}
              </div>
              <div>
                Configured root diverges from legacy:{" "}
                {systemStatus.commandBus.configuredRootDivergesFromLegacy ? "yes" : "no"}
              </div>
              <div>Legacy root: {systemStatus.commandBus.legacyRoot}</div>
            </div>

            <div style={panelStyle}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Launcher supervision and intent</div>
              <div style={{ fontSize: 12, color: "#444", marginBottom: 8 }}>
                Ownership from{" "}
                {systemStatus.launcherSupervision.owner.leaseFileRelative ??
                  "launcher/supervision_owner_lease.json"}
                ; live health from{" "}
                {systemStatus.launcherSupervision.supervisionStatusFileRelative ??
                  "launcher/supervision_status.json"}
                ; persisted desired state from{" "}
                {systemStatus.launcherSupervision.desiredStatePersisted?.fileRelative ??
                  "launcher/supervision_desired_state.json"}
                .
              </div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Ownership</div>
              <div>
                Owner active: {systemStatus.launcherSupervision.owner.active ? "yes" : "no"}
              </div>
              <div>Lease status: {systemStatus.launcherSupervision.owner.state}</div>
              <div>
                Owner id: {systemStatus.launcherSupervision.owner.ownerId ?? "unknown"}
              </div>
              <div>
                Owner host/pid:{" "}
                {systemStatus.launcherSupervision.owner.hostname ?? "unknown"} /{" "}
                {systemStatus.launcherSupervision.owner.pid ?? "unknown"}
              </div>
              <div>
                Lease updated: {systemStatus.launcherSupervision.owner.updatedAt ?? "unknown"}
              </div>
              <div>
                Lease timeout (sec):{" "}
                {systemStatus.launcherSupervision.owner.leaseTimeoutSec ?? "unknown"}
              </div>
              <div>
                Lease reason: {systemStatus.launcherSupervision.owner.reason ?? "unknown"}
              </div>
              <div style={{ fontWeight: 600, margin: "10px 0 4px" }}>Persisted desired state</div>
              {supervisionFreshnessLine(
                "Desired-state file freshness",
                systemStatus.launcherSupervision.artifactFreshness?.desiredState,
              )}
              <div>
                Snapshot file:{" "}
                {systemStatus.launcherSupervision.desiredStatePersisted?.fileRelative ??
                  "launcher/supervision_desired_state.json"}
              </div>
              <div>
                File state:{" "}
                {systemStatus.launcherSupervision.desiredStatePersisted?.fileState ?? "unknown"}
              </div>
              <div>
                Snapshot updated:{" "}
                {systemStatus.launcherSupervision.desiredStatePersisted?.updatedAt ?? "unknown"}
              </div>
              <div>
                Last change reason:{" "}
                {systemStatus.launcherSupervision.desiredStatePersisted?.updateReason ?? "unknown"}
              </div>
              <div style={{ fontWeight: 600, margin: "10px 0 4px" }}>Supervision truth (last tick)</div>
              {supervisionFreshnessLine(
                "Supervision snapshot freshness",
                systemStatus.launcherSupervision.artifactFreshness?.supervisionStatus,
              )}
              <div>
                Supervision snapshot timestamp:{" "}
                {systemStatus.launcherSupervision.snapshotTimestamp ?? "unknown"}
              </div>
              <div style={{ fontSize: 11, color: "#666", marginBottom: 6 }}>
                Per-component health below is only as current as the supervision snapshot. If the
                snapshot is stale or missing, treat live classifications as non-authoritative.
              </div>
              {Array.isArray(systemStatus.launcherSupervision.managedComponents) &&
              systemStatus.launcherSupervision.managedComponents.length > 0 ? (
                <div style={{ marginTop: 8, fontSize: 12 }}>
                  {systemStatus.launcherSupervision.managedComponents.map((row) => (
                    <div
                      key={row.name}
                      style={{
                        marginBottom: 10,
                        paddingBottom: 8,
                        borderBottom: "1px solid #e3e6eb",
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>{row.name}</div>
                      <div style={{ fontSize: 11, color: "#555", marginBottom: 2 }}>
                        Live row freshness: {row.liveRowFreshness ?? "unknown"}
                        {row.liveRowFreshness === "stale"
                          ? " (supervision tick or row observation is old)"
                          : null}
                        {row.liveRowFreshness === "unavailable"
                          ? " (no usable supervision snapshot)"
                          : null}
                      </div>
                      <div>
                        Desired (persisted): {row.desiredPersisted}
                        {" · "}
                        Desired (live tick): {row.desiredLive ?? "unknown"}
                      </div>
                      <div>Health: {row.lastClassification ?? "unknown"}</div>
                      <div>Last unhealthy / probe reason: {row.lastReason ?? "unknown"}</div>
                      <div>
                        Unhealthy strikes:{" "}
                        {row.consecutiveUnhealthy != null ? row.consecutiveUnhealthy : "unknown"}
                      </div>
                      <div>Last observed: {row.lastObservedAt ?? "unknown"}</div>
                      <div>Last restart at: {row.lastRestartAt ?? "none"}</div>
                      <div>Last restart reason: {row.lastRestartReason ?? "none"}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: "#666", marginTop: 6 }}>
                  Managed component rows unavailable (API may be older).
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div style={{ ...sectionCardStyle, display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <button onClick={() => void loadFromApi()}>Load Disk Config</button>
        <button onClick={loadLocal}>Load Local Draft</button>
        <button onClick={saveLocal}>Save Local Draft</button>
        <button onClick={() => void validateCurrent()}>Validate</button>
        <button onClick={() => void saveToDisk()} style={{ fontWeight: 700 }}>Save To Disk</button>
        <button onClick={() => void applySafeLiveSettingsToScoreboard()}>
          Apply safe live settings to scoreboard
        </button>
        <button onClick={() => void loadScoreboardReloadStatus()}>
          Refresh scoreboard reload outcome
        </button>
        <button onClick={exportFile}>Export</button>
        <label>
          Import
          <input
            type="file"
            accept=".json,application/json"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                importFile(file);
              }
              e.currentTarget.value = "";
            }}
            style={{ marginLeft: 8 }}
          />
        </label>
      </div>

      <div style={{ ...sectionCardStyle, display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {sectionKeys.map((key) => (
          <button key={key} onClick={() => setActive(key)}>{SECTION_LABELS[key]}</button>
        ))}
      </div>

      <h2>{SECTION_LABELS[active]}</h2>
      <p style={{ color: "#444" }}>
        {[
          "general",
          "webApp",
          "worker",
          "scoreboard",
          "launcher",
          "cleaner",
          "obsFfmpegPaths",
          "encoder",
          "storage",
          "picklePlanner",
          "schemaVersion",
        ].includes(active)
          ? "Restart required after save for most runtime apps."
          : "Usually safe without restart; app behavior depends on current runtime reload support."}
      </p>
      <div style={sectionCardStyle}>
        {active === "general" ? renderGeneralForm() : null}
        {active === "webApp" ? renderWebAppForm() : null}
        {active === "cleaner" ? renderCleanerForm() : null}
        {active === "obsFfmpegPaths" ? renderObsFfmpegForm() : null}
        {active === "storage" ? renderStorageForm() : null}
        {active === "picklePlanner" ? renderPicklePlannerForm() : null}
        {active === "schemaVersion" ? renderSchemaForm() : null}
        {active === "worker" ? renderWorkerForm() : null}
        {active === "scoreboard" ? renderScoreboardForm() : null}
        {active === "launcher" ? renderLauncherForm() : null}
        {active === "encoder" ? renderEncoderForm() : null}
      </div>
      <h3>Advanced JSON Editor</h3>
      <p style={{ fontSize: 12, color: "#555" }}>
        Expert fallback for keys not in the form above. Edits stay in the box until you apply; invalid JSON
        is not written to the draft config.
      </p>
      <textarea
        style={{ width: "100%", minHeight: 260, fontFamily: "Consolas, monospace", borderRadius: 8, border: "1px solid #d9dde4", padding: 10 }}
        value={jsonDraft}
        onChange={(e) => setJsonDraft(e.target.value)}
      />
      <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" onClick={() => applyJsonDraft(active)}>
          Apply JSON to section
        </button>
        <button type="button" onClick={() => resetSection(active)}>
          Reset Section To Defaults
        </button>
      </div>
      <h2>Diagnostics</h2>
      <div style={panelStyle}>
        <div>Config path: {diagnostics.configPath || "(unknown)"}</div>
        <div>File found: {diagnostics.found ? "yes" : "no"}</div>
        <div>Schema version: {diagnostics.schemaVersion ?? "(unknown)"}</div>
        <div>Migrated on load/validate: {diagnostics.migrated ? "yes" : "no"}</div>
        <div>Validation status: {diagnostics.validationOk ? "ok" : "has errors"}</div>
        <div>Backup path: {diagnostics.backupPath || "(none yet)"}</div>
        <div>Last saved: {lastSavedAt || "(not saved this session)"}</div>
      </div>
      <h2>Validation Issues</h2>
      <ul>
        {validationIssues.length === 0 ? (
          <li>No issues.</li>
        ) : (
          validationIssues.map((issue, idx) => (
            <li key={`${issue.code}-${idx}`}>
              [{issue.severity}] {issue.code}: {issue.message}
              {issue.path ? ` @ ${issue.path}` : ""}
            </li>
          ))
        )}
      </ul>
      {saveSummary ? (
        <>
          <h2>Post-Save Summary</h2>
          <div style={panelStyle}>
            <div>Changed fields: {saveSummary.changed.length}</div>
            <div>Restart-required changed fields: {saveSummary.restart.length}</div>
            <div>Dangerous changed fields: {saveSummary.dangerous.length}</div>
            {saveSummary.restart.length > 0 ? <div>Restart list: {saveSummary.restart.join(", ")}</div> : null}
            {saveSummary.dangerous.length > 0 ? <div>Dangerous list: {saveSummary.dangerous.join(", ")}</div> : null}
          </div>
        </>
      ) : null}
      {reloadSummary ? (
        <>
          <h2>Safe Live Reload Queue Result</h2>
          <div style={panelStyle}>
            <div>Status: {reloadSummary.ok ? "queued" : "failed"}</div>
            <div>{reloadSummary.message}</div>
            {reloadSummary.commandId ? <div>Command id: {reloadSummary.commandId}</div> : null}
            {reloadSummary.correlationId ? (
              <div>Correlation id: {reloadSummary.correlationId}</div>
            ) : null}
            <div>Final applied/rejected outcome is logged by the scoreboard process.</div>
            <div>Restart remains the default-safe path for non-allowlisted settings.</div>
          </div>
        </>
      ) : null}
      <h2>Last Scoreboard Reload Outcome</h2>
      <div style={panelStyle}>
        {!reloadStatusArtifact?.found ? (
          <div>No reload outcome status file found yet.</div>
        ) : (
          <>
            <div>Status file: {reloadStatusArtifact.statusPath}</div>
            <div>Timestamp: {reloadStatusArtifact.status?.timestamp ?? "(unknown)"}</div>
            <div>Correlation id: {reloadStatusArtifact.status?.correlation_id ?? "(none)"}</div>
            <div>Outcome: {reloadStatusArtifact.status?.status ?? "(unknown)"}</div>
            <div>
              Applied fields:{" "}
              {reloadStatusArtifact.status?.applied_fields?.length
                ? reloadStatusArtifact.status.applied_fields.join(", ")
                : "(none)"}
            </div>
            {reloadStatusArtifact.status?.rejection_reason ? (
              <div>Rejection reason: {reloadStatusArtifact.status.rejection_reason}</div>
            ) : null}
            <div>
              Schema version:{" "}
              {reloadStatusArtifact.status?.schema_version ?? "(unknown)"}
            </div>
          </>
        )}
      </div>
      {pendingDangerConfirm.length > 0 ? (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "grid", placeItems: "center" }}>
          <div style={{ background: "white", padding: 16, maxWidth: 720, borderRadius: 10 }}>
            <h3>Confirm high-impact changes</h3>
            <p>These edits can affect startup or replay plumbing.</p>
            <ul>
              {pendingDangerConfirm.map((item) => (
                <li key={item.key}>
                  <strong>{item.meta?.label ?? item.key}</strong>: {item.meta?.impact ?? "High-impact setting changed."}
                  {item.meta?.restartRequired ? " Restart required." : ""}
                </li>
              ))}
            </ul>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => {
                  setPendingDangerConfirm([]);
                  void saveToDisk(true);
                }}
              >
                Confirm and save
              </button>
              <button onClick={() => setPendingDangerConfirm([])}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
