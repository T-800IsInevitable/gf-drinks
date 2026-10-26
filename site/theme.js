// Apply the saved theme before the first paint, so the page doesn't flash the wrong colours. Loaded as a file rather
// than written inline, so the content security policy needs no hash of its text (a stale hash would break the app).
try { var t = localStorage.getItem("gf-theme"); if (t && t !== "auto") document.documentElement.setAttribute("data-theme", t); } catch (e) {}
