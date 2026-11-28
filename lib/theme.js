// Old addresses (the two old thisisfed.xyz ones, the bare goccio.co.uk) go to the same page on www.goccio.co.uk
(function () { var h = location.hostname; if (h === "v60.thisisfed.xyz" || h === "bagtocup.thisisfed.xyz" || h === "goccio.co.uk")
  location.replace("https://www.goccio.co.uk" + location.pathname + location.search + location.hash); })();
// The inner pages (coffees, roasters, privacy, get listed): the same appearance button as the main page and the same choice,
// kept on this device under the same name: Dark (the default), Light, or Auto (light by day, dark from sunset where you are) (28/11/2026)
(function () {
  var r = document.documentElement, b = document.getElementById("themeBtn"); if (!b) return;
  var S = '<svg viewBox="0 0 24 24" aria-hidden="true">', E = "</svg>", TH = ["dark", "light", "auto"], LB = { dark: "Dark", light: "Light", auto: "Auto" };
  var IC = {
    auto: S + '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>' + E,
    light: S + '<circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' + E,
    dark: S + '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>' + E
  };
  var sys = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null, tm = 0;
  function place() { try { var p = JSON.parse(localStorage.getItem("v60.sun") || "null"); return p && p.la != null && p.lo != null ? p : null; } catch (e) { return null; } }
  function autoDark() { var p = place(); return p && window.__sun ? window.__sun(p.la, p.lo).dark : (sys ? sys.matches : true); }
  var t = "dark"; try { var v = localStorage.getItem("v60.theme"); if (TH.indexOf(v) >= 0) t = v; } catch (e) {}
  function set() { var dark = t === "auto" ? autoDark() : t !== "light"; r.setAttribute("data-theme", dark ? "dark" : "light"); b.innerHTML = IC[t];
    b.setAttribute("aria-label", "Appearance: " + LB[t] + ". Tap for " + LB[TH[(TH.indexOf(t) + 1) % 3]] + ".");
    var m = document.querySelector('meta[name="theme-color"]'); if (m) m.setAttribute("content", dark ? "#000000" : "#f7f3ed"); }
  function watch() { clearTimeout(tm); if (t !== "auto") return; var p = place(), s = p && window.__sun ? window.__sun(p.la, p.lo) : null;
    tm = setTimeout(function () { set(); watch(); }, (s && s.next != null ? Math.min(s.next + 0.5, 30) : 10) * 60000); }
  function fetchPlace() { var p = place(); if (p && Date.now() - (p.at || 0) < 864e5) return;
    fetch("/api/where", { cache: "no-store" }).then(function (x) { return x.json(); }).then(function (w) { if (w && w.la != null && w.lo != null) { try { localStorage.setItem("v60.sun", JSON.stringify({ la: w.la, lo: w.lo, at: Date.now() })); } catch (e) {} if (t === "auto") { set(); watch(); } } }).catch(function () {}); }
  set(); if (t === "auto") { fetchPlace(); watch(); }
  try { sys.addEventListener("change", function () { if (t === "auto" && !place()) set(); }); } catch (e) {}
  document.addEventListener("visibilitychange", function () { if (!document.hidden && t === "auto") { set(); watch(); } });
  b.onclick = function () { t = TH[(TH.indexOf(t) + 1) % 3]; try { localStorage.setItem("v60.theme", t); } catch (e) {} set(); if (t === "auto") { fetchPlace(); watch(); } };
})();

// links to other websites (a roaster's shop, a coffee's page) open in a new tab
(function () { var own = location.hostname;
  [].forEach.call(document.querySelectorAll('a[href^="http"]'), function (a) { try { if (new URL(a.href).hostname !== own) { a.target = "_blank"; if (!/noopener/.test(a.rel)) a.rel = (a.rel + " noopener").trim(); } } catch (e) {} });
})();
