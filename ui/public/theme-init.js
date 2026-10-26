try {
  var t = localStorage.getItem("gonogo-theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {
  // Storage can be blocked. The page falls back to the system theme.
}
