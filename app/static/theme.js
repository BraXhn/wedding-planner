// Mörkt/ljust läge i apparna – laddas före sidan ritas så att den inte blinkar. "auto" följer telefonen.
try {
  const t = localStorage.getItem("app-theme");
  if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
} catch (_) { /* privat läge */ }
