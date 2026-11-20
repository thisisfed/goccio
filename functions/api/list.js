// "Get your roastery listed" (POST /api/list), a Cloudflare Pages Function.
// 1. Checks the form (a hidden honeypot field stops most bots).
// 2. Looks at the shop once, the way the daily scan does: Shopify's /products.json, WooCommerce's Store API,
//    Squarespace's ?format=json, else a sitemap. It reads nothing private and buys nothing.
// 3. Files the request as a GitHub issue (label "listing") in the private repo, if the LISTING_TOKEN secret is set.
//    The "Find new roasters" workflow picks those up, checks them with the real scanner and adds the ones it can read.
// The roaster's email is used only to reply about the listing; it goes into that private issue and nowhere else.

const UA = "BagToCup/1.0 (+https://bagtocup.thisisfed.xyz/list/; checking a shop that asked to be listed)";
const REPO = "thisisfed/v60";

const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });

async function get(url, accept = "application/json") {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(url, { headers: { "User-Agent": UA, Accept: accept }, redirect: "follow", signal: ctl.signal });
    return r.ok ? r : null;
  } catch (e) { return null; } finally { clearTimeout(t); }
}

// what the scan would find: the platform and how many products it can see (coffee or not; the scan sorts that out)
async function probe(shop) {
  let r = await get(`${shop}/products.json?limit=250`);
  if (r) { try { const d = await r.json(); if (Array.isArray(d.products)) return { platform: "Shopify", products: d.products.length }; } catch (e) {} }
  r = await get(`${shop}/wp-json/wc/store/v1/products?per_page=100`);
  if (r) { try { const d = await r.json(); if (Array.isArray(d)) return { platform: "WooCommerce", products: d.length }; } catch (e) {} }
  r = await get(`${shop}/shop?format=json`);
  if (r) { try { const d = await r.json(); if (d && (d.items || d.collection)) return { platform: "Squarespace", products: (d.items || []).length }; } catch (e) {} }
  r = await get(`${shop}/sitemap.xml`, "application/xml,text/xml");
  if (r) { const t = await r.text(); const n = (t.match(/<loc>[^<]*(product|shop|coffee)[^<]*<\/loc>/gi) || []).length; if (n) return { platform: "sitemap", products: n }; }
  return { platform: null, products: 0 };
}

export async function onRequestPost({ request, env }) {
  let f;
  try { f = await request.formData(); } catch (e) { return json({ ok: false, msg: "That didn't come through. Try again." }, 400); }
  if ((f.get("website2") || "").toString().trim()) return json({ ok: true, msg: "Thanks." });   // honeypot: a person never fills this
  const want = (f.get("want") || "list").toString();
  if (want === "ask") return ask(f, env);
  let name = (f.get("name") || "").toString().trim().slice(0, 80);   // the form asks only for the shop and an email: the name comes from the shop
  const town = (f.get("town") || "").toString().trim().slice(0, 60);
  const email = (f.get("email") || "").toString().trim().slice(0, 120);
  const note = (f.get("note") || "").toString().trim().slice(0, 600);
  let shop = (f.get("shop") || "").toString().trim();
  if (!shop || !email) return json({ ok: false, msg: "Please fill in your shop's address and an email." }, 400);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ ok: false, msg: "That email address doesn't look right." }, 400);
  if (!/^https?:\/\//i.test(shop)) shop = "https://" + shop;
  let u; try { u = new URL(shop); } catch (e) { return json({ ok: false, msg: "That shop address doesn't look right." }, 400); }
  if (!/\./.test(u.hostname) || /bagtocup|thisisfed|localhost/.test(u.hostname)) return json({ ok: false, msg: "That shop address doesn't look right." }, 400);
  shop = `${u.protocol}//${u.hostname}`;
  if (!name) name = await shopName(shop);
  if (want === "remove") {
    // no shop check and no consent box: a removal request is filed for the morning run, which takes the shop off the list
    const ok = await file(env, `Removal: ${name}`, { name, shop, email, at: new Date().toISOString() }, "removal");
    return ok ? json({ ok: true, msg: "Thanks. Your coffees come off the site within a day, and we'll email you when they have." })
              : json({ ok: false, msg: "Something went wrong on our side. Please try again later." }, 502);
  }
  // no tick box: sending the form is the permission (the sentence above the button says what it allows)

  const p = await probe(shop);
  const seen = p.platform ? `We can read your shop (${p.platform}, ${p.products} product${p.products === 1 ? "" : "s"} visible).` : "We couldn't read your shop automatically, so a person will look at it.";

  if (!env.LISTING_TOKEN) return json({ ok: false, msg: `${seen} Listing requests open very soon: please try again in a few days.` }, 503);
  const body = ["```json", JSON.stringify({ name, shop, town, email, note, platform: p.platform, products: p.products, at: new Date().toISOString() }, null, 1), "```"].join("\n");
  const gh = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.LISTING_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "bagtocup-listing", "content-type": "application/json" },
    body: JSON.stringify({ title: `Listing: ${name}`, body, labels: ["listing"] }),
  }).catch(() => null);
  if (!gh || !gh.ok) return json({ ok: false, msg: `${seen} Something went wrong on our side saving your request. Please try again later.` }, 502);
  return json({ ok: true, msg: p.platform ? `${seen} Your coffees should appear within two days. We'll email you if anything needs checking.` : `${seen} We'll email you within a week.` });
}

// the shop's own name, from its home page (og:site_name, else the page title before any " | " or " – "), else its address
async function shopName(shop) {
  const host = new URL(shop).hostname.replace(/^www\./, "");
  const r = await get(shop, "text/html"); if (!r) return host;
  const t = (await r.text()).slice(0, 60000);
  const m = t.match(/<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']{2,80})/i) || t.match(/<title[^>]*>([^<]{2,120})<\/title>/i);
  const n = m ? m[1].replace(/&amp;/g, "&").replace(/&#0?39;|&rsquo;/g, "’").split(/\s[|–—-]\s/)[0].trim() : "";
  return n || host;
}

// files a request as an issue in the private repo; false when the token is missing or GitHub says no
async function file(env, title, data, label) {
  if (!env.LISTING_TOKEN) return false;
  const body = ["```json", JSON.stringify(data, null, 1), "```"].join("\n");
  const gh = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.LISTING_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "bagtocup-listing", "content-type": "application/json" },
    body: JSON.stringify({ title, body, labels: [label] }),
  }).catch(() => null);
  return !!(gh && gh.ok);
}

// a question from the privacy page
async function ask(f, env) {
  const email = (f.get("email") || "").toString().trim().slice(0, 120);
  const note = (f.get("note") || "").toString().trim().slice(0, 1200);
  if (!note) return json({ ok: false, msg: "Please write your question." }, 400);
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ ok: false, msg: "That email address doesn't look right." }, 400);
  const ok = await file(env, "Question", { email, note, at: new Date().toISOString() }, "question");
  return ok ? json({ ok: true, msg: email ? "Thanks. We'll reply by email." : "Thanks, it's been sent." })
            : json({ ok: false, msg: "Something went wrong on our side. Please try again later." }, 502);
}

export const onRequestGet = () => json({ ok: false, msg: "Send the form on /list/." }, 405);
