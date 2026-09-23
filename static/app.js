/* =====================================================================
   Dashboard stage SISR — interface (Vue 3 sans build)
   Vues : Accueil, Tableau, Kanban, Carte, Corbeille, Réglages + fiche détaillée.
   Toutes les données passent par l'API FastAPI (/api/...).
   ===================================================================== */
const { createApp, reactive, ref, computed, watch, onMounted, onBeforeUnmount, nextTick, markRaw } = Vue;

// ------------------------------------------------------------------ constantes
const STATUTS = [
  { id: "nouveau", label: "Nouveau", emoji: "🆕" },
  { id: "vu", label: "Vu", emoji: "👁️" },
  { id: "retenu", label: "Retenu / à contacter", emoji: "⭐" },
  { id: "envoyee", label: "Candidature envoyée", emoji: "📨" },
  { id: "a_relancer", label: "À relancer", emoji: "🔔" },
  { id: "entretien", label: "Entretien prévu", emoji: "🗓️" },
  { id: "accepte", label: "Accepté", emoji: "✅" },
  { id: "refuse", label: "Refusé", emoji: "❌" },
  { id: "supprime", label: "Supprimé", emoji: "🗑️" },
];
const STATUT = Object.fromEntries(STATUTS.map(s => [s.id, s]));
const TYPES = { offre: "Offre publiée", spontanee: "Candidature spontanée", dsi_interne: "DSI interne" };
const CONTRATS = { stage: "Stage", alternance: "Alternance", autre: "Emploi" };
const SOURCES = {
  recherche_entreprises: "Annuaire entreprises", france_travail_offres: "France Travail",
  la_bonne_boite: "La Bonne Boîte", manuel: "Saisie manuelle", enrichissement_web: "Site web",
};
const FILTRES_DEFAUT = () => ({
  q: "", statut: [], type: [], distance_max: null, taille: [], secteur: [], technos: [],
  score_min: 0, favoris: false, priorite_min: 0, tri: "score", ordre: "desc",
});

// ------------------------------------------------------------------ utilitaires
function stVar(statut) { return { "--st": `var(--st-${statut})` }; }
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function fmtDate(s, heure = false) {
  if (!s) return "";
  const d = new Date(s.replace(" ", "T"));
  if (isNaN(d)) return s;
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" }) +
    (heure ? " à " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "");
}
function fmtKm(v) { return v == null ? "—" : `${Math.round(v)} km`; }
function lsGet(k, def) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch (e) { return def; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* stockage indisponible */ } }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function lien(url) { if (!url) return ""; return /^https?:\/\//.test(url) ? url : "https://" + url; }

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, init);
  if (r.status === 401 && path !== "/api/login") { location.href = "/login"; throw new Error("Connexion requise"); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* pas de JSON */ }
  if (!r.ok) {
    let msg = data && data.detail ? data.detail : `Erreur HTTP ${r.status}`;
    if (Array.isArray(msg)) msg = msg.map(x => x.msg).join(", ");
    throw new Error(msg);
  }
  return data;
}

// ------------------------------------------------------------------ état global
const store = reactive({
  view: lsGet("view", "accueil"),
  cibles: [],
  corbeille: [],
  loading: false,
  options: { statuts: STATUTS, types: [], tailles: [], secteurs: [], technos: [] },
  params: null,
  health: null,
  dash: null,
  filters: Object.assign(FILTRES_DEFAUT(), lsGet("filters", {})),
  selected: {},
  ficheId: null,
  refresh: null,
  toasts: [],
  modal: null,          // { type: 'manuel' | 'mail' | 'entretien', ... }
  theme: lsGet("theme", "auto"),
});

function toast(msg, kind = "info", ms = 4500) {
  const t = { id: Math.random(), msg, kind };
  store.toasts.push(t);
  // Comparaison par id : store.toasts contient des proxys réactifs, pas l'objet `t` lui-même
  setTimeout(() => { store.toasts = store.toasts.filter(x => x.id !== t.id); }, ms);
}

function queryString(extra = {}) {
  const f = { ...store.filters, ...extra };
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) {
    if (Array.isArray(v)) v.forEach(x => p.append(k, x));
    else if (v === true) p.append(k, "1");
    else if (v !== null && v !== "" && v !== false && v !== undefined && !(k.endsWith("_min") && v === 0)) p.append(k, v);
  }
  return p.toString();
}

async function chargerCibles() {
  store.loading = true;
  try { store.cibles = await api("/api/cibles?" + queryString()); }
  catch (e) { toast("Chargement impossible : " + e.message, "error"); }
  finally { store.loading = false; }
}
async function chargerCorbeille() {
  store.corbeille = await api("/api/cibles?corbeille=1&tri=nom");
}
async function chargerOptions() {
  try { store.options = await api("/api/filtres"); } catch (e) { /* garde les valeurs par défaut */ }
}
async function chargerDash() {
  try { store.dash = await api("/api/dashboard"); } catch (e) { toast(e.message, "error"); }
}
async function chargerParams() { store.params = await api("/api/parametres"); }
async function chargerHealth() { try { store.health = await api("/api/health"); } catch (e) { store.health = null; } }
async function toutRecharger() {
  await Promise.all([chargerCibles(), chargerOptions(), chargerDash()]);
  if (store.view === "corbeille") await chargerCorbeille();
}

// Met à jour une ligne de la liste locale sans tout recharger
function majLocale(fiche) {
  for (const list of [store.cibles, store.corbeille]) {
    const i = list.findIndex(c => c.id === fiche.id);
    if (i >= 0) Object.assign(list[i], {
      statut: fiche.statut, favori: fiche.favori, priorite: fiche.priorite, notes: fiche.notes,
      date_envoi: fiche.date_envoi, entretien_at: fiche.entretien_at, nom: fiche.nom, site_web: fiche.site_web,
    });
  }
}

// Changement de statut (demande une date si « Entretien prévu »)
async function changerStatut(cible, statut, entretien_at = null) {
  if (statut === "entretien" && !entretien_at) {
    store.modal = { type: "entretien", cible, valeur: cible.entretien_at || "" };
    return;
  }
  try {
    const f = await api(`/api/cibles/${cible.id}/statut`, { method: "POST", body: { statut, entretien_at } });
    majLocale(f);
    if (statut === "supprime") {
      store.cibles = store.cibles.filter(c => c.id !== cible.id);
      toast(`« ${f.nom} » mis à la corbeille (restaurable)`);
    }
    chargerDash();
    return f;
  } catch (e) { toast(e.message, "error"); }
}
async function majSuivi(cible, champs) {
  try { const f = await api(`/api/cibles/${cible.id}`, { method: "PATCH", body: champs }); majLocale(f); return f; }
  catch (e) { toast(e.message, "error"); }
}
function ouvrirFiche(id) { store.ficheId = id; }

// Actualisation des données avec suivi de progression
let pollTimer = null;
async function lancerRefresh(opts = {}) {
  try {
    store.refresh = await api("/api/refresh", { method: "POST", body: opts });
    suivreRefresh();
  } catch (e) { toast(e.message, "error"); }
}
function suivreRefresh() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const e = await api("/api/refresh/status");
      store.refresh = e;
      if (!e.en_cours) {
        clearInterval(pollTimer);
        const r = e.resume || {};
        toast("✅ Actualisation terminée : " + (r.texte || "aucune donnée"), "ok", 9000);
        for (const [nom, s] of Object.entries(e.sources || {})) {
          if (s.statut === "erreur") toast(`⚠️ ${s.label} : ${s.message}`, "error", 12000);
          if (s.statut === "ignoree") toast(`ℹ️ ${s.label} ignorée : ${s.message}`, "info", 9000);
          if (s.statut === "ok" && s.message) toast(`ℹ️ ${s.label} : ${s.message}`, "info", 9000);
        }
        setTimeout(() => { if (!store.refresh?.en_cours) store.refresh = null; }, 8000);
        toutRecharger();
      }
    } catch (err) { clearInterval(pollTimer); }
  }, 1000);
}

// ================================================================== composants
const ScoreBadge = {
  props: ["score", "detail"],
  template: `
    <span class="score" tabindex="0" :style="{'--s': score}">{{ score }}
      <span class="tip">
        <b>Score {{ score }}/100</b>
        <div v-for="d in detail" class="tip-line" :class="{neg: d.points < 0}"><b>{{ d.points > 0 ? '+' : '' }}{{ d.points }}</b><span>{{ d.raison }}</span></div>
      </span>
    </span>`,
};

