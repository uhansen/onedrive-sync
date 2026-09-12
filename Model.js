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
    errors: [],
    backend: "",
    daemonReachable: false,
    tokenExpiresInSec: 0,
    indexEnabled: false,
    crawlComplete: false,
    totalDirs: 0,
    totalFiles: 0,
    itemsPerSec: 0,
    lastTickAt: 0,
    lastTickApplied: 0,
    lastTickDurationMs: 0
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

function formatDuration(seconds) {
  var value = Math.max(0, Math.floor(Number(seconds || 0)))
  if (!isFinite(value) || value <= 0) return "Ready (auto-refresh)"
  if (value < 60) return value + "s"
  var minutes = Math.floor(value / 60)
  if (minutes < 60) return minutes + "m"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return hours + "h"
  var days = Math.floor(hours / 24)
  return days + "d"
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

function formatRate(itemsPerSec) {
  var value = Number(itemsPerSec || 0)
  if (!isFinite(value) || value <= 0) return "idle"
  if (value >= 100) return Math.round(value) + " items/s"
  if (value >= 10) return value.toFixed(1) + " items/s"
  return value.toFixed(2) + " items/s"
}

function parseIndexStatus(raw) {
  var parsed = parseStatus(raw)
  if (!parsed.ok) return parsed
  var tick = parsed.lastTick && typeof parsed.lastTick === "object" ? parsed.lastTick : {}
  parsed.indexEnabled = parsed.indexEnabled === true
  parsed.crawlComplete = parsed.crawlComplete === true
  parsed.totalDirs = Number(parsed.totalDirs || 0)
  parsed.totalFiles = Number(parsed.totalFiles || 0)
  parsed.itemsPerSec = Number(tick.itemsPerSec || parsed.itemsPerSec || 0)
  parsed.lastTickAt = Number(tick.at || 0)
  parsed.lastTickApplied = Number(tick.applied || 0)
  parsed.lastTickDurationMs = Number(tick.durationMs || 0)
  parsed.lastTickPages = Number(tick.pages || 0)
  parsed.lastTickResync = tick.resync === true
  parsed.generation = Number(parsed.generation || 0)
  parsed.pendingNextLink = parsed.pendingNextLink === true
  return parsed
}

function parseTree(raw) {
  var parsed = parseStatus(raw)
  if (!parsed.ok) {
    parsed.children = []
    parsed.path = "/"
    parsed.isDir = true
    return parsed
  }
  parsed.path = String(parsed.path || "/")
  parsed.name = String(parsed.name || "")
  parsed.isDir = parsed.isDir === true
  parsed.size = Number(parsed.size || 0)
  parsed.mtime = Number(parsed.mtime || 0)
  parsed.source = String(parsed.source || "")
  parsed.children = (Array.isArray(parsed.children) ? parsed.children : []).filter(isFolderEntry)
  return parsed
}

function isFolderEntry(entry) {
  if (!entry || typeof entry !== "object") return false
  var value = entry.isDir
  if (value === undefined) value = entry.is_dir
  return value === true || value === 1 || value === "true"
}

function joinTreePath(parent, name) {
  var p = String(parent || "/").replace(/\/+$/, "")
  if (p === "") p = "/"
  var n = String(name || "")
  if (p === "/") return "/" + n
  return p + "/" + n
}

function flattenTree(byPath, expanded, rootPath) {
  var rows = []
  function walk(path, depth) {
    var node = byPath ? byPath[path] : null
    if (!node || !Array.isArray(node.children)) return
    for (var i = 0; i < node.children.length; i++) {
      var c = node.children[i]
      var childPath = String(c.path || joinTreePath(path, c.name))
      if (!isFolderEntry(c)) continue
      var isExpanded = !!(expanded && expanded[childPath])
      rows.push({
        path: childPath,
        name: String(c.name || ""),
        isDir: true,
        size: Number(c.size || 0),
        mtime: Number(c.mtime || 0),
        depth: depth,
        expanded: isExpanded
      })
      if (isExpanded) walk(childPath, depth + 1)
    }
  }
  walk(rootPath || "/", 0)
  return rows
}

function parseSearchResults(raw) {
  var parsed = parseStatus(raw)
  if (!parsed.ok) {
    parsed.ready = false
    parsed.query = ""
    parsed.truncated = false
    parsed.results = []
    return parsed
  }
  parsed.ready = parsed.ready === true
  parsed.query = String(parsed.query || "")
  parsed.truncated = parsed.truncated === true
  var results = Array.isArray(parsed.results) ? parsed.results : []
  parsed.results = results.map(function (entry) {
    return {
      path: String((entry && entry.path) || ""),
      name: String((entry && entry.name) || ""),
      isDir: isFolderEntry(entry),
      size: Number((entry && entry.size) || 0),
      mtime: Number((entry && entry.mtime) || 0)
    }
  })
  return parsed
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
    formatDuration: formatDuration,
    relativeTime: relativeTime,
    pendingGlyph: pendingGlyph,
    pendingTitle: pendingTitle,
    pendingMeta: pendingMeta,
    statusSummary: statusSummary,
    formatRate: formatRate,
    parseIndexStatus: parseIndexStatus,
    parseTree: parseTree,
    parseSearchResults: parseSearchResults,
    flattenTree: flattenTree,
    joinTreePath: joinTreePath,
    isFolderEntry: isFolderEntry
  }
}
