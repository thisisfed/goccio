// How a brew tasted (POST /api/taste) and what everyone said about a coffee (GET /api/taste?u=<coffee link>).
// A Cloudflare Pages Function with a D1 database bound as TASTE (free tier: 100,000 writes and 5 million reads a day).
// No database bound yet: answers are dropped quietly and the site works exactly as before.
//
// What is kept, per answer: the coffee (its public shop link, roaster and name, all already on Goccio), the brewer, the recipe's
// numbers (grind in Comandante clicks, temperature, ratio, dose), the drain time, the roast and process the recipe used, the
// answer (sour, balanced or bitter) and the day. Nothing about the person: no address, no device, no cookie, no id.
// Only coffees from Goccio's own list are counted; a coffee someone typed or scanned never leaves the phone.

const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
const TASTES = new Set(["sour", "balanced", "bitter"]);
const str = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "");
const num = (v, lo, hi) => (typeof v === "number" && isFinite(v) && v >= lo && v <= hi ? Math.round(v * 10) / 10 : null);

let ready = false;
async function table(db) {
  if (ready) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS taste (
    day TEXT NOT NULL, url TEXT NOT NULL, roaster TEXT, name TEXT, brewer TEXT, taste TEXT NOT NULL,
    clicks REAL, temp REAL, ratio REAL, dose REAL, drained INTEGER, roast TEXT, process TEXT)`).run();
  await db.prepare("CREATE INDEX IF NOT EXISTS taste_url ON taste (url)").run();
  ready = true;
}

export async function onRequestPost({ request, env }) {
  if (!env.TASTE) return json({ ok: true, kept: false });
  let b;
  try { b = await request.json(); } catch (e) { return json({ ok: false }, 400); }
  const url = str(b.url, 400), taste = str(b.taste, 12);
  if (!/^https?:\/\//.test(url) || !TASTES.has(taste)) return json({ ok: false }, 400);
  try {
    await table(env.TASTE);
    await env.TASTE.prepare("INSERT INTO taste (day, url, roaster, name, brewer, taste, clicks, temp, ratio, dose, drained, roast, process) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")
      .bind(new Date().toISOString().slice(0, 10), url, str(b.roaster, 120), str(b.name, 160), str(b.brewer, 40), taste,
            num(b.clicks, 0, 60), num(b.temp, 0, 100), num(b.ratio, 1, 30), num(b.dose, 1, 100), num(b.drained, 0, 7200), str(b.roast, 20), str(b.process, 30))
      .run();
    return json({ ok: true, kept: true });
  } catch (e) { return json({ ok: false }, 500); }
}

// totals for one coffee: how many said sour, just right, bitter
export async function onRequestGet({ request, env }) {
  const u = new URL(request.url).searchParams.get("u") || "";
  if (!env.TASTE || !/^https?:\/\//.test(u)) return json({ sour: 0, balanced: 0, bitter: 0, db: !!env.TASTE });
  try {
    await table(env.TASTE);
    const { results } = await env.TASTE.prepare("SELECT taste, COUNT(*) AS n FROM taste WHERE url = ? GROUP BY taste").bind(u.slice(0, 400)).all();
    const out = { sour: 0, balanced: 0, bitter: 0, db: true };
    for (const r of results || []) if (r.taste in out) out[r.taste] = r.n;
    return new Response(JSON.stringify(out), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=300" } });
  } catch (e) { return json({ sour: 0, balanced: 0, bitter: 0, db: true, error: true }); }
}
