// Goccio's scan clock: on its timers it asks GitHub to start, first, the search for new roasters (00:31 UTC), then the
// daily roaster scan (02:31, again at 03:31), so the scan reads the roasters added that night too. GitHub's own
// schedule for the search ran hours late (11:00 on 26/11/2026), after the scan. "daily: 1" tells the scan to skip
// itself if today's has already run.
const GH = "https://api.github.com/repos/thisisfed/goccio/actions/workflows/";

async function start(env, cron) {
  const world = cron === "31 0 * * *", URL = GH + (world ? "world.yml" : "scan.yml") + "/dispatches";
  if (!env.GITHUB_TOKEN) { console.log("No GITHUB_TOKEN secret yet: nothing started"); return; }
  const r = await fetch(URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Goccio/1.0", "Content-Type": "application/json" },
    body: JSON.stringify(world ? { ref: "main" } : { ref: "main", inputs: { daily: "1" } }),
  });
  console.log(r.ok ? (world ? "Roaster search started" : "Daily scan started") : `GitHub said ${r.status}: ${(await r.text()).slice(0, 300)}`);
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(start(env, event.cron)); },
};
