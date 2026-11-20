// The inner pages (coffees, roasters, privacy, get listed): the same Dark / Light button as the main page, and the same
// choice, kept on this device under the same name. Dark unless you picked Light.
(function () {
  var r = document.documentElement, b = document.getElementById("themeBtn"); if (!b) return;
  var S = '<svg viewBox="0 0 24 24" aria-hidden="true">', E = "</svg>";
  var IC = {
    light: S + '<circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' + E,
    dark: S + '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>' + E
  };
  function set(t) { r.setAttribute("data-theme", t); b.innerHTML = IC[t]; b.setAttribute("aria-label", "Appearance: " + (t === "dark" ? "Dark" : "Light") + ". Tap to change.");
    var m = document.querySelector('meta[name="theme-color"]'); if (m) m.setAttribute("content", t === "dark" ? "#000000" : "#ffffff"); }
  set(r.getAttribute("data-theme") === "light" ? "light" : "dark");
  b.onclick = function () { var t = r.getAttribute("data-theme") === "dark" ? "light" : "dark"; try { localStorage.setItem("v60.theme", t); } catch (e) {} set(t); };
})();
