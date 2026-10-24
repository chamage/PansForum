(function () {
  try {
    var saved = localStorage.getItem("pans_theme");
    if (saved === "dark" || saved === "light") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (_) {}
})();
