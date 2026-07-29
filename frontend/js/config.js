// Central API configuration.
// Local development: leave as-is (FastAPI on localhost:8000).
// Production: change this to your deployed backend URL, e.g.
//   window.API_BASE = "https://api.goldenkeysllc.com";
const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : "https://goldenkeyscapital.app";
