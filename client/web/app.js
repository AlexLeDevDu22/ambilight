"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let cfg = null;
let presets = {};
let live = null;
let pending = {};
let pendingTimer = null;

const MAX_LEDS = 113;
// Les LEDs du contour sont sur les côtés et l'arrière (rien à l'avant).
const RING_PATH =
  "M16 60C14.6 70 14 80 14 90C14 150 29 192 60 192C91 192 106 150 106 90C106 80 105.4 70 104 60";
const QUICK = [
  "#ff2d55",
  "#ff6b00",
  "#ffc300",
  "#00e676",
  "#00d4ff",
  "#2f6bff",
  "#8b5cff",
  "#ff4fd8",
  "#ffffff",
];

const FORMAT = {
  brightness: (v) => `${Math.round(v * 100)} %`,
  sensitivity: (v) => `×${(+v).toFixed(1)}`,
  speed: (v) => `${Math.round(v * 100)} %`,
  smoothing: (v) => `${Math.round(v * 100)} %`,
  gamma: (v) => (+v).toFixed(1),
  saturation: (v) => `×${(+v).toFixed(1)}`,
};

/* ------------------------------------------------------------------ */
/* Utilitaires chemin "a.b.0"                                          */
/* ------------------------------------------------------------------ */
function getIn(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}
function setIn(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  keys.slice(0, -1).forEach((k) => {
    o = o[k];
  });
  o[keys.at(-1)] = value;
}
function patchFor(path, value) {
  // Les tableaux (leds.colors) sont envoyés entiers.
  const keys = path.split(".");
  const idx = keys.findIndex((k) => /^\d+$/.test(k));
  if (idx !== -1) {
    const arrPath = keys.slice(0, idx).join(".");
    return patchFor(arrPath, [...getIn(cfg, arrPath)]);
  }
  const root = {};
  let o = root;
  keys.slice(0, -1).forEach((k) => {
    o = o[k] = {};
  });
  o[keys.at(-1)] = value;
  return root;
}
function merge(a, b) {
  for (const [k, v] of Object.entries(b)) {
    if (
      v &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      a[k] &&
      typeof a[k] === "object"
    )
      merge(a[k], v);
    else a[k] = v;
  }
  return a;
}

/* ------------------------------------------------------------------ */
/* Réglages : modification locale immédiate + envoi groupé             */
/* ------------------------------------------------------------------ */
let lastLocalChange = 0;
let cfgVersion = null;
let cfgFetching = false;

// Réglages modifiés ailleurs (télécommande, barre de menus, autre onglet) :
// on les recharge, sauf si l'utilisateur est en train de modifier ici.
async function syncConfig(version) {
  if (cfgVersion === null) { cfgVersion = version; return; }
  if (version === cfgVersion || cfgFetching) return;
  if (Date.now() - lastLocalChange < 700 || Object.keys(pending).length) return;
  cfgFetching = true;
  try {
    const r = await fetch("/api/state");
    const s = await r.json();
    cfg = s.config;
    cfgVersion = version;
    buildLeds();
    refresh();
  } catch { /* on réessaiera au prochain message */ }
  cfgFetching = false;
}

function change(path, value) {
  lastLocalChange = Date.now();
  setIn(cfg, path, value);
  merge(pending, patchFor(path, value));
  refresh();
  clearTimeout(pendingTimer);
  pendingTimer = setTimeout(flush, 90);
}

async function flush() {
  const body = pending;
  pending = {};
  if (!Object.keys(body).length) return;
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.config && !Object.keys(pending).length) {
      cfg = data.config;
      refresh();
    }
    flashSaved();
  } catch {
    merge(pending, body); // on réessaiera au prochain changement
  }
}

let savedTimer;
function flashSaved() {
  const el = $("#saved");
  el.classList.add("show");
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => el.classList.remove("show"), 1100);
}

