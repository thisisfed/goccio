// Safety net: every script inside the page must at least parse. A stray comment or bracket once stopped Goccio
// (and the whole page) from working; this catches that before it's published.
// Usage: node scripts/check_js.js [index.html ...]   Exit code 1 if any script doesn't parse.
const fs = require("fs");
const files = process.argv.slice(2).length ? process.argv.slice(2) : ["index.html"];
let bad = 0;
for (const f of files) {
  const s = fs.readFileSync(f, "utf8");
  const scripts = [...s.matchAll(/<script(?![^>]*\bsrc=)(?![^>]*type=["']application\/(?:ld\+)?json)[^>]*>([\s\S]*?)<\/script>/g)];
  scripts.forEach((m, i) => {
    try { new Function(m[1]); }
    catch (e) { bad++; const line = s.slice(0, m.index).split("\n").length; console.error(`${f}: script ${i + 1} (from line ${line}) does not parse: ${e.message}`); }
  });
  console.log(`${f}: ${scripts.length} scripts checked`);
}
process.exit(bad ? 1 : 0);
