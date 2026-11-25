// Roughly where a visitor is (GET /api/where), a Cloudflare Pages Function.
// Cloudflare already knows each visitor's approximate town from the connection (request.cf): Goccio uses it for "what's the
// weather?", so the phone never has to ask for its location. A town, never a street; nothing is stored or logged.
export async function onRequestGet({ request }) {
  const cf = request.cf || {};
  const n = (v) => (v == null || v === "" || isNaN(+v) ? null : Math.round(+v * 100) / 100);   // two decimals: about a kilometre
  const out = { city: cf.city || "", country: cf.country || "", la: n(cf.latitude), lo: n(cf.longitude) };
  return new Response(JSON.stringify(out), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "private, no-store" } });
}