const StatusBadge = {
  props: ["statut"],
  setup() { return { STATUT, stVar }; },
  template: `<span class="badge st" :style="stVar(statut)">{{ STATUT[statut]?.emoji }} {{ STATUT[statut]?.label }}</span>`,
};

const Stars = {
  props: ["modelValue"],
  emits: ["update:modelValue"],
  template: `
    <span class="stars" @click.stop>
      <button v-for="n in 5" :class="{on: n <= (modelValue || 0)}" :title="'Priorité ' + n"
        @click="$emit('update:modelValue', n === modelValue ? 0 : n)">★</button>
    </span>`,
};

const StatusSelect = {
  props: ["cible"],
  setup(props) {
    const choix = STATUTS.filter(s => s.id !== "supprime");
    return { choix, stVar, change: e => changerStatut(props.cible, e.target.value) };
  },
  template: `
    <select class="status-select" :style="stVar(cible.statut)" :value="cible.statut" @click.stop @change="change">
      <option v-for="s in choix" :value="s.id">{{ s.emoji }} {{ s.label }}</option>
    </select>`,
};

// ------------------------------------------------------------------ filtres
const FiltersPanel = {
  props: { showStatut: { default: true } },
  setup() {
    const f = store.filters;
    const ouvert = ref(lsGet("filtersOpen", true));
    watch(ouvert, v => lsSet("filtersOpen", v));
    const rayon = computed(() => store.params?.rayon_km || 50);
    const toggle = (arr, v) => { const i = arr.indexOf(v); i >= 0 ? arr.splice(i, 1) : arr.push(v); };
    const nbActifs = computed(() => ["statut", "type", "taille", "secteur", "technos"].reduce((n, k) => n + f[k].length, 0)
      + (f.distance_max != null ? 1 : 0) + (f.score_min ? 1 : 0) + (f.favoris ? 1 : 0) + (f.priorite_min ? 1 : 0));
    const reset = () => { const q = f.q; Object.assign(f, FILTRES_DEFAUT(), { q }); };
    return { f, store, ouvert, rayon, toggle, nbActifs, reset, stVar, STATUTS };
  },
  template: `
  <div class="card" style="margin-bottom:14px">
    <div class="filters-head">
      <button class="btn ghost" @click="ouvert = !ouvert">{{ ouvert ? '▾' : '▸' }} Filtres <span v-if="nbActifs" class="badge">{{ nbActifs }} actif(s)</span></button>
      <div class="row">
        <label class="row small"><input type="checkbox" v-model="f.favoris"> ⭐ Favoris uniquement</label>
        <button class="btn sm" @click="reset" :disabled="!nbActifs">Réinitialiser</button>
      </div>
    </div>
    <div class="filters" v-show="ouvert">
      <div v-if="showStatut">
        <div class="section-title">Statut</div>
        <div class="toggle-group">
          <button v-for="s in STATUTS.filter(x => x.id !== 'supprime')" class="toggle" :class="{'st-on': f.statut.includes(s.id)}"
            :style="stVar(s.id)" @click="toggle(f.statut, s.id)">{{ s.emoji }} {{ s.label }}</button>
        </div>
      </div>
      <div>
        <div class="section-title">Type</div>
        <div class="toggle-group">
          <button v-for="t in store.options.types" class="toggle" :class="{on: f.type.includes(t.id)}" @click="toggle(f.type, t.id)">{{ t.label }}</button>
        </div>
        <div class="section-title" style="margin-top:10px">Taille</div>
        <div class="toggle-group">
          <button v-for="t in store.options.tailles" class="toggle" :class="{on: f.taille.includes(t.id)}" @click="toggle(f.taille, t.id)">{{ t.label }}</button>
        </div>
      </div>
      <div>
        <div class="section-title">Distance max : {{ f.distance_max == null ? 'tout (' + rayon + ' km)' : f.distance_max + ' km' }}</div>
        <input type="range" min="1" :max="rayon" :value="f.distance_max ?? rayon"
          @input="f.distance_max = +$event.target.value >= rayon ? null : +$event.target.value">
        <div class="section-title" style="margin-top:10px">Score minimum : {{ f.score_min }}</div>
        <input type="range" min="0" max="100" step="5" v-model.number="f.score_min">
        <div class="section-title" style="margin-top:10px">Priorité minimum</div>
        <div class="stars">
          <button v-for="n in 5" :class="{on: n <= f.priorite_min}" @click="f.priorite_min = n === f.priorite_min ? 0 : n">★</button>
        </div>
      </div>
      <div>
        <div class="section-title">Secteur</div>
        <select multiple v-model="f.secteur" style="height:110px">
          <option v-for="s in store.options.secteurs" :value="s">{{ s }}</option>
        </select>
        <div class="small muted">Ctrl/Cmd + clic pour plusieurs</div>
      </div>
      <div>
        <div class="section-title">Technos (toutes requises)</div>
        <div class="toggle-group">
          <button v-for="t in store.options.technos" class="toggle" :class="{on: f.technos.includes(t)}" @click="toggle(f.technos, t)">{{ t }}</button>
          <span v-if="!store.options.technos.length" class="muted small">Aucune techno détectée pour l'instant</span>
        </div>
      </div>
    </div>
  </div>`,
};

// ------------------------------------------------------------------ accueil
const DashboardView = {
  components: { StatusBadge, ScoreBadge },
  setup() {
    const canvas = ref(null);
    let chart = null;
    const d = computed(() => store.dash);
    const dessiner = () => {
      if (!canvas.value || !d.value) return;
      const pts = d.value.progression;
      if (chart) chart.destroy();
      if (!pts.length) { chart = null; return; }
      const couleur = cssVar("--accent"), grille = cssVar("--border"), texte = cssVar("--muted");
      chart = markRaw(new Chart(canvas.value, {
        type: "line",
        data: {
          labels: pts.map(p => new Date(p.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })),
          datasets: [{ label: "Candidatures envoyées (cumul)", data: pts.map(p => p.cumul), borderColor: couleur,
            backgroundColor: couleur + "33", fill: true, tension: .25, pointRadius: 3, borderWidth: 2, stepped: false }],
        },
        options: {
          responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
          scales: { x: { grid: { color: grille }, ticks: { color: texte } },
                    y: { beginAtZero: true, ticks: { precision: 0, color: texte }, grid: { color: grille } } },
        },
      }));
    };
    onMounted(async () => { await chargerDash(); await nextTick(); dessiner(); });
    watch(() => store.dash, () => nextTick(dessiner));
    onBeforeUnmount(() => chart && chart.destroy());
    const allerStatut = s => { Object.assign(store.filters, FILTRES_DEFAUT(), { statut: [s] }); store.view = "tableau"; };
    const kpis = computed(() => STATUTS.filter(s => s.id !== "supprime"));
    return { d, canvas, kpis, allerStatut, ouvrirFiche, fmtDate, fmtKm, stVar, TYPES, store, lancerRefresh };
  },
  template: `
  <div v-if="!d" class="empty">Chargement…</div>
  <div v-else>
    <div v-if="d.total_actifs === 0" class="card empty" style="margin-bottom:16px">
      <h2>Bienvenue 👋</h2>
      <p>La base est vide. Lance une première actualisation pour récupérer les entreprises autour de Brest.</p>
      <button class="btn primary" @click="lancerRefresh()" :disabled="store.refresh?.en_cours">🔄 Actualiser les données</button>
    </div>
    <div class="kpis">
      <div class="kpi" style="--st: var(--accent)" @click="store.view='tableau'">
        <div class="v">{{ d.total_actifs }}</div><div class="l">Cibles au total</div>
      </div>
      <div class="kpi" style="--st: var(--st-envoyee)">
        <div class="v">{{ d.envoyees_semaine }}</div><div class="l">📨 Envoyées cette semaine</div>
      </div>
      <div class="kpi" style="--st: var(--st-a_relancer)" @click="allerStatut('a_relancer')">
        <div class="v">{{ d.a_relancer.length }}</div><div class="l">🔔 Relances à faire</div>
      </div>
      <div class="kpi" v-for="s in kpis" :style="stVar(s.id)" @click="allerStatut(s.id)">
        <div class="v">{{ d.compteurs[s.id] }}</div><div class="l">{{ s.emoji }} {{ s.label }}</div>
      </div>
    </div>
    <div class="dash-grid">
      <div class="card">
        <h3>🔔 Relances à faire aujourd'hui</h3>
        <div v-if="!d.a_relancer.length" class="muted small">Rien à relancer 🎉</div>
        <div v-for="r in d.a_relancer" class="list-item" @click="ouvrirFiche(r.id)">
          <div class="grow" style="min-width:0"><div class="li-title">{{ r.nom }}</div><div class="small muted">{{ r.titre || 'Candidature spontanée' }} · envoyée le {{ fmtDate(r.date_envoi) }}</div></div>
        </div>
      </div>
      <div class="card">
        <h3>🗓️ Prochains entretiens</h3>
        <div v-if="!d.entretiens.length" class="muted small">Aucun entretien prévu pour l'instant.</div>
        <div v-for="r in d.entretiens" class="list-item" @click="ouvrirFiche(r.id)">
          <div class="grow" style="min-width:0"><div class="li-title">{{ r.nom }}</div><div class="small muted">{{ fmtDate(r.entretien_at, true) }} · {{ r.ville }}</div></div>
        </div>
      </div>
      <div class="card">
        <h3>📈 Progression des candidatures</h3>
        <div class="small muted" style="margin-bottom:6px">{{ d.envoyees_total }} candidature(s) envoyée(s) au total</div>
        <div class="chart-box" v-show="d.progression.length"><canvas ref="canvas"></canvas></div>
        <div v-if="!d.progression.length" class="muted small">Le graphique apparaîtra dès la première candidature envoyée.</div>
      </div>
      <div class="card">
        <h3>🆕 Meilleures cibles pas encore vues</h3>
        <div v-if="!d.top_nouveaux.length" class="muted small">Tout a été vu.</div>
        <div v-for="r in d.top_nouveaux" class="list-item" @click="ouvrirFiche(r.id)">
          <span class="score" :style="{'--s': r.score}">{{ r.score }}</span>
          <div class="grow" style="min-width:0"><div class="li-title">{{ r.titre || r.nom }}</div>
            <div class="small muted">{{ r.titre ? r.nom + ' · ' : '' }}{{ TYPES[r.type] }} · {{ fmtKm(r.distance_km) }}</div></div>
        </div>
      </div>
      <div class="card">
        <h3>📊 Répartition</h3>
        <div v-for="(label, t) in TYPES" class="list-item" style="cursor:default">
          <span class="badge type" :class="'type-' + t">{{ label }}</span><span class="grow"></span><b>{{ d.par_type[t] || 0 }}</b>
        </div>
        <div class="small muted" style="margin-top:8px" v-if="d.derniere_actualisation">Dernière actualisation : {{ fmtDate(d.derniere_actualisation.fin, true) }}</div>
      </div>
    </div>
  </div>`,
};