/* ------------------------------------------------------------------ */
/* Construction de l'interface                                         */
/* ------------------------------------------------------------------ */
function buildPalettes() {
  $$(".palettes").forEach((box) => {
    box.innerHTML = "";
    const path = box.dataset.path;
    const mk = (name, label, colors) => {
      const b = document.createElement("button");
      b.className = "pal";
      b.dataset.value = name;
      b.innerHTML = `<span class="bar"></span><span class="name">${name === "cover" ? '<img alt="">' : ""}${label}</span>`;
      b.querySelector(".bar").style.background =
        `linear-gradient(90deg, ${colors.join(",")})`;
      b.addEventListener("click", () => change(path, name));
      box.appendChild(b);
    };
    mk("cover", "Cover", presets.sunset.colors);
    Object.entries(presets).forEach(([k, p]) => mk(k, p.label, p.colors));
  });
}

function buildQuick() {
  $$(".quick").forEach((box) => {
    QUICK.forEach((c) => {
      const b = document.createElement("button");
      b.style.background = c;
      b.title = "Couleur unie";
      b.addEventListener("click", () => {
        cfg.leds.colors = [c, c];
        change("leds.colors.0", c);
      });
      box.appendChild(b);
    });
  });
}

function bindControls() {
  $$(".seg[data-path], .chips[data-path]").forEach((box) => {
    $$("button", box).forEach((b) =>
      b.addEventListener("click", () =>
        change(box.dataset.path, b.dataset.value),
      ),
    );
  });
  $$("input[type=range][data-path]").forEach((inp) => {
    inp.addEventListener("input", () =>
      change(inp.dataset.path, parseFloat(inp.value)),
    );
  });
  $$("input[type=color][data-path]").forEach((inp) => {
    inp.addEventListener("input", () => change(inp.dataset.path, inp.value));
  });
  $$("input[type=checkbox][data-path]").forEach((inp) => {
    inp.addEventListener("change", () => change(inp.dataset.path, inp.checked));
  });
  $$("select[data-path], input[type=number][data-path]").forEach((inp) => {
    inp.addEventListener("change", () => {
      let v = inp.value;
      if (inp.hasAttribute("data-number")) {
        v = parseInt(v, 10);
        if (Number.isNaN(v)) return refresh();
      }
      if (inp.dataset.path.startsWith("hardware.led_sides.")) {
        const sides = {
          ...cfg.hardware.led_sides,
          [inp.dataset.path.split(".").pop()]: v,
        };
        const total = Object.values(sides).reduce((a, b) => a + b, 0);
        if (total < 1 || total > MAX_LEDS) {
          inp.value = getIn(cfg, inp.dataset.path);
          return updateSidesTotal(total);
        }
      }
      change(inp.dataset.path, v);
      if (inp.dataset.path.startsWith("hardware.led_sides.")) buildLeds();
    });
  });
  $$(".power").forEach((btn) =>
    btn.addEventListener("click", () => power(btn)),
  );
}

function condOk(expr) {
  return expr.split("&").every((c) => {
    const [path, vals] = c.split("=");
    return vals.split("|").includes(String(getIn(cfg, path)));
  });
}

/* Reflète cfg dans l'interface (sans toucher au contrôle en cours d'édition). */
function refresh() {
  if (!cfg) return;
  const active = document.activeElement;
  $$("[data-show], [data-hide]").forEach((el) => {
    let show = el.dataset.show ? condOk(el.dataset.show) : true;
    if (show && el.dataset.hide && condOk(el.dataset.hide)) show = false;
    el.hidden = !show;
  });
  $$(".seg[data-path], .chips[data-path], .palettes[data-path]").forEach(
    (box) => {
      const v = String(getIn(cfg, box.dataset.path));
      $$("button", box).forEach((b) =>
        b.classList.toggle("active", b.dataset.value === v),
      );
    },
  );
  $$("input[data-path], select[data-path]").forEach((inp) => {
    const v = getIn(cfg, inp.dataset.path);
    if (inp.type === "checkbox") inp.checked = !!v;
    else if (inp !== active || inp.type === "range" || inp.type === "color") {
      if (String(inp.value) !== String(v)) inp.value = v;
    }
    if (inp.type === "range") {
      const min = +inp.min,
        max = +inp.max;
      inp.style.setProperty("--fill", `${((v - min) / (max - min)) * 100}%`);
      const out = inp.parentElement.querySelector("output");
      const key = inp.dataset.path.split(".").pop();
      if (out) out.textContent = (FORMAT[key] || ((x) => x))(v);
    }
  });
  updateSidesTotal();
}

