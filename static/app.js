// Phase 0 : affiche simplement l'état renvoyé par /api/health.
async function chargerEtat() {
  const statusEl = document.getElementById("status");
  const sourcesEl = document.getElementById("sources");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    document.getElementById("version").textContent = "v" + data.version;
    statusEl.textContent = `API OK · schéma v${data.schema_version} · ${data.nb_cibles} cible(s) en base`;
    statusEl.className = "ok";
    sourcesEl.innerHTML = "";
    for (const [nom, info] of Object.entries(data.sources)) {
      const li = document.createElement("li");
      li.innerHTML = info.configuree
        ? `<span class="ok">●</span> ${nom}`
        : `<span class="warn">●</span> ${nom} <span class="muted">(${info.message})</span>`;
      sourcesEl.appendChild(li);
    }
  } catch (e) {
    statusEl.textContent = "Impossible de joindre l'API : " + e.message;
    statusEl.className = "warn";
  }
}
chargerEtat();