// ------------------------------------------------------------------ tableau
const TableView = {
  components: { FiltersPanel, ScoreBadge, StatusSelect, Stars, StatusBadge },
  setup() {
    const limite = ref(150);
    const cols = [
      ["nom", "Entreprise / offre"], ["type", "Type"], ["statut", "Statut"], ["score", "Score"],
      ["distance_km", "Distance"], ["ville", "Ville"], ["taille", "Taille"], ["technos", "Technos"], ["priorite", "Priorité"],
    ];
    const trier = c => {
      if (c === "technos") return;
      const f = store.filters;
      if (f.tri === c) f.ordre = f.ordre === "asc" ? "desc" : "asc";
      else { f.tri = c; f.ordre = ["nom", "distance_km", "ville", "type", "statut"].includes(c) ? "asc" : "desc"; }
    };
    const nbSel = computed(() => Object.keys(store.selected).length);
    const tousSel = computed(() => store.cibles.length > 0 && store.cibles.every(c => store.selected[c.id]));
    const toutSelectionner = () => {
      if (tousSel.value) store.selected = {};
      else store.selected = Object.fromEntries(store.cibles.map(c => [c.id, true]));
    };
    const toggleSel = id => { if (store.selected[id]) delete store.selected[id]; else store.selected[id] = true; };
    const lotStatut = ref("");
    const appliquerLot = async () => {
      if (!lotStatut.value) return;
      const ids = Object.keys(store.selected).map(Number);
      try {
        await api("/api/lot/statut", { method: "POST", body: { ids, statut: lotStatut.value } });
        toast(`${ids.length} ligne(s) passée(s) en « ${STATUT[lotStatut.value].label} »`, "ok");
        store.selected = {}; lotStatut.value = "";
        toutRecharger();
      } catch (e) { toast(e.message, "error"); }
    };
    const exporter = fmt => { window.location.href = `/api/export?format=${fmt}&` + queryString(); };
    const lignes = computed(() => store.cibles.slice(0, limite.value));
    return { store, cols, trier, lignes, limite, nbSel, tousSel, toutSelectionner, toggleSel, lotStatut, appliquerLot,
      exporter, ouvrirFiche, majSuivi, fmtKm, TYPES, CONTRATS, STATUTS, stVar };
  },
  template: `
  <div>
    <FiltersPanel />
    <div class="bulk-bar" v-if="nbSel">
      <b>{{ nbSel }} sélectionnée(s)</b>
      <select v-model="lotStatut" style="width:auto">
        <option value="">Changer le statut…</option>
        <option v-for="s in STATUTS" :value="s.id">{{ s.emoji }} {{ s.label }}</option>
      </select>
      <button class="btn primary sm" :disabled="!lotStatut" @click="appliquerLot">Appliquer</button>
      <button class="btn sm" @click="store.selected = {}">Désélectionner</button>
    </div>
    <div class="row" style="margin-bottom:10px">
      <b>{{ store.cibles.length }} résultat(s)</b><span v-if="store.loading" class="muted small">chargement…</span>
      <span class="grow"></span>
      <button class="btn sm" @click="exporter('csv')">⬇️ CSV</button>
      <button class="btn sm" @click="exporter('xlsx')">⬇️ Excel</button>
    </div>
    <div class="table-wrap">
      <table class="data">
        <thead><tr>
          <th style="width:28px" @click.stop><input type="checkbox" :checked="tousSel" @change="toutSelectionner" title="Tout sélectionner (liste filtrée)"></th>
          <th style="width:28px" title="Favori">⭐</th>
          <th v-for="[k, l] in cols" @click="trier(k)" :class="{sorted: store.filters.tri === k, 'hide-mobile': ['ville','taille','technos','priorite'].includes(k)}">
            {{ l }} <span v-if="store.filters.tri === k">{{ store.filters.ordre === 'asc' ? '▲' : '▼' }}</span></th>
        </tr></thead>
        <tbody>
          <tr v-for="c in lignes" :key="c.id" @click="ouvrirFiche(c.id)" :class="{selected: store.selected[c.id], inactive: c.offre_id && !c.offre_active}">
            <td @click.stop><input type="checkbox" :checked="!!store.selected[c.id]" @change="toggleSel(c.id)"></td>
            <td @click.stop><button class="icon-btn" :class="{on: c.favori}" @click="majSuivi(c, {favori: !c.favori})" :title="c.favori ? 'Retirer des favoris' : 'Ajouter aux favoris'">{{ c.favori ? '★' : '☆' }}</button></td>
            <td class="name-cell">
              <span class="n">{{ c.titre || c.nom }}</span>
              <span class="s">{{ c.titre ? c.nom : (c.secteur || '') }}<template v-if="c.offre_id && !c.offre_active"> · offre expirée</template></span>
            </td>
            <td><span class="badge type" :class="'type-' + c.type">{{ c.type === 'offre' ? (CONTRATS[c.type_contrat] || 'Offre') : TYPES[c.type] }}</span></td>
            <td><StatusSelect :cible="c" /></td>
            <td @click.stop><ScoreBadge :score="c.score" :detail="c.score_detail" /></td>
            <td class="nowrap">{{ fmtKm(c.distance_km) }}</td>
            <td class="hide-mobile">{{ c.ville }}</td>
            <td class="hide-mobile nowrap small">{{ c.taille_libelle }}</td>
            <td class="hide-mobile" style="max-width:220px"><span v-for="t in c.technos.slice(0, 4)" class="chip">{{ t }}</span><span v-if="c.technos.length > 4" class="small muted">+{{ c.technos.length - 4 }}</span></td>
            <td class="hide-mobile" @click.stop><Stars :modelValue="c.priorite" @update:modelValue="v => majSuivi(c, {priorite: v})" /></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!store.cibles.length && !store.loading" class="empty">Aucun résultat avec ces filtres.</div>
    </div>
    <div class="row" style="justify-content:center; margin-top:12px" v-if="store.cibles.length > limite">
      <button class="btn" @click="limite += 150">Afficher plus ({{ store.cibles.length - limite }} restantes)</button>
    </div>
  </div>`,
};

