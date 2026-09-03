function parseStatus(raw) {
  var text = String(raw || "").trim()
  if (text === "") return defaultStatus()
  try {
    var parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== "object") return defaultStatus()
    parsed.pendingFiles = Array.isArray(parsed.pendingFiles) ? parsed.pendingFiles : []
    parsed.errors = Array.isArray(parsed.errors) ? parsed.errors : []
    return parsed
  } catch (e) {
    var failed = defaultStatus()
    failed.ok = false
    failed.lastError = "Failed to parse OneDrive status"
    return failed
  }
}

function defaultStatus() {
  return {
    ok: true,
    installed: false,
    serviceExists: false,
    running: false,
    mounted: false,
    authenticated: false,
    statusText: "Unavailable",
    remoteName: "",
    mountPoint: "",
    mountPointExpanded: "",
    lastSyncTs: 0,
    pendingFiles: [],
    pendingCount: 0,
    bytesQueued: 0,
    transferredBytes: 0,
    errorCount: 0,
    errors: []
  }
}

function formatBytes(bytes) {
  var value = Number(bytes || 0)
  if (!isFinite(value) || value <= 0) return "0 B"
  var units = ["B", "KB", "MB", "GB", "TB"]
  var index = 0
  while (value >= 1000 && index < units.length - 1) {
    value = value / 1000
    index++
  }
  var decimals = value >= 100 || index === 0 ? 0 : (value >= 10 ? 1 : 2)
  return value.toFixed(decimals).replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1") + " " + units[index]
}

function relativeTime(timestampSec, nowMs) {
  var ts = Number(timestampSec || 0)
  if (!isFinite(ts) || ts <= 0) return "Never"
  var now = nowMs === undefined ? Date.now() : Number(nowMs)
  var diff = Math.max(0, Math.floor((now - ts * 1000) / 1000))
  if (diff < 60) return "Just now"
  var minutes = Math.floor(diff / 60)
  if (minutes < 60) return minutes + "m ago"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return hours + "h ago"
  var days = Math.floor(hours / 24)
  if (days < 30) return days + "d ago"
  var months = Math.floor(days / 30)
  if (months < 12) return months + "mo ago"
  return Math.floor(days / 365) + "y ago"
}

function pendingGlyph(file) {
  var stage = String(file && file.stage || "").toLowerCase()
  if (stage === "transferring") return "󰇚"
  if (stage === "checking") return "󰑓"
  if (stage === "queued") return "󱑍"
  if (stage === "error") return "󰅚"
  return "󰄭"
}

function pendingTitle(file) {
  if (!file) return "Unknown item"
  var name = String(file.name || file.path || file.remote || "")
  return name === "" ? "Unknown item" : name
}

function pendingMeta(file, nowMs) {
  if (!file) return ""
  var parts = []
  var stage = String(file.stage || "")
  if (stage !== "") parts.push(stage)
  if (Number(file.sizeBytes || 0) > 0) parts.push(formatBytes(file.sizeBytes))
  if (Number(file.speed || 0) > 0) parts.push(formatBytes(file.speed) + "/s")
  if (Number(file.modifiedTs || 0) > 0) parts.push(relativeTime(file.modifiedTs, nowMs))
  return parts.join(" · ")
}

function statusSummary(statusText, pendingCount, lastSyncTs) {
  if (Number(pendingCount || 0) > 0) return "Syncing " + pendingCount + " item" + (pendingCount === 1 ? "" : "s")
  if (Number(lastSyncTs || 0) > 0) return "Last sync " + relativeTime(lastSyncTs)
  return String(statusText || "Idle")
}

if (typeof module !== "undefined") {
  module.exports = {
    parseStatus: parseStatus,
    defaultStatus: defaultStatus,
    formatBytes: formatBytes,
    relativeTime: relativeTime,
    pendingGlyph: pendingGlyph,
    pendingTitle: pendingTitle,
    pendingMeta: pendingMeta,
    statusSummary: statusSummary
  }
}
