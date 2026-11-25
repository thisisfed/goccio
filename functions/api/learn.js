// What Goccio couldn't answer (POST /api/learn), a Cloudflare Pages Function.
// When Goccio says "I don't know", or someone gives one of its answers a 👎, the question is sent here and filed as a comment
// on that week's issue ("Goccio couldn't answer: week of 23 Nov 2026", label "goccio-learn") in the private requests repo.
// On Mondays the "Goccio's week" workflow counts the week's questions into a list, most asked first, for Federico to answer.
//
// What is kept: the question's words (cut to 200 characters, with anything like an email, a phone number or a link taken
// out), its language, and why it was sent (didn't know, or a 👎). Nothing about the person: no address, no device, no id.
// No token set: nothing is kept and the chat works exactly as before.

const REPO = "thisisfed/goccio-requests";   // private: the questions never sit in the public repo
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// the week's Monday, day first: "23 Nov 2026"
const weekOf = (d = new Date()) => { const m = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())); m.setUTCDate(m.getUTCDate() - ((m.getUTCDay() + 6) % 7)); return `${m.getUTCDate()} ${MON[m.getUTCMonth()]} ${m.getUTCFullYear()}`; };

// nothing personal goes into the issue
const clean = (q) => String(q || "").replace(/[\u0000-\u001f]/g, " ")
  .replace(/\S+@\S+\.\S+/g, "[email]").replace(/https?:\/\/\S+|www\.\S+/gi, "[link]").replace(/\+?\d[\d ()-]{7,}\d/g, "[number]")
  .replace(/\s+/g, " ").trim().slice(0, 200);

export async function onRequestPost({ request, env }) {
  if (!env.LISTING_TOKEN) return json({ ok: true, kept: false });
  let b; try { b = await request.json(); } catch (e) { return json({ ok: false }, 400); }
  const q = clean(b && b.q), lang = b && b.lang === "it" ? "it" : "en", why = b && b.why === "down" ? "👎" : "didn't know";
  if (q.length < 3 || !/[a-zà-ü]{2}/i.test(q)) return json({ ok: false }, 400);
  const gh = (path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, { ...init, headers: { Authorization: `Bearer ${env.LISTING_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "goccio-learn", "content-type": "application/json", ...(init.headers || {}) } });
  const title = `Goccio couldn't answer: week of ${weekOf()}`;
  try {
    let num = null;
    const r = await gh(`/issues?labels=goccio-learn&state=open&per_page=20`);
    if (r.ok) { const list = await r.json(); const hit = list.find((i) => i.title === title); if (hit) num = hit.number; }
    if (!num) {
      const c = await gh(`/issues`, { method: "POST", body: JSON.stringify({ title, labels: ["goccio-learn"], body: "What Goccio couldn't answer this week, one comment per question as it came in. On Monday the list is counted here, most asked first.\n\nSend this issue to Claude to teach Goccio the answers." }) });
      if (!c.ok) return json({ ok: false }, 502);
      num = (await c.json()).number;
    }
    const k = await gh(`/issues/${num}/comments`, { method: "POST", body: JSON.stringify({ body: `${q}\n\n<sub>${why}, ${lang}</sub>` }) });
    return json({ ok: k.ok });
  } catch (e) { return json({ ok: false }, 502); }
}