// ------------------------------------------------------------------ kanban
const KanbanView = {
  components: { FiltersPanel, ScoreBadge },
  setup() {
    const colonnes = STATUTS.filter(s => s.id !== "supprime");
    const limites = reactive(Object.fromEntries(colonnes.map(s => [s.id, 40])));
    const parStatut = computed(() => {
      const g = Object.fromEntries(colonnes.map(s => [s.id, []]));
      for (const c of store.cibles) if (g[c.statut]) g[c.statut].push(c);
      return g;
    });
    const corps = ref({});
    const sortables = [];
    onMounted(() => {
      for (const s of colonnes) {
        const el = corps.value[s.id];
        if (!el) continue;
        sortables.push(Sortable.create(el, {
          group: "kanban", sort: false, animation: 150, ghostClass: "sortable-ghost", dragClass: "sortable-drag",
          onEnd(evt) {
            if (evt.from === evt.to) return;
            // Remettre l'élément à sa place : c'est Vue qui redessine après la mise à jour du statut
            evt.from.insertBefore(evt.item, evt.from.children[evt.oldIndex] || null);
            const cible = store.cibles.find(c => c.id === +evt.item.dataset.id);
            if (cible) changerStatut(cible, evt.to.dataset.statut);
          },
        }));
      }
    });
    onBeforeUnmount(() => sortables.forEach(s => s.destroy()));
    const setCorps = id => el => { if (el) corps.value[id] = el; };
    return { colonnes, parStatut, limites, setCorps, ouvrirFiche, fmtKm, stVar, TYPES, CONTRATS };
  },
  template: `
  <div>
    <FiltersPanel :showStatut="false" />
    <div class="kanban">
      <div class="kcol" v-for="s in colonnes" :key="s.id" :style="stVar(s.id)">
        <div class="kcol-head"><span>{{ s.emoji }} {{ s.label }}</span><span class="muted">{{ parStatut[s.id].length }}</span></div>
        <div class="kcol-body" :ref="setCorps(s.id)" :data-statut="s.id">
          <div class="kcard" v-for="c in parStatut[s.id].slice(0, limites[s.id])" :key="c.id" :data-id="c.id" @click="ouvrirFiche(c.id)">
            <div class="row" style="justify-content:space-between; flex-wrap:nowrap">
              <span class="t">{{ c.titre || c.nom }}</span>
              <span class="score" :style="{'--s': c.score}" style="font-size:11px; min-width:30px">{{ c.score }}</span>
            </div>
            <div class="small muted">{{ c.titre ? c.nom + ' · ' : '' }}{{ c.ville }} · {{ fmtKm(c.distance_km) }}</div>
            <div class="small" style="margin-top:4px"><span class="badge type" :class="'type-' + c.type" style="font-size:10px">{{ c.type === 'offre' ? (CONTRATS[c.type_contrat] || 'Offre') : TYPES[c.type] }}</span>
              <span v-if="c.favori" style="color:#eab308"> ★</span></div>
          </div>
        </div>
        <button v-if="parStatut[s.id].length > limites[s.id]" class="btn sm ghost" style="margin:6px" @click="limites[s.id] += 40">+ {{ parStatut[s.id].length - limites[s.id] }} autres</button>
      </div>
    </div>
  </div>`,
};

// ------------------------------------------------------------------ carte
const MapView = {
  components: { FiltersPanel },
  setup() {
    const el = ref(null);
    let map = null, calque = null, cercle = null;
    const dessiner = () => {
      if (!map || !store.params) return;
      const v = store.params.ville_depart;
      if (cercle) cercle.remove();
      cercle = L.circle([v.lat, v.lon], { radius: store.params.rayon_km * 1000, color: cssVar("--accent"), weight: 1.5, fillOpacity: 0.04 }).addTo(map);
      calque.clearLayers();
      L.marker([v.lat, v.lon], { title: v.nom }).addTo(calque).bindTooltip(`📍 ${v.nom} (départ)`);
      for (const c of store.cibles) {
        if (c.lat == null || c.lon == null) continue;
        const couleur = cssVar(`--st-${c.statut}`);
        const m = L.circleMarker([c.lat, c.lon], {
          radius: c.favori ? 9 : 7, color: "#fff", weight: 1.5, fillColor: couleur, fillOpacity: 0.9,
        });
        m.bindTooltip(`<b>${(c.titre || c.nom).replace(/</g, "&lt;")}</b><br>${STATUT[c.statut].emoji} ${STATUT[c.statut].label} · score ${c.score}`);
        m.on("click", () => ouvrirFiche(c.id));
        m.addTo(calque);
      }
    };
    onMounted(async () => {
      if (!store.params) await chargerParams();
      const v = store.params.ville_depart;
      map = markRaw(L.map(el.value, { preferCanvas: true }).setView([v.lat, v.lon], 9));
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
      calque = markRaw(L.layerGroup().addTo(map));
      dessiner();
    });
    watch(() => [store.cibles, store.cibles.map(c => c.statut + c.favori).join()], dessiner);
    onBeforeUnmount(() => map && map.remove());
    const sansCoord = computed(() => store.cibles.filter(c => c.lat == null).length);
    return { el, STATUTS, stVar, sansCoord, store };
  },
  template: `
  <div>
    <FiltersPanel />
    <div id="map" ref="el"></div>
    <div class="legend">
      <span v-for="s in STATUTS.filter(x => x.id !== 'supprime')" :style="stVar(s.id)"><i></i>{{ s.label }}</span>
      <span class="muted">· Cercle : {{ store.params?.rayon_km }} km autour de {{ store.params?.ville_depart?.nom }}</span>
      <span v-if="sansCoord" class="muted">· {{ sansCoord }} sans coordonnées</span>
    </div>
  </div>`,
};

// ------------------------------------------------------------------ corbeille
const TrashView = {
  setup() {
    onMounted(chargerCorbeille);
    const restaurer = async c => {
      try { await api(`/api/cibles/${c.id}/restaurer`, { method: "POST" }); toast(`« ${c.nom} » restauré`, "ok"); await chargerCorbeille(); chargerCibles(); chargerDash(); }
      catch (e) { toast(e.message, "error"); }
    };
    const toutRestaurer = async () => { for (const c of [...store.corbeille]) await api(`/api/cibles/${c.id}/restaurer`, { method: "POST" }); await chargerCorbeille(); toutRecharger(); };
    return { store, restaurer, toutRestaurer, ouvrirFiche, STATUT, TYPES, fmtKm };
  },
  template: `
  <div>
    <div class="row" style="margin-bottom:12px">
      <p class="muted grow" style="margin:0">Les éléments supprimés sont masqués partout mais jamais effacés. Ils retrouvent leur statut précédent quand on les restaure.</p>
      <button class="btn" v-if="store.corbeille.length" @click="toutRestaurer">♻️ Tout restaurer</button>
    </div>
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>Entreprise / offre</th><th>Type</th><th>Statut avant suppression</th><th>Distance</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in store.corbeille" :key="c.id" @click="ouvrirFiche(c.id)">
            <td class="name-cell"><span class="n">{{ c.titre || c.nom }}</span><span class="s">{{ c.titre ? c.nom : c.ville }}</span></td>
            <td>{{ TYPES[c.type] }}</td>
            <td>{{ STATUT[c.statut_avant_suppression || 'vu']?.emoji }} {{ STATUT[c.statut_avant_suppression || 'vu']?.label }}</td>
            <td>{{ fmtKm(c.distance_km) }}</td>
            <td @click.stop><button class="btn sm" @click="restaurer(c)">♻️ Restaurer</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!store.corbeille.length" class="empty">La corbeille est vide.</div>
    </div>
  </div>`,
};

