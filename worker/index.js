// Starts the daily roaster scan on time. GitHub's own schedule often runs hours late; Cloudflare's cron
// triggers fire on the minute, so this asks GitHub to run the scan workflow straight away.
// GitHub's schedule stays as a backup and skips itself once the day's scan is in.
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(startScan(env));
  },
  // the Worker has no public job: any visit just gets a line of text, nothing is started
  async fetch() {
    return new Response("Bag to Cup scan trigger", { headers: { "content-type": "text/plain" } });
  },
};

async function startScan(env) {
  const res = await fetch("https://api.github.com/repos/thisisfed/v60/actions/workflows/scan.yml/dispatches", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "bagtocup-scan-trigger",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (!res.ok) throw new Error(`GitHub answered ${res.status}: ${await res.text()}`);
}
