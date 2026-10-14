const assert = require("node:assert/strict");
const Model = require("./Model.js");

const parsed = Model.parseSearchResults(JSON.stringify({
  ok: true, ready: true, partial: true, truncated: true,
  results: [
    { path: "/@work/Report.pdf", sourcePath: "/Report.pdf", profileId: "work", libraryLabel: "Work", mountPoint: "/fixture/work" },
    { path: "/@personal/Report.pdf", sourcePath: "/Report.pdf", profileId: "personal", libraryLabel: "Personal", mountPoint: "/fixture/personal" }
  ]
}));
assert.equal(parsed.partial, true);
assert.equal(parsed.truncated, true);
assert.equal(parsed.results[0].mountPoint, "/fixture/work");
assert.equal(parsed.results[1].profileId, "personal");
assert.notEqual(parsed.results[0].path, parsed.results[1].path);
const tree = Model.flattenTree({
  "/": { children: [{ path: "/@work", name: "Documents", isDir: true }, { path: "/@personal", name: "Documents", isDir: true }] }
}, {}, "/");
assert.deepEqual(tree.map(row => row.path), ["/@work", "/@personal"]);
assert.equal(Model.parseSearchResults('{"ok":false,"error":"Unavailable"}').results.length, 0);