// ------------------------------------------------------------------ fiche détaillée
const FicheDrawer = {
  components: { ScoreBadge, Stars, StatusBadge },
  setup() {
    const f = ref(null);
    const edition = ref(false);
    const form = reactive({});
    const enrichissement = ref(false);
    const charger = async () => {
      if (!store.ficheId) { f.value = null; return; }
      try {
        f.value = await api(`/api/cibles/${store.ficheId}?marquer_vu=true`);
        majLocale(f.value);
        edition.value = false;
      } catch (e) { toast(e.message, "error"); store.ficheId = null; }
    };
    watch(() => store.ficheId, charger, { immediate: true });
    const fermer = () => { store.ficheId = null; };
    const statut = async s => { const r = await changerStatut(f.value, s); if (r) f.value = r; };
    const suivi = async champs => { const r = await majSuivi(f.value, champs); if (r) f.value = r; };
    const sauverNotes = debounce(v => suivi({ notes: v }), 800);
    const commencerEdition = () => {
      for (const k of ["nom", "siret", "adresse", "code_postal", "ville", "site_web", "page_contact", "page_recrutement",
        "email_public", "tel_public", "secteur", "naf", "description_activite"]) form[k] = f.value[k] || "";
      edition.value = true;
    };
    const sauverEdition = async () => {
      try {
        await api(`/api/entreprises/${f.value.entreprise_id}`, { method: "PATCH", body: { ...form } });
        toast("Fiche entreprise mise à jour", "ok"); await charger(); chargerCibles();
      } catch (e) { toast(e.message, "error"); }
    };
    const enrichir = async () => {
      enrichissement.value = true;
      try {
        const r = await api(`/api/entreprises/${f.value.entreprise_id}/enrichir`, { method: "POST" });
        toast(r.message, r.trouve ? "ok" : "info", 7000); await charger();
      } catch (e) { toast(e.message, "error"); }
      finally { enrichissement.value = false; }
    };
    const mail = () => { store.modal = { type: "mail", cible: f.value }; };
    const restaurer = async () => {
      try { f.value = await api(`/api/cibles/${f.value.id}/restaurer`, { method: "POST" }); toast("Restauré", "ok"); toutRecharger(); }
      catch (e) { toast(e.message, "error"); }
    };
    const onKey = e => { if (e.key === "Escape" && !store.modal) fermer(); };
    onMounted(() => window.addEventListener("keydown", onKey));
    onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
    const recherche = computed(() => f.value ? "https://www.qwant.com/?q=" + encodeURIComponent(`${f.value.nom.split(" (")[0]} ${f.value.ville || ""}`) : "");
    return { f, store, fermer, statut, suivi, sauverNotes, edition, form, commencerEdition, sauverEdition, enrichir, enrichissement,
      mail, restaurer, recherche, STATUTS, STATUT, TYPES, CONTRATS, SOURCES, stVar, fmtDate, fmtKm, lien, ouvrirFiche };
  },
  template: `
  <template v-if="store.ficheId">
    <div class="overlay" @click="fermer"></div>
    <aside class="drawer" v-if="f">
      <div class="drawer-head">
        <div class="grow" style="min-width:0">
          <div class="row small" style="margin-bottom:4px">
            <span class="badge type" :class="'type-' + f.type">{{ TYPES[f.type] }}</span>
            <span v-if="f.type_contrat" class="badge">{{ CONTRATS[f.type_contrat] }}</span>
            <span v-if="f.offre_id && !f.offre_active" class="badge" style="color:var(--danger)">Offre expirée</span>
          </div>
          <h2>{{ f.titre || f.nom }}</h2>
          <div class="muted" v-if="f.titre">{{ f.nom }}</div>
          <div class="muted small">{{ f.ville }}<template v-if="f.distance_km != null"> · {{ fmtKm(f.distance_km) }} de {{ store.params?.ville_depart?.nom || 'Brest' }}</template></div>
        </div>
        <ScoreBadge :score="f.score" :detail="f.score_detail" />
        <button class="icon-btn" :class="{on: f.favori}" style="font-size:22px" @click="suivi({favori: !f.favori})" title="Favori">{{ f.favori ? '★' : '☆' }}</button>
        <button class="icon-btn" style="font-size:22px" @click="fermer" title="Fermer (Échap)">✕</button>
      </div>

      <div>
        <div class="section-title">Statut</div>
        <div class="status-buttons">
          <button v-for="s in STATUTS" :style="stVar(s.id)" :class="{on: f.statut === s.id}" @click="statut(s.id)">{{ s.emoji }} {{ s.label }}</button>
        </div>
        <div class="row small" style="margin-top:8px" v-if="f.statut === 'supprime'">
          <span class="muted">Dans la corbeille.</span>
          <button class="btn sm" @click="restaurer">♻️ Restaurer</button>
        </div>
        <div class="row small" style="margin-top:8px">
          <span v-if="f.date_envoi">📨 Envoyée le {{ fmtDate(f.date_envoi, true) }}</span>
          <label class="row" v-if="f.statut === 'entretien' || f.entretien_at">🗓️ Entretien :
            <input type="datetime-local" style="width:auto" :value="(f.entretien_at || '').replace(' ', 'T').slice(0, 16)" @change="suivi({entretien_at: $event.target.value})">
          </label>
        </div>
        <div class="row" style="margin-top:8px">
          <span class="small muted">Priorité</span>
          <Stars :modelValue="f.priorite" @update:modelValue="v => suivi({priorite: v})" />
          <span class="grow"></span>
          <button class="btn sm" @click="mail">✉️ Modèle de mail</button>
        </div>
      </div>

      <div>
        <div class="section-title">Notes</div>
        <textarea :value="f.notes" @input="sauverNotes($event.target.value)" placeholder="Qui j'ai eu au téléphone, ce qu'ils ont dit…" rows="4"></textarea>
      </div>

      <div>
        <div class="section-title">Liens</div>
        <div class="row">
          <a v-if="f.offre_url" class="btn sm" :href="f.offre_url" target="_blank" rel="noopener">🔗 Voir l'offre</a>
          <a v-if="f.site_web" class="btn sm" :href="lien(f.site_web)" target="_blank" rel="noopener">🌐 Site web</a>
          <a v-if="f.page_recrutement" class="btn sm" :href="lien(f.page_recrutement)" target="_blank" rel="noopener">💼 Recrutement</a>
          <a v-if="f.page_contact" class="btn sm" :href="lien(f.page_contact)" target="_blank" rel="noopener">📇 Contact</a>
          <a v-if="f.siret" class="btn sm" :href="'https://annuaire-entreprises.data.gouv.fr/etablissement/' + f.siret" target="_blank" rel="noopener">🏛️ Annuaire</a>
          <a class="btn sm" :href="recherche" target="_blank" rel="noopener">🔍 Rechercher</a>
          <button class="btn sm" @click="enrichir" :disabled="enrichissement">{{ enrichissement ? '⏳ Recherche…' : '✨ Trouver site / contact' }}</button>
        </div>
      </div>

      <div v-if="f.technos.length">
        <div class="section-title">Missions et technos détectées</div>
        <span v-for="t in f.technos" class="chip">{{ t }}</span>
      </div>

      <div v-if="f.offre_description || f.description_activite">
        <div class="section-title">{{ f.offre_description ? "Description de l'offre" : "Activité" }}</div>
        <div class="desc">{{ f.offre_description || f.description_activite }}</div>
        <div v-if="f.offre_description && f.description_activite" class="desc" style="margin-top:6px">{{ f.description_activite }}</div>
      </div>

      <div>
        <div class="row"><div class="section-title grow">Entreprise</div><button class="btn sm" v-if="!edition" @click="commencerEdition">✏️ Modifier</button></div>
        <dl class="info-grid" v-if="!edition">
          <dt>Nom</dt><dd>{{ f.nom }}</dd>
          <dt>SIRET</dt><dd>{{ f.siret || '—' }}</dd>
          <dt>Secteur</dt><dd>{{ f.secteur || '—' }} <span class="muted" v-if="f.naf">({{ f.naf }})</span></dd>
          <dt>Taille</dt><dd>{{ f.taille_libelle }}</dd>
          <dt>Adresse</dt><dd>{{ f.adresse || f.lieu || '—' }}</dd>
          <dt>Contact public</dt><dd><a v-if="f.email_public" :href="'mailto:' + f.email_public">{{ f.email_public }}</a><span v-if="f.email_public && f.tel_public"> · </span><a v-if="f.tel_public" :href="'tel:' + f.tel_public">{{ f.tel_public }}</a><span v-if="!f.email_public && !f.tel_public">—</span></dd>
          <dt>Création</dt><dd>{{ f.date_creation ? fmtDate(f.date_creation) : '—' }}</dd>
          <dt>Sources</dt><dd>{{ f.sources.map(s => SOURCES[s] || s).join(', ') || '—' }}<span class="muted small" v-if="f.fetched_at"> · récupéré le {{ fmtDate(f.fetched_at, true) }}</span></dd>
          <template v-if="f.date_publication"><dt>Publication</dt><dd>{{ fmtDate(f.date_publication) }}</dd></template>
        </dl>
        <div v-else class="form-grid">
          <label class="field full"><span>Nom</span><input type="text" v-model="form.nom"></label>
          <label class="field"><span>SIRET</span><input type="text" v-model="form.siret"></label>
          <label class="field"><span>Secteur</span><input type="text" v-model="form.secteur"></label>
          <label class="field full"><span>Adresse</span><input type="text" v-model="form.adresse"></label>
          <label class="field"><span>Code postal</span><input type="text" v-model="form.code_postal"></label>
          <label class="field"><span>Ville</span><input type="text" v-model="form.ville"></label>
          <label class="field"><span>Site web</span><input type="url" v-model="form.site_web"></label>
          <label class="field"><span>Page contact</span><input type="url" v-model="form.page_contact"></label>
          <label class="field"><span>Page recrutement</span><input type="url" v-model="form.page_recrutement"></label>
          <label class="field"><span>Email générique</span><input type="email" v-model="form.email_public"></label>
          <label class="field"><span>Téléphone</span><input type="tel" v-model="form.tel_public"></label>
          <label class="field full"><span>Description de l'activité</span><textarea v-model="form.description_activite"></textarea></label>
          <div class="row full"><button class="btn primary" @click="sauverEdition">Enregistrer</button><button class="btn" @click="edition = false">Annuler</button></div>
        </div>
      </div>

      <div v-if="f.liees.length">
        <div class="section-title">Autres pistes dans cette entreprise</div>
        <div v-for="l in f.liees" class="list-item" @click="ouvrirFiche(l.id)">
          <span class="badge st" :style="stVar(l.statut)">{{ STATUT[l.statut].emoji }}</span>
          <span class="li-title">{{ l.titre || TYPES[l.type] }}</span>
        </div>
      </div>

      <div>
        <div class="section-title">Historique</div>
        <ul class="timeline">
          <li v-for="h in f.historique" :style="stVar(h.nouveau_statut)">
            <b>{{ STATUT[h.nouveau_statut]?.emoji }} {{ STATUT[h.nouveau_statut]?.label }}</b>
            <span class="muted small"> · {{ fmtDate(h.created_at, true) }}</span>
            <div class="small muted" v-if="h.commentaire">{{ h.commentaire }}</div>
          </li>
        </ul>
      </div>
    </aside>
  </template>`,
};