function updateSidesTotal(total) {
  const t =
    total ?? Object.values(cfg.hardware.led_sides).reduce((a, b) => a + b, 0);
  const el = $("#sidesTotal");
  el.textContent = `${t} / ${MAX_LEDS}`;
  el.classList.toggle("bad", t < 1 || t > MAX_LEDS);
}

function fillSelects(ports, screens) {
  const ps = $("#portSelect");
  const current = cfg.hardware.serial_port;
  const opts = [
    ["auto", "Automatique"],
    ...ports.map((p) => [p, p.replace("/dev/cu.", "")]),
  ];
  if (current !== "auto" && !ports.includes(current))
    opts.push([current, `${current.replace("/dev/cu.", "")} (absent)`]);
  ps.innerHTML = opts
    .map(([v, l]) => `<option value="${v}">${l}</option>`)
    .join("");
  const ss = $("#screenSelect");
  ss.innerHTML = Array.from(
    { length: Math.max(1, screens) },
    (_, i) =>
      `<option value="${i}">${i === 0 ? "Principal" : "Écran " + (i + 1)}</option>`,
  ).join("");
}

/* ------------------------------------------------------------------ */
/* Aperçu ruban                                                        */
/* ------------------------------------------------------------------ */
let ledPts = [];
function ledLayout(s) {
  const pts = [];
  const seg = (n, x0, y0, x1, y1) => {
    for (let i = 0; i < n; i++) {
      const t = (i + 0.5) / n;
      pts.push([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t]);
    }
  };
  seg(s.bottom_left_count, 0, 1, 1, 1);
  seg(s.right_count, 1, 1, 1, 0);
  seg(s.top_count, 1, 0, 0, 0);
  seg(s.left_count, 0, 0, 0, 1);
  seg(s.bottom_right_count, 1, 1, 0, 1);
  return pts;
}
const canvas = document.getElementById("ledCanvas");
const ctx = canvas.getContext("2d");
function buildLeds() {
  ledPts = ledLayout(cfg.hardware.led_sides);
  sizeCanvas();
}
function sizeCanvas() {
  const r = canvas.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(r.width * dpr));
  canvas.height = Math.max(1, Math.round(r.height * dpr));
  lastPreview = "";
  if (live) paintLeds(live.leds.preview);
}
new ResizeObserver(() => sizeCanvas()).observe(canvas);

let lastPreview = "";
function paintLeds(hex) {
  if (hex === lastPreview) return;
  lastPreview = hex;
  const W = canvas.width,
    H = canvas.height;
  const k = W / 400;
  ctx.clearRect(0, 0, W, H);
  const n = ledPts.length;
  const m = Math.min(n, hex.length / 6);
  const pos = ledPts.map(([x, y]) => [
    (0.03 + x * 0.94) * W,
    (0.035 + y * 0.93) * H,
  ]);
  // Halo additif (dégradés radiaux, aucun filtre de flou)
  ctx.globalCompositeOperation = "lighter";
  let sr = 0,
    sg = 0,
    sb = 0;
  for (let i = 0; i < m; i++) {
    const r = parseInt(hex.substr(i * 6, 2), 16),
      g = parseInt(hex.substr(i * 6 + 2, 2), 16),
      b = parseInt(hex.substr(i * 6 + 4, 2), 16);
    sr += r;
    sg += g;
    sb += b;
    if (r + g + b < 12) continue;
    const [x, y] = pos[i];
    const grad = ctx.createRadialGradient(x, y, 0, x, y, 13 * k);
    grad.addColorStop(0, `rgba(${r},${g},${b},0.45)`);
    grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.fillStyle = grad;
    ctx.fillRect(x - 13 * k, y - 13 * k, 26 * k, 26 * k);
  }
  ctx.globalCompositeOperation = "source-over";
  for (let i = 0; i < n; i++) {
    const [x, y] = pos[i];
    ctx.fillStyle = i < m ? "#" + hex.substr(i * 6, 6) : "#222";
    ctx.beginPath();
    ctx.arc(x, y, 3.2 * k, 0, 6.2832);
    ctx.fill();
  }
  const d = Math.max(1, m) * 4;
  const inner = `radial-gradient(ellipse at center, #101018 45%, rgb(${(sr / d) | 0},${(sg / d) | 0},${(sb / d) | 0}) 140%)`;
  setStyle($("#ledScreenInner"), "background", inner);
}

