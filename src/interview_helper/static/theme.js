"use strict";
// Blocking head script: apply the sole browser preference before styles/paint.
// Unavailable storage still leaves a usable dark-first, in-memory toggle.
try {
  if (localStorage.getItem("ih-theme") === "light") {
    document.documentElement.dataset.theme = "light";
  }
} catch {}