// ------------------------------------------------------------------ modales
const EntretienModal = {
  setup() {
    const m = store.modal;
    const valeur = ref((m.valeur || "").replace(" ", "T").slice(0, 16));
    const valider = async () => {
      const r = await changerStatut(m.cible, "entretien", valeur.value || null);
      store.modal = null;
      if (r && store.ficheId === m.cible.id) { store.ficheId = null; await nextTick(); store.ficheId = r.id; }
    };
    const sansDate = async () => {
      await api(`/api/cibles/${m.cible.id}/statut`, { method: "POST", body: { statut: "entretien" } }).then(majLocale);
      store.modal = null; chargerDash();
      if (store.ficheId === m.cible.id) { store.ficheId = null; await nextTick(); store.ficheId = m.cible.id; }
    };
    return { m, valeur, valider, sansDate, store };
  },
  template: `
    <div class="modal-overlay" @click="store.modal = null"></div>
    <div class="modal" style="width:min(420px, calc(100vw - 32px))">
      <h2>🗓️ Entretien prévu</h2>
      <div class="muted">{{ m.cible.titre || m.cible.nom }}</div>
      <label class="field"><span>Date et heure</span><input type="datetime-local" v-model="valeur"></label>
      <div class="row"><button class="btn primary" @click="valider" :disabled="!valeur">Enregistrer</button>
        <button class="btn" @click="sansDate">Sans date pour l'instant</button><button class="btn ghost" @click="store.modal = null">Annuler</button></div>
    </div>`,
};

const MailModal = {
  setup() {
    const m = store.modal;
    const mail = ref(null);
    onMounted(async () => { try { mail.value = await api(`/api/cibles/${m.cible.id}/mail`); } catch (e) { toast(e.message, "error"); store.modal = null; } });
    const copier = async (txt, quoi) => {
      try { await navigator.clipboard.writeText(txt); toast(`${quoi} copié dans le presse-papiers`, "ok"); }
      catch (e) { toast("Copie impossible : sélectionne le texte manuellement", "error"); }
    };
    const mailto = computed(() => mail.value ? `mailto:${mail.value.destinataire}?subject=${encodeURIComponent(mail.value.objet)}&body=${encodeURIComponent(mail.value.corps)}` : "#");
    return { m, mail, copier, mailto, store };
  },
  template: `
    <div class="modal-overlay" @click="store.modal = null"></div>
    <div class="modal">
      <h2>✉️ Candidature spontanée — {{ m.cible.nom }}</h2>
      <div v-if="!mail" class="muted">Préparation…</div>
      <template v-else>
        <label class="field"><span>Objet</span><input type="text" v-model="mail.objet"></label>
        <label class="field"><span>Message</span><textarea v-model="mail.corps" rows="14"></textarea></label>
        <div class="small muted">Le modèle et ton profil se modifient dans Réglages. N'oublie pas de joindre ton CV.</div>
        <div class="row">
          <button class="btn primary" @click="copier(mail.corps, 'Message')">📋 Copier le message</button>
          <button class="btn" @click="copier(mail.objet, 'Objet')">📋 Copier l'objet</button>
          <a class="btn" :href="mailto">📧 Ouvrir dans ma messagerie</a>
          <span class="grow"></span><button class="btn ghost" @click="store.modal = null">Fermer</button>
        </div>
      </template>
    </div>`,
};

const ManuelModal = {
  setup() {
    const f = reactive({ type: "spontanee", type_contrat: "stage", nom: "", siret: "", adresse: "", code_postal: "", ville: "Brest",
      site_web: "", email_public: "", tel_public: "", secteur: "", description_activite: "", titre: "", url: "", description: "",
      page_recrutement: "", notes: "" });
    const envoi = ref(false);
    const valider = async () => {
      envoi.value = true;
      try {
        const r = await api("/api/manuel", { method: "POST", body: { ...f } });
        toast(`« ${r.nom} » ajouté`, "ok");
        store.modal = null;
        if (r.distance_km != null && store.params && r.distance_km > store.params.rayon_km)
          toast(`Attention : à ${Math.round(r.distance_km)} km, au-delà de ton rayon`, "info", 8000);
        await toutRecharger(); ouvrirFiche(r.id);
      } catch (e) { toast(e.message, "error"); }
      finally { envoi.value = false; }
    };
    return { f, valider, envoi, store };
  },
  template: `
    <div class="modal-overlay" @click="store.modal = null"></div>
    <div class="modal">
      <h2>➕ Ajouter manuellement</h2>
      <div class="toggle-group">
        <button class="toggle" :class="{on: f.type === 'spontanee'}" @click="f.type = 'spontanee'">Candidature spontanée</button>
        <button class="toggle" :class="{on: f.type === 'offre'}" @click="f.type = 'offre'">Offre trouvée ailleurs</button>
        <button class="toggle" :class="{on: f.type === 'dsi_interne'}" @click="f.type = 'dsi_interne'">DSI interne</button>
      </div>
      <div class="form-grid">
        <template v-if="f.type === 'offre'">
          <label class="field full"><span>Intitulé de l'offre *</span><input type="text" v-model="f.titre" placeholder="Stage technicien systèmes et réseaux"></label>
          <label class="field"><span>Contrat</span><select v-model="f.type_contrat"><option value="stage">Stage</option><option value="alternance">Alternance</option><option value="autre">Autre</option></select></label>
          <label class="field"><span>Lien de l'offre</span><input type="url" v-model="f.url" placeholder="https://…"></label>
          <label class="field full"><span>Description de l'offre</span><textarea v-model="f.description" placeholder="Colle ici le texte : les technos seront détectées automatiquement"></textarea></label>
        </template>
        <label class="field full"><span>Entreprise *</span><input type="text" v-model="f.nom"></label>
        <label class="field"><span>SIRET (évite les doublons)</span><input type="text" v-model="f.siret"></label>
        <label class="field"><span>Secteur</span><input type="text" v-model="f.secteur"></label>
        <label class="field full"><span>Adresse</span><input type="text" v-model="f.adresse"></label>
        <label class="field"><span>Code postal</span><input type="text" v-model="f.code_postal"></label>
        <label class="field"><span>Ville</span><input type="text" v-model="f.ville"></label>
        <label class="field"><span>Site web</span><input type="url" v-model="f.site_web"></label>
        <label class="field"><span>Page recrutement</span><input type="url" v-model="f.page_recrutement"></label>
        <label class="field"><span>Email générique</span><input type="email" v-model="f.email_public"></label>
        <label class="field"><span>Téléphone</span><input type="tel" v-model="f.tel_public"></label>
        <label class="field full" v-if="f.type !== 'offre'"><span>Activité</span><textarea v-model="f.description_activite"></textarea></label>
        <label class="field full"><span>Notes</span><textarea v-model="f.notes" rows="2"></textarea></label>
      </div>
      <div class="row"><button class="btn primary" :disabled="!f.nom || envoi" @click="valider">{{ envoi ? 'Ajout…' : 'Ajouter' }}</button>
        <button class="btn ghost" @click="store.modal = null">Annuler</button></div>
    </div>`,
};

