// Goccio's scan clock: on its timer it asks GitHub to start the daily roaster scan (the one that adds new coffees from
// the roasters Goccio already knows). "daily: 1" tells the scan to skip itself if today's has already run.
const URL = "https://api.github.com/repos/thisisfed/goccio/actions/workflows/scan.yml/dispatches";

async function start(env) {
  if (!env.GITHUB_TOKEN) { console.log("No GITHUB_TOKEN secret yet: nothing started"); return; }
  const r = await fetch(URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Goccio/1.0", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main", inputs: { daily: "1" } }),
  });
  console.log(r.ok ? "Daily scan started" : `GitHub said ${r.status}: ${(await r.text()).slice(0, 300)}`);
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(start(env)); },
};