/* ------------------------------------------------------------------ */
/* Aperçu souris                                                       */
/* ------------------------------------------------------------------ */
function setupMouseMask() {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 200'><path d='${RING_PATH}' fill='none' stroke='white' stroke-width='7' stroke-linecap='round'/></svg>`;
  const url = `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  $$(".ring").forEach((r) => {
    r.style.webkitMaskImage = url;
    r.style.maskImage = url;
    r.style.webkitMaskSize = "100% 100%";
    r.style.maskSize = "100% 100%";
  });
}
let lastRingKey = "";
function paintMouse(p) {
  const ring = p.ring;
  const key = ring.type === "flow" ? JSON.stringify(ring) : ring.color;
  if (key !== lastRingKey) {
    lastRingKey = key;
    const f = $(".ring-fill");
    let halo;
    if (ring.type === "flow") {
      const cols = [...ring.colors, ring.colors[0]];
      f.style.background = `conic-gradient(from 0deg, ${cols.join(",")})`;
      f.style.animationDuration = `${(0.9 + ring.speed * 0.45).toFixed(2)}s`;
      f.classList.add("spin");
      f.classList.toggle("ccw", !ring.cw);
      halo = ring.colors[3];
    } else {
      f.style.background = ring.color;
      f.classList.remove("spin");
      halo = ring.color;
    }
    $("#mHalo").style.background =
      `radial-gradient(ellipse at 50% 62%, ${halo}, transparent 62%)`;
  }
  setAttr($("#mWheel"), "fill", p.wheel);
  setAttr($("#mLogo"), "fill", p.logo);
  setAttr($("#gWheel stop"), "stop-color", p.wheel);
  setAttr($("#gLogo stop"), "stop-color", p.logo);
}

/* Écritures DOM seulement si la valeur change (évite les recalculs de style). */
const _memo = new WeakMap();
function _changed(el, key, v) {
  let m = _memo.get(el);
  if (!m) _memo.set(el, (m = {}));
  if (m[key] === v) return false;
  m[key] = v;
  return true;
}
function setText(el, v) {
  if (_changed(el, "text", v)) el.textContent = v;
}
function setAttr(el, k, v) {
  if (_changed(el, "a:" + k, v)) el.setAttribute(k, v);
}
function setStyle(el, k, v) {
  if (_changed(el, "s:" + k, v)) el.style[k] = v;
}
function setClass(el, v) {
  if (_changed(el, "class", v)) el.className = v;
}
function setHidden(el, v) {
  if (_changed(el, "hidden", v)) el.hidden = v;
}

/* ------------------------------------------------------------------ */
/* Live                                                                */
/* ------------------------------------------------------------------ */
let lastAccent = "";
/* ------------------------------------------------------------------ */
/* Musique en cours : bandeau, animations de changement de morceau      */
/* ------------------------------------------------------------------ */
const np = { track: null, cover: null };
const eqBars = () => $$("#npEq i");

function swapText(el, text, instant) {
  if (instant) { el.textContent = text; return; }
  el.classList.remove("text-in");
  el.classList.add("text-out");
  setTimeout(() => {
    el.textContent = text;
    el.classList.remove("text-out");
    void el.offsetWidth;  // relance l'animation
    el.classList.add("text-in");
  }, 220);
}

let coverFront = 0, bgFront = 0, coverTimer = null;
function swapCover(url) {
  const img = new Image();
  img.onload = () => {
    if (url !== np.cover) return;  // un autre morceau est déjà arrivé
    clearTimeout(coverTimer);      // une animation en cours est remplacée proprement
    const arts = [$("#npArtA"), $("#npArtB")];
    const front = arts[coverFront], back = arts[1 - coverFront];
    back.src = url;
    back.className = "art-in";
    front.className = front.getAttribute("src") ? "art-out" : "";
    coverFront = 1 - coverFront;
    coverTimer = setTimeout(() => { back.className = "front"; front.className = ""; }, 780);
    // Fond flouté : fondu enchaîné
    const bgs = [$("#npBgA"), $("#npBgB")];
    const bgBack = bgs[1 - bgFront];
    bgBack.style.backgroundImage = `url("${url}")`;
    bgBack.classList.add("show");
    bgs[bgFront].classList.remove("show");
    bgFront = 1 - bgFront;
  };
  img.src = url;
}

function updateNowPlaying(sp, levels) {
  const hero = $("#npHero");
  hero.classList.toggle("off", !sp.playing);
  if (!sp.playing) return;

  const key = `${sp.track}|${sp.artist}`;
  const first = np.track === null;
  if (key !== np.track) {
    np.track = key;
    swapText($("#npTrack"), sp.track, first);
    swapText($("#npArtist"), sp.artist || "", first);
    if (!first) {
      const shine = $(".np-shine");
      shine.classList.remove("go");
      void shine.offsetWidth;
      shine.classList.add("go");
    }
  }
  if (sp.cover && sp.cover !== np.cover) {
    np.cover = sp.cover;
    swapCover(sp.cover);
  }
  const cols = sp.colors || [];
  if (_changed($("#npDots"), "cols", cols.join())) {
    $("#npDots").innerHTML = cols.map(c => `<i style="background:${c};color:${c}"></i>`).join("");
  }

  // Égaliseur : vrai son si un mode Son tourne, sinon animation douce
  const eq = $("#npEq");
  if (levels && levels.length) {
    eq.classList.remove("idle");
    eqBars().forEach((bar, i) => setStyle(bar, "transform", `scaleY(${(0.1 + 0.9 * (levels[i] || 0)).toFixed(2)})`));
  } else {
    eq.classList.add("idle");
  }
}

let webVersion = null;
let lastRemoteId = null;
let toastTimer;
function showToast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove("show"); setTimeout(() => { t.hidden = true; }, 250); }, 1600);
}
function applyLive(l) {
  live = l;
  // Interface modifiée sur le disque → rechargement automatique
  if (l.web) {
    if (webVersion && l.web !== webVersion) { location.reload(); return; }
    webVersion = l.web;
  }
  // Ruban
  const ledsState = l.leds.running
    ? l.serial.connected
      ? "on"
      : "warn"
    : l.serial.connected
      ? ""
      : "warn";
  $("#ledsPower").classList.toggle("on", l.leds.running);
  setClass($("#ledsDot"), "sdot " + ledsState);
  const asleep = l.sleep && l.sleep.on ? `en veille (${l.sleep.reason})` : "";
  setText(
    $("#ledsStatus"),
    l.leds.running
      ? l.leds.status
      : asleep ||
          (l.serial.connected ? "arrêté · Arduino prêt" : l.serial.status),
  );
  setText(
    $("#ledsFps"),
    l.leds.running && l.leds.fps ? `${Math.round(l.leds.fps)} i/s` : "",
  );
  setText($("#serialStatus"), l.serial.status);
  paintLeds(l.leds.preview);

  // Souris
  const mouseOk = !/erreur|non détectée|déconnectée|refusé|manquant/i.test(
    l.mouse.status,
  );
  $("#mousePower").classList.toggle("on", l.mouse.running);
  setClass(
    $("#mouseDot"),
    "sdot " + (l.mouse.running ? (mouseOk ? "on" : "warn") : ""),
  );
  setText(
    $("#mouseStatus"),
    l.mouse.running ? l.mouse.status : asleep || `arrêtée · ${l.mouse.status}`,
  );
  paintMouse(l.mouse.preview);
  const needPerm = /autorise/i.test(l.mouse.responsive);
  setText(
    $("#respHint"),
    needPerm
      ? l.mouse.responsive
      : "Clic gauche ↺ · clic droit ↻ · molette · clic milieu",
  );
  $("#respHint").classList.toggle("warn", needPerm);

  // Musique qui joue mais rien de capté → message dans les cartes en mode Son
  const hint = l.audio_hint || "";
  setText($("#ledsHint"), hint);
  setHidden(
    $("#ledsHint"),
    !(hint && l.leds.running && cfg.leds.mode === "sound"),
  );
  setText($("#mouseHint"), hint);
  setHidden(
    $("#mouseHint"),
    !(hint && l.mouse.running && cfg.mouse.mode === "sound"),
  );

  if (l.cfg !== undefined) syncConfig(l.cfg);

  // Télécommande : petite notification
  if (l.remote && l.remote.id !== lastRemoteId) {
    if (lastRemoteId !== null && l.remote.text) showToast(l.remote.text);
    lastRemoteId = l.remote.id;
  }

  // Spotify
  const sp = l.spotify;
  updateNowPlaying(sp, l.levels);
  const coverKey = `${sp.cover}|${(sp.colors || []).join()}`;
  $$('.pal[data-value="cover"]').forEach((b) => {
    if (!_changed(b, "cover", coverKey)) return;
    const cols = sp.colors || presets.sunset.colors;
    b.querySelector(".bar").style.background =
      `linear-gradient(90deg, ${cols.join(",")})`;
    const img = b.querySelector("img");
    if (sp.cover) {
      img.src = sp.cover;
      img.hidden = false;
    } else img.hidden = true;
    b.title = sp.playing
      ? `Couleurs de « ${sp.track} »`
      : "Couleurs de la pochette Spotify (Sunset quand rien ne joue)";
  });

  // Teinte de l'interface = palette active
  const pal =
    l.leds.running || !l.mouse.running ? l.leds.palette : l.mouse.palette;
  const a1 = pal[0],
    a2 = pal[Math.min(2, pal.length - 1)];
  if (_changed(document.documentElement, "accent", a1 + a2)) {
    document.documentElement.style.setProperty("--accent", a1);
    document.documentElement.style.setProperty("--accent2", a2);
  }
}

async function power(btn) {
  btn.classList.add("busy");
  try {
    const r = await fetch(`/api/${btn.dataset.target}/toggle`, {
      method: "POST",
    });
    const data = await r.json();
    if (data.live) applyLive(data.live);
  } finally {
    btn.classList.remove("busy");
  }
}

let es = null;
let pendingLive = null;
let rafId = 0;
function scheduleLive(l) {
  pendingLive = l;
  if (!rafId)
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      if (pendingLive) applyLive(pendingLive);
      pendingLive = null;
    });
}
function connectEvents() {
  if (es) return;
  es = new EventSource("/api/events");
  let wasDown = false;
  es.onmessage = (e) => {
    if (wasDown) {
      wasDown = false;
      loadState();
    }
    setHidden($("#offline"), true);
    scheduleLive(JSON.parse(e.data));
  };
  es.onerror = () => {
    wasDown = true;
    setHidden($("#offline"), false);
  };
}
function disconnectEvents() {
  if (es) {
    es.close();
    es = null;
  }
}
// Onglet caché → plus aucun flux ni rendu
document.addEventListener("visibilitychange", () => {
  if (document.hidden) disconnectEvents();
  else {
    connectEvents();
    loadState().catch(() => {});
  }
});

async function loadState() {
  const r = await fetch("/api/state");
  const s = await r.json();
  cfg = s.config;
  presets = s.presets;
  if (!$(".pal")) {
    buildPalettes();
    buildQuick();
  }
  fillSelects(s.ports, s.screens);
  buildLeds();
  refresh();
  applyLive(s.live);
}

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea")) return;
  if (e.key === "l") power($("#ledsPower"));
  if (e.key === "m") power($("#mousePower"));
});

(async function init() {
  setupMouseMask();
  bindControls();
  try {
    await loadState();
  } catch {
    $("#offline").hidden = false;
  }
  connectEvents();
})();