// ------------------------------------------------------------------ réglages
const SettingsView = {
  setup() {
    const p = ref(null);
    const nafSisr = ref(""), nafDsi = ref("");
    const motsCles = ref([]), nafPoids = ref([]);
    const nouveau = reactive({ mot: "", points: 4 });
    const doublons = ref(null);
    const sauvegarde = ref(false);
    const charger = async () => {
      await chargerParams();
      p.value = JSON.parse(JSON.stringify(store.params));
      nafSisr.value = p.value.naf_sisr.join(", ");
      nafDsi.value = p.value.naf_dsi_interne.join(", ");
      motsCles.value = Object.entries(p.value.mots_cles).map(([mot, points]) => ({ mot, points }));
      nafPoids.value = Object.entries(p.value.naf_poids).map(([naf, points]) => ({ naf, points }));
      chargerHealth();
    };
    onMounted(charger);
    const liste = s => s.split(/[\s,;]+/).map(x => x.trim().toUpperCase()).filter(Boolean);
    const sauver = async () => {
      sauvegarde.value = true;
      const data = { ...p.value, naf_sisr: liste(nafSisr.value), naf_dsi_interne: liste(nafDsi.value),
        mots_cles: Object.fromEntries(motsCles.value.filter(k => k.mot.trim()).map(k => [k.mot.trim().toLowerCase(), +k.points])),
        naf_poids: Object.fromEntries(nafPoids.value.filter(k => k.naf.trim()).map(k => [k.naf.trim().toUpperCase(), +k.points])) };
      if (data.ville_depart.nom !== store.params.ville_depart.nom) data.ville_depart = { nom: data.ville_depart.nom, code_postal: data.ville_depart.code_postal, lat: null, lon: null };
      try {
        store.params = await api("/api/parametres", { method: "PUT", body: data });
        toast("Réglages enregistrés, scores recalculés", "ok");
        await charger(); toutRecharger();
      } catch (e) { toast(e.message, "error"); }
      finally { sauvegarde.value = false; }
    };
    const reinit = async cles => {
      if (!confirm("Remettre ces réglages à leur valeur par défaut ?")) return;
      try { await api("/api/parametres/reinitialiser", { method: "POST", body: cles }); await charger(); toutRecharger(); toast("Valeurs par défaut restaurées", "ok"); }
      catch (e) { toast(e.message, "error"); }
    };
    const ajouterMot = () => { if (nouveau.mot.trim()) { motsCles.value.unshift({ ...nouveau }); nouveau.mot = ""; } };
    const chercherDoublons = async () => { doublons.value = await api("/api/doublons"); };
    const fusionner = async (garder, fusion) => {
      try { await api("/api/doublons/fusionner", { method: "POST", body: { garder_id: garder.id, fusion_id: fusion.id } });
        toast(`« ${fusion.nom} » fusionné dans « ${garder.nom} »`, "ok"); chercherDoublons(); toutRecharger(); }
      catch (e) { toast(e.message, "error"); }
    };
    return { p, store, nafSisr, nafDsi, motsCles, nafPoids, nouveau, ajouterMot, sauver, sauvegarde, reinit, doublons,
      chercherDoublons, fusionner, lancerRefresh, SOURCES };
  },
  template: `
  <div v-if="!p" class="empty">Chargement…</div>
  <div v-else>
    <div class="row" style="margin-bottom:14px; position:sticky; top:58px; z-index:10">
      <span class="grow"></span>
      <button class="btn primary" @click="sauver" :disabled="sauvegarde">{{ sauvegarde ? 'Enregistrement…' : '💾 Enregistrer les réglages' }}</button>
    </div>
    <div class="settings-grid">
      <div class="card stack">
        <h3>📍 Zone de recherche</h3>
        <div class="form-grid">
          <label class="field"><span>Ville de départ</span><input type="text" v-model="p.ville_depart.nom"></label>
          <label class="field"><span>Code postal</span><input type="text" v-model="p.ville_depart.code_postal"></label>
        </div>
        <label class="field"><span>Rayon de recherche : {{ p.rayon_km }} km</span><input type="range" min="5" max="50" step="5" v-model.number="p.rayon_km"></label>
        <div class="small muted">Tout ce qui est au-delà du rayon est ignoré à l'import (50 km max, limite de l'API Annuaire).</div>
        <label class="row"><input type="checkbox" v-model="p.exclure_sans_salarie"> Ignorer les entreprises sans salarié (auto-entrepreneurs)</label>
        <label class="field"><span>Effectif minimum pour les « DSI internes »</span>
          <select v-model.number="p.dsi_effectif_min"><option :value="50">50 salariés</option><option :value="100">100 salariés</option><option :value="250">250 salariés</option><option :value="500">500 salariés</option></select></label>
      </div>
      <div class="card stack">
        <h3>🎓 Stage et relances</h3>
        <div class="form-grid">
          <label class="field"><span>Début du stage</span><input type="date" v-model="p.stage_debut"></label>
          <label class="field"><span>Fin au plus tard</span><input type="date" v-model="p.stage_fin"></label>
          <label class="field"><span>Durée min (semaines)</span><input type="number" min="1" max="52" v-model.number="p.stage_duree_min_semaines"></label>
          <label class="field"><span>Durée max (semaines)</span><input type="number" min="1" max="52" v-model.number="p.stage_duree_max_semaines"></label>
        </div>
        <label class="field"><span>Relance automatique après {{ p.delai_relance_jours }} jour(s) sans réponse</span>
          <input type="range" min="2" max="30" v-model.number="p.delai_relance_jours"></label>
      </div>
      <div class="card stack">
        <h3>🏷️ Codes NAF</h3>
        <label class="field"><span>Entreprises SISR (candidatures spontanées)</span><textarea v-model="nafSisr" rows="3"></textarea></label>
        <label class="field"><span>Grosses structures avec DSI interne</span><textarea v-model="nafDsi" rows="4"></textarea></label>
        <div class="section-title">Points de score par code NAF</div>
        <div class="kw-list"><table class="kw-table">
          <tr v-for="(k, i) in nafPoids"><td><input type="text" v-model="k.naf"></td><td><input type="number" v-model.number="k.points"></td>
            <td><button class="icon-btn" @click="nafPoids.splice(i, 1)" title="Retirer">✕</button></td></tr>
        </table></div>
        <div class="row"><button class="btn sm" @click="nafPoids.push({naf: '', points: 5})">+ Ajouter</button>
          <button class="btn sm ghost" @click="reinit(['naf_sisr', 'naf_dsi_interne', 'naf_poids'])">Valeurs par défaut</button></div>
      </div>
      <div class="card stack">
        <h3>🔑 Mots-clés du score</h3>
        <div class="small muted">Points ajoutés quand le mot apparaît dans l'offre ou la description (négatif = malus). La pertinence est plafonnée à 40 points.</div>
        <div class="row"><input type="text" v-model="nouveau.mot" placeholder="nouveau mot-clé" style="flex:1" @keyup.enter="ajouterMot">
          <input type="number" v-model.number="nouveau.points" style="width:70px"><button class="btn sm" @click="ajouterMot">Ajouter</button></div>
        <div class="kw-list"><table class="kw-table">
          <tr v-for="(k, i) in motsCles"><td><input type="text" v-model="k.mot"></td><td><input type="number" v-model.number="k.points"></td>
            <td><button class="icon-btn" @click="motsCles.splice(i, 1)" title="Retirer">✕</button></td></tr>
        </table></div>
        <div><button class="btn sm ghost" @click="reinit(['mots_cles'])">Valeurs par défaut</button></div>
      </div>
      <div class="card stack">
        <h3>✉️ Modèle de mail</h3>
        <div class="form-grid">
          <label class="field"><span>Prénom Nom</span><input type="text" v-model="p.profil.prenom_nom"></label>
          <label class="field"><span>Établissement</span><input type="text" v-model="p.profil.ecole" placeholder="lycée …"></label>
          <label class="field"><span>Email</span><input type="email" v-model="p.profil.email"></label>
          <label class="field"><span>Téléphone</span><input type="tel" v-model="p.profil.telephone"></label>
        </div>
        <label class="field"><span>Objet</span><input type="text" v-model="p.modele_mail_objet"></label>
        <label class="field"><span>Message</span><textarea v-model="p.modele_mail" rows="10"></textarea></label>
        <div class="small muted">Variables : {entreprise} {ville} {poste} {poste_phrase} {date_debut} {date_fin} {duree} {prenom_nom} {email} {telephone} {ecole} {ecole_phrase}</div>
        <div><button class="btn sm ghost" @click="reinit(['modele_mail', 'modele_mail_objet'])">Modèle par défaut</button></div>
      </div>
      <div class="card stack">
        <h3>🔌 Sources de données</h3>
        <div v-if="store.health" class="stack small">
          <div v-for="(s, nom) in store.health.sources" class="row">
            <span :style="{color: s.configuree ? 'var(--ok)' : 'var(--warn)'}">●</span><b>{{ SOURCES[nom] || nom }}</b>
            <span class="muted" v-if="s.message">{{ s.message }}</span>
          </div>
        </div>
        <div class="small muted">Les clés France Travail se mettent dans le fichier <code>.env</code> (voir README), puis redémarre l'application.</div>
        <div class="row">
          <button class="btn" @click="lancerRefresh({force: true})" :disabled="store.refresh?.en_cours">🔄 Actualiser sans cache</button>
          <button class="btn" @click="lancerRefresh({sources: ['enrichissement_web']})" :disabled="store.refresh?.en_cours" title="Cherche le site web, la description et les pages contact/recrutement des entreprises les mieux notées">✨ Trouver les sites web</button>
        </div>
      </div>
      <div class="card stack">
        <h3>👯 Doublons potentiels</h3>
        <div class="small muted">Entreprises au nom très proche dans la même ville (sans SIRET différent). La fusion conserve le suivi, les notes et l'historique.</div>
        <div><button class="btn sm" @click="chercherDoublons">Rechercher les doublons</button></div>
        <div v-if="doublons && !doublons.length" class="muted small">Aucun doublon détecté 👍</div>
        <div v-for="d in doublons || []" class="card" style="padding:10px">
          <div class="small"><b>{{ d.a.nom }}</b> ({{ d.a.siret || 'sans SIRET' }}) ↔ <b>{{ d.b.nom }}</b> ({{ d.b.siret || 'sans SIRET' }}) · {{ d.a.ville }} · {{ d.similarite }} %</div>
          <div class="row" style="margin-top:6px"><button class="btn sm" @click="fusionner(d.a, d.b)">Garder la 1re</button><button class="btn sm" @click="fusionner(d.b, d.a)">Garder la 2e</button></div>
        </div>
      </div>
    </div>
  </div>`,
};

// ================================================================== application
const App = {
  components: { DashboardView, TableView, KanbanView, MapView, TrashView, SettingsView, FicheDrawer, EntretienModal, MailModal, ManuelModal },
  setup() {
    const vues = [
      { id: "accueil", label: "Accueil", ico: "🏠" },
      { id: "tableau", label: "Tableau", ico: "📋" },
      { id: "kanban", label: "Kanban", ico: "🗂️" },
      { id: "carte", label: "Carte", ico: "🗺️" },
      { id: "corbeille", label: "Corbeille", ico: "🗑️" },
      { id: "reglages", label: "Réglages", ico: "⚙️" },
    ];
    const titre = computed(() => vues.find(v => v.id === store.view)?.label);
    watch(() => store.view, v => { lsSet("view", v); store.selected = {}; if (v === "accueil") chargerDash(); });
    // Recharge la liste quand les filtres changent (avec un petit délai pour la saisie)
    const recharger = debounce(chargerCibles, 250);
    watch(() => JSON.stringify(store.filters), () => { lsSet("filters", store.filters); recharger(); });
    const appliquerTheme = t => {
      if (t === "auto") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = t;
    };
    const changerTheme = () => {
      store.theme = { auto: "light", light: "dark", dark: "auto" }[store.theme];
      lsSet("theme", store.theme); appliquerTheme(store.theme);
      if (store.view === "accueil") chargerDash();
    };
    appliquerTheme(store.theme);
    onMounted(async () => {
      await Promise.all([chargerParams().catch(() => {}), chargerHealth(), toutRecharger()]);
      const e = await api("/api/refresh/status").catch(() => null);
      if (e?.en_cours) { store.refresh = e; suivreRefresh(); }
    });
    const avertissement = computed(() => {
      const h = store.health;
      if (!h) return "L'API ne répond pas. Le serveur est-il lancé ?";
      return null;
    });
    const deconnexion = async () => { await fetch("/api/logout", { method: "POST" }); location.href = "/login"; };
    return { store, vues, titre, changerTheme, lancerRefresh, avertissement, deconnexion };
  },
  template: `
  <div class="layout">
    <nav class="sidebar">
      <div class="brand">🖧 Stage SISR<small>{{ store.params?.ville_depart?.nom || 'Brest' }} · {{ store.params?.rayon_km || 50 }} km</small></div>
      <button v-for="v in vues" class="nav-btn" :class="{active: store.view === v.id}" @click="store.view = v.id">
        <span class="ico">{{ v.ico }}</span>{{ v.label }}
        <span class="count" v-if="v.id === 'tableau'">{{ store.cibles.length }}</span>
      </button>
      <div class="spacer"></div>
      <button class="nav-btn" v-if="store.health?.auth" @click="deconnexion" title="Se déconnecter de cet appareil">
        <span class="ico">🔒</span>Déconnexion
      </button>
      <button class="nav-btn" @click="changerTheme" :title="'Thème : ' + store.theme">
        <span class="ico">{{ store.theme === 'dark' ? '🌙' : store.theme === 'light' ? '☀️' : '🌓' }}</span>Thème {{ store.theme === 'auto' ? 'auto' : store.theme === 'dark' ? 'sombre' : 'clair' }}
      </button>
    </nav>
    <div class="main">
      <header class="topbar">
        <h1>{{ titre }}</h1>
        <input v-if="['tableau','kanban','carte'].includes(store.view)" class="search" type="search" v-model="store.filters.q" placeholder="🔍 Rechercher (nom, ville, techno, notes…)">
        <span class="grow"></span>
        <button class="btn" @click="store.modal = {type: 'manuel'}">➕ Ajouter</button>
        <button class="btn primary" @click="lancerRefresh()" :disabled="store.refresh?.en_cours">{{ store.refresh?.en_cours ? '⏳ Actualisation…' : '🔄 Actualiser les données' }}</button>
      </header>
      <div class="progress-wrap" v-if="store.refresh">
        <div class="row small" style="margin-bottom:4px">
          <span class="grow">{{ store.refresh.en_cours ? store.refresh.etape : '✅ ' + (store.refresh.resume?.texte || 'Terminé') }}</span>
          <b>{{ Math.round(store.refresh.progression * 100) }} %</b>
          <button v-if="!store.refresh.en_cours" class="icon-btn" @click="store.refresh = null">✕</button>
        </div>
        <div class="progress"><div :style="{width: (store.refresh.progression * 100) + '%'}"></div></div>
      </div>
      <main class="content">
        <div class="alert" v-if="avertissement" style="margin-bottom:12px">{{ avertissement }}</div>
        <DashboardView v-if="store.view === 'accueil'" />
        <TableView v-else-if="store.view === 'tableau'" />
        <KanbanView v-else-if="store.view === 'kanban'" />
        <MapView v-else-if="store.view === 'carte'" />
        <TrashView v-else-if="store.view === 'corbeille'" />
        <SettingsView v-else-if="store.view === 'reglages'" />
      </main>
    </div>
    <FicheDrawer />
    <EntretienModal v-if="store.modal?.type === 'entretien'" />
    <MailModal v-if="store.modal?.type === 'mail'" />
    <ManuelModal v-if="store.modal?.type === 'manuel'" />
    <div class="toasts"><div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.msg }}</div></div>
  </div>`,
};

createApp(App).mount("#app");
