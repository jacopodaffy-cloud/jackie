/* ============================================================
   J.A.R.V.I.S — front-end logic
   Works standalone in a browser (lite mode) and unlocks full
   computer control when the local Python backend is running.
   ============================================================ */

const PROVIDERS = {
  claudecode: {
    label: "Claude Code — your Claude subscription (no API key)",
    url: "", keyUrl: "https://claude.com/claude-code",
    models: ["default"],
    browser: false, kind: "claude-cli", nokey: true,
  },
  openrouter: {
    label: "OpenRouter — FREE (Qwen3 + GLM + DeepSeek + Llama)",
    url: "https://openrouter.ai/api/v1/chat/completions",
    keyUrl: "https://openrouter.ai/keys",
    models: ["qwen/qwen3-235b-a22b:free", "z-ai/glm-4.5-air:free",
             "deepseek/deepseek-chat-v3.1:free", "meta-llama/llama-3.3-70b-instruct:free"],
    browser: true,
  },
  gemini: {
    label: "Google Gemini — FREE (gemini flash)",
    url: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    keyUrl: "https://aistudio.google.com/apikey",
    models: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    browser: true,
  },
  groq: {
    label: "Groq — FREE (Llama, ultra-fast)",
    url: "https://api.groq.com/openai/v1/chat/completions",
    keyUrl: "https://console.groq.com/keys",
    models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    browser: true,
  },
  claude: {
    label: "Claude — Anthropic (Opus 4.8, the strongest brain)",
    url: "https://api.anthropic.com/v1/messages",
    keyUrl: "https://console.anthropic.com/settings/keys",
    models: ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    browser: true, kind: "anthropic",
  },
  zai: {
    label: "Z.ai — GLM (glm-4.6 / glm-4.5)",
    url: "https://api.z.ai/api/paas/v4/chat/completions",
    keyUrl: "https://z.ai/manage-apikey/apikey-list",
    models: ["glm-4.6", "glm-4.5", "glm-4.5-air"], browser: false,
  },
  deepseek: {
    label: "DeepSeek — deepseek-chat",
    url: "https://api.deepseek.com/chat/completions",
    keyUrl: "https://platform.deepseek.com/api_keys",
    models: ["deepseek-chat", "deepseek-reasoner"], browser: false,
  },
  qwen: {
    label: "Qwen — Alibaba Model Studio",
    url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    keyUrl: "https://bailian.console.alibabacloud.com/",
    models: ["qwen-plus", "qwen-max", "qwen3-235b-a22b"], browser: false,
  },
};

const WX = { 0:["Clear","☀"],1:["Mainly clear","🌤"],2:["Partly cloudy","⛅"],3:["Overcast","☁"],
  45:["Fog","🌫"],48:["Fog","🌫"],51:["Drizzle","🌦"],61:["Rain","🌧"],63:["Rain","🌧"],
  65:["Heavy rain","🌧"],71:["Snow","🌨"],80:["Showers","🌦"],95:["Thunderstorm","⛈"] };

const $ = (s) => document.querySelector(s);
const state = {
  backend: false, provider: "openrouter", started: Date.now(),
  session: 1, commands: 0, speak: true, wake: false, busy: false,
  messages: [], camStream: null, recog: null, clapCtx: null,
  greeted: false, tasks: [], notes: [], bootBase: null, battWarned: false,
};

/* ---------------- storage ---------------- */
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem("jacopus_" + k)) ?? d; } catch { return d; } },
  set: (k, v) => localStorage.setItem("jacopus_" + k, JSON.stringify(v)),
};
function currentKey() { return store.get("key_" + state.provider, "") || ""; }

/* ---------------- boot + clock ---------------- */
window.addEventListener("load", () => setTimeout(() => $("#boot").classList.add("hide"), 900));
function tickClock() {
  const d = new Date();
  $("#clockTime").textContent = d.toLocaleTimeString("en-US", { hour12: true });
  $("#clockDate").textContent = d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}
setInterval(tickClock, 1000); tickClock();

/* ---------------- uptime ---------------- */
function pad(n){return String(n).padStart(2,"0");}
function fmtDur(sec){const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=Math.floor(sec%60);return `${pad(h)}:${pad(m)}:${pad(s)}`;}
setInterval(() => {
  // real machine uptime when the backend reports it; session time otherwise
  const up = state.bootBase != null
    ? Date.now() / 1000 - state.bootBase
    : (Date.now() - state.started) / 1000;
  $("#uptimeMini").textContent = fmtDur(up);
  $("#uptimeBig").textContent = fmtDur(up);
  $("#sessionCount").textContent = state.session;
  $("#cmdCount").textContent = state.commands;
}, 1000);

/* ---------------- backend detection + status ---------------- */
async function detectBackend() {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    if (!r.ok) throw 0;
    const j = await r.json();
    state.backend = true;
    if (j.provider) state.provider = j.provider;
    setStatus(true, j.has_key);
    $("#backendNote").textContent = "✅ Backend connected — full computer control is available.";
    return j;
  } catch {
    state.backend = false;
    setStatus(false, !!currentKey());
    $("#backendNote").textContent = "Backend offline — chat + camera + mic still work. Run Jackie.bat for full PC control.";
    return null;
  }
}
function setStatus(online, hasKey) {
  const pill = $("#statusPill"), txt = $("#statusText");
  if (online && hasKey) { pill.className = "pill online"; txt.textContent = "Online"; }
  else if (hasKey) { pill.className = "pill online"; txt.textContent = "Ready"; }
  else { pill.className = "pill offline"; txt.textContent = "Offline"; }
  // don't stomp the wake text while actively listening/thinking
  if (!state.busy && voice.mode !== "command" && voice.mode !== "wake") idleReactor();
}
function setWake(t){ $("#wakeText").textContent = t; }

/* ---------------- system stats ---------------- */
async function refreshStats() {
  if (state.backend) {
    try {
      // listening=1 tells the background clap launcher OUR mic is in charge;
      // s.clap means the launcher heard a double clap for us — wake up.
      const url = "/api/stats?listening=" + (state.wake ? 1 : 0);
      const s = await (await fetch(url, { cache: "no-store" })).json();
      applyStats(s.cpu, s.ram_pct, s.ram_used_gb, s.disk_used_gb, s.disk_total_gb, s.load);
      applyExtraStats(s);
      if (s.boot_uptime != null) state.bootBase = Date.now() / 1000 - s.boot_uptime;
      if (s.clap) clapSignal();
      return;
    } catch {}
  }
  // lite mode: plausible simulated values that drift smoothly
  const base = (Math.sin(Date.now() / 9000) + 1) * 12 + 5;
  const cpu = Math.max(2, Math.min(95, base + Math.random() * 8));
  const memGB = navigator.deviceMemory || 8;
  const ramPct = 40 + Math.sin(Date.now() / 12000) * 8 + Math.random() * 4;
  applyStats(cpu, ramPct, (memGB * ramPct / 100), null, memGB, cpu * 0.9 + ramPct * 0.3);
  applyExtraStats(null);
  liteBattery();
}
function applyExtraStats(s) {
  $("#gpuCard").textContent = s && s.gpu ? Math.round(s.gpu.util) + "%" : "—";
  $("#battCard").textContent = s && s.battery
    ? s.battery.pct + "%" + (s.battery.plugged ? "⚡" : "") : $("#battCard").textContent;
  if (!s) return;
  $("#netCard").textContent = s.net_down_kbs != null
    ? "↓" + fmtRate(s.net_down_kbs) : "—";
}
function fmtRate(kbs) {
  return kbs >= 1024 ? (kbs / 1024).toFixed(1) + " MB/s" : Math.round(kbs) + " KB/s";
}
// Lite mode gets battery from the browser Battery API (where supported).
async function liteBattery() {
  if (!navigator.getBattery) return;
  try {
    const b = await navigator.getBattery();
    $("#battCard").textContent = Math.round(b.level * 100) + "%" + (b.charging ? "⚡" : "");
    if (!b.charging && b.level <= 0.2 && !state.battWarned) {
      state.battWarned = true;
      pushNote(`Battery at ${Math.round(b.level * 100)}% — connect the charger.`, "alert");
    }
  } catch {}
}
function applyStats(cpu, ramPct, ramGB, diskUsed, diskTotal, load) {
  cpu = Math.round(cpu); ramPct = Math.round(ramPct);
  $("#cpuPct").textContent = cpu + "%"; $("#cpuBar").style.width = cpu + "%";
  $("#cpuCard").textContent = cpu + "%";
  $("#ramTop").textContent = ramGB != null ? ramGB.toFixed(0) + " GB" : ramPct + "%";
  $("#ramBar").style.width = ramPct + "%"; $("#memCard").textContent = ramPct + "%";
  $("#diskCard").textContent = (diskUsed != null && diskTotal != null)
    ? `${Math.round(diskUsed)}/${Math.round(diskTotal)} GB` : (diskTotal ? diskTotal + " GB" : "— GB");
  const l = Math.round(Math.max(0, Math.min(100, load ?? cpu)));
  $("#loadPct").textContent = l + "%"; $("#loadBar").style.width = l + "%";
  $("#loadWord").textContent = l < 30 ? "Idle" : l < 65 ? "Moderate" : "High";
}
setInterval(refreshStats, 3000);

/* ---------------- weather ---------------- */
async function refreshWeather() {
  try {
    let lat = store.get("lat"), lon = store.get("lon"), city = store.get("city");
    if (lat == null) {
      const g = await (await fetch("https://ipapi.co/json/")).json();
      lat = g.latitude; lon = g.longitude; city = g.city + ", " + g.country_code;
      store.set("lat", lat); store.set("lon", lon); store.set("city", city);
    }
    const u = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code`;
    const w = (await (await fetch(u)).json()).current;
    const [desc, emoji] = WX[w.weather_code] || ["—", "☁"];
    $("#wxTemp").textContent = Math.round(w.temperature_2m) + "°C";
    $("#weatherChipTemp").textContent = Math.round(w.temperature_2m) + "°C";
    $("#wxCity").textContent = city; $("#weatherChipCity").textContent = (city || "").split(",")[0];
    $("#wxDesc").textContent = desc;
    $("#wxHum").textContent = w.relative_humidity_2m + "%";
    $("#wxWind").textContent = w.wind_speed_10m + " m/s";
    $("#wxFeels").textContent = Math.round(w.apparent_temperature) + "°C";
    $("#wxIcon").innerHTML = `<div style="font-size:52px;line-height:1">${emoji}</div>`;
  } catch {
    $("#wxCity").textContent = "Weather unavailable";
  }
}

/* ---------------- camera ---------------- */
async function toggleCamera() {
  const stage = $("#camStage");
  if (state.camStream) {
    if (hand.active) stopHandTracking();
    state.camStream.getTracks().forEach((t) => t.stop());
    state.camStream = null; stage.classList.remove("on");
    $("#btnCamera").classList.remove("active"); return;
  }
  try {
    state.camStream = await navigator.mediaDevices.getUserMedia({ video: true });
    $("#camVideo").srcObject = state.camStream; stage.classList.add("on");
    $("#btnCamera").classList.add("active");
    if (!hand.active) toggleHandTracking();  // camera on = gesture control on
  } catch (e) { toast("Camera access denied."); }
}
function snapshot() {
  if (!state.camStream) return toast("Turn the camera on first.");
  const v = $("#camVideo"), c = $("#snapCanvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  const a = document.createElement("a");
  a.download = "jackie-snapshot.png"; a.href = c.toDataURL("image/png"); a.click();
}

/* ============================================================
   HAND-GESTURE CONTROL — Iron-Man style
   Camera on -> JARVIS tracks your hand (MediaPipe, in-browser):
   a holographic cursor follows your index finger, pinching your
   thumb + index clicks, pinch-and-move scrolls.
   ============================================================ */
const hand = {
  active: false, hands: null, timer: 0, pinched: false,
  startY: 0, scrollEl: null, moved: false,
  sx: 0, sy: 0, haveCursor: false,      // smoothed cursor position
  pinchAt: 0, lastClick: 0, lastSeen: 0, // gesture timing (debounce/hold)
};
const MP_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/hands/";

function loadMediaPipe() {
  if (window.Hands) return Promise.resolve(true);
  return new Promise((res) => {
    const s = document.createElement("script");
    s.src = MP_URL + "hands.js";
    s.onload = () => res(true);
    s.onerror = () => res(false);
    document.head.appendChild(s);
  });
}

async function toggleHandTracking() {
  if (hand.active) { stopHandTracking(); return; }
  if (!state.camStream) await toggleCamera();
  if (!state.camStream) return;                       // camera denied
  toast("Loading hand tracking…");
  if (!(await loadMediaPipe())) {
    toast("Hand tracking needs internet for the first load."); return;
  }
  if (!hand.hands) {
    hand.hands = new Hands({ locateFile: (f) => MP_URL + f });
    hand.hands.setOptions({ maxNumHands: 1, modelComplexity: 0,
      minDetectionConfidence: 0.7, minTrackingConfidence: 0.6 });
    hand.hands.onResults(onHandResults);
  }
  hand.active = true; hand.haveCursor = false; hand.pinched = false;
  $("#camHand").classList.add("active");
  $("#handCursor").classList.remove("hidden");
  $("#camNote").textContent = "Gesture control on — point to move, pinch to click, pinch + move to scroll.";
  setWake("Hand tracking active");
  (async function pump() {
    if (!hand.active) return;
    const v = $("#camVideo");
    if (v.readyState >= 2 && !document.hidden) {
      try { await hand.hands.send({ image: v }); } catch {}
    }
    hand.timer = setTimeout(pump, 33);                // ~30 fps — smooth cursor
  })();
}
function stopHandTracking() {
  hand.active = false; hand.pinched = false;
  clearTimeout(hand.timer);
  $("#camHand").classList.remove("active");
  $("#handCursor").classList.add("hidden");
  $("#handCursor").classList.remove("pinch", "clicked");
  $("#camNote").textContent = "Camera is inactive. Click the power button to start.";
  idleReactor();
}

function scrollableAt(x, y) {
  let el = document.elementFromPoint(x, y);
  while (el && el !== document.body) {
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 4) return el;
    el = el.parentElement;
  }
  return document.scrollingElement;
}

function onHandResults(res) {
  const cur = $("#handCursor");
  const now = performance.now();
  const lm = res.multiHandLandmarks && res.multiHandLandmarks[0];
  if (!lm) {
    // Hand gone: fade the cursor and NEVER leave a pinch stuck half-way
    // (a stuck pinch used to click whatever the cursor reappeared on).
    if (now - hand.lastSeen > 250) {
      cur.classList.add("idle");
      hand.pinched = false; cur.classList.remove("pinch");
      hand.haveCursor = false;
    }
    return;
  }
  hand.lastSeen = now;
  cur.classList.remove("idle");

  const tip = lm[8], thumb = lm[4];                   // index fingertip + thumb tip
  const rx = (1 - tip.x) * innerWidth;                // mirror: it's a selfie view
  const ry = tip.y * innerHeight;

  // Adaptive smoothing (One-Euro style): heavy when the hand hovers (kills
  // jitter), light when it moves fast (no lag) — this is what makes the
  // cursor feel glued to your finger instead of trembling around it.
  if (!hand.haveCursor) { hand.sx = rx; hand.sy = ry; hand.haveCursor = true; }
  const speed = Math.hypot(rx - hand.sx, ry - hand.sy);
  const alpha = Math.min(0.85, 0.12 + speed / 120);
  hand.sx += (rx - hand.sx) * alpha;
  hand.sy += (ry - hand.sy) * alpha;
  const x = hand.sx, y = hand.sy;
  cur.style.transform = `translate(${x}px, ${y}px)`;

  // Pinch normalized by HAND SIZE (wrist → middle-finger knuckle), so it
  // works at any distance from the camera, with hysteresis so the state
  // can't flicker at the boundary.
  const size = Math.hypot(lm[0].x - lm[9].x, lm[0].y - lm[9].y) || 0.001;
  const ratio = Math.hypot(tip.x - thumb.x, tip.y - thumb.y) / size;
  const pinch = hand.pinched ? ratio < 0.42 : ratio < 0.30;

  if (pinch && !hand.pinched) {                       // pinch start
    hand.pinched = true; hand.moved = false; hand.startY = y;
    hand.pinchAt = now;
    hand.scrollEl = scrollableAt(x, y);
    cur.classList.add("pinch");
  } else if (pinch && hand.pinched) {                 // held: drag = scroll
    const dy = y - hand.startY;
    if (Math.abs(dy) > 14 && hand.scrollEl) {
      hand.scrollEl.scrollTop -= dy * 1.15; hand.startY = y; hand.moved = true;
    }
  } else if (!pinch && hand.pinched) {                // release: click if not a drag
    hand.pinched = false;
    cur.classList.remove("pinch");
    const held = now - hand.pinchAt;
    // A valid click is a DELIBERATE pinch: held ≥70 ms (rejects one-frame
    // flickers), released within 1.2 s (longer = you were scrolling), not a
    // drag, and ≥400 ms after the previous click (no double-fires).
    if (!hand.moved && held >= 70 && held <= 1200 && now - hand.lastClick > 400) {
      const el = document.elementFromPoint(x, y);
      if (el) {
        hand.lastClick = now;
        cur.classList.add("clicked");
        setTimeout(() => cur.classList.remove("clicked"), 250);
        el.click();
        if (/^(input|textarea)$/i.test(el.tagName)) el.focus();
      }
    }
  }
}

/* ============================================================
   VOICE ENGINE — always-on clap-to-wake + continuous dictation
   Once enabled (one mic-permission grant), it never stops:
   listens for a double clap -> captures your full command ->
   JARVIS answers -> returns to listening. Self-heals on errors.
   ============================================================ */
const voice = {
  micStream: null, ctx: null, src: null, analyser: null, rafId: 0,
  recog: null, wakeRecog: null, mode: "idle", speaking: false, capturing: false,
};

// Speech-recognition language. "" = auto (follow the browser/OS language),
// so Italian speakers are understood in Italian out of the box.
function sttLang() {
  return store.get("stt_lang", "") || navigator.language || "en-US";
}

// Wake word: saying "Hey Jackie" (or just "Jackie") activates him. Recognizers
// (especially non-English ones) hear close variants, so match generously — and
// the user can add their own aliases in Settings, which are matched too.
// "jacopus" and "jarvis" stay as courtesy aliases from the old habits.
const BUILTIN_WAKE = ["jackie", "jacky", "jacki", "jakie", "jaki", "jackey",
  "jackee", "giacchi", "giacki", "jek", "jacky boy", "hey jackie", "hey jacky",
  "jacopus", "jarvis"];
function wakeRegex() {
  const extra = String(store.get("wake_aliases", "") || "")
    .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  const words = [...new Set([...BUILTIN_WAKE, ...extra])]
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp("\\b(" + words.join("|") + ")\\b", "i");
}
// "Jarvis, open notepad" — everything after the name is already the command.
function afterWakeCommand(text) {
  const m = text.match(wakeRegex());
  if (!m) return "";
  return text.slice(m.index + m[0].length).replace(/^[\s,.!?…]+/, "").trim();
}

// ---- voice picking: prefer human-like "Natural" male voices (Edge has them
// for free); fall back to the best male voice the browser offers. ----
let _voices = [];
function refreshVoices() {
  _voices = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
  fillVoiceSelect();
}
if (window.speechSynthesis) speechSynthesis.onvoiceschanged = refreshVoices;

const MALE_RE = /andrew|guy\b|christopher|eric\b|brian|ryan|thomas|davis|tony|jason|george|giuseppe|diego|cosimo|david|daniel/i;
const FEMALE_RE = /female|zira|aria|jenny|emma\b|ava\b|sonia|elsa|isabella|michelle|libby|clara|natasha|hazel|susan/i;
function scoreVoice(v, lang) {
  let s = 0;
  if (/natural/i.test(v.name)) s += 8;          // Edge neural voices — near human
  if (/multilingual/i.test(v.name)) s += 5;     // pronounces Italian AND English natively
  if (MALE_RE.test(v.name)) s += 4;
  if (FEMALE_RE.test(v.name)) s -= 8;
  if (/google uk english male/i.test(v.name)) s += 5;  // best Chrome fallback
  const want = (lang || (sttLang() || "en").slice(0, 2)).toLowerCase();
  if ((v.lang || "").toLowerCase().startsWith(want)) s += 4;
  if (/^en/i.test(v.lang || "")) s += 1;
  return s;
}
// Which language is this reply in? Italian vs English is what matters here —
// reading Italian with an English voice is what makes pronunciation "robotic".
const IT_WORDS = /\b(ciao|sono|sei|come|che|questo|questa|tutto|fatto|bene|grazie|signore|posso|voglio|subito|ecco|certo|adesso|pronto|operativo|il|la|di|non|per|con|una|uno|sto|già)\b/gi;
function detectLang(text) {
  if (/[àèéìòù]/i.test(text)) return "it";
  return ((text || "").match(IT_WORDS) || []).length >= 3 ? "it" : "en";
}
function pickVoiceFor(lang) {
  if (!_voices.length) refreshVoices();
  const wanted = store.get("voice_name", "");
  if (wanted) {
    const v = _voices.find((x) => x.name === wanted);
    // Honor the user's pick unless the text is in a language that voice can't
    // pronounce (multilingual voices pronounce everything fine).
    if (v && (/multilingual/i.test(v.name) || (v.lang || "").toLowerCase().startsWith(lang))) return v;
  }
  return [..._voices].sort((a, b) => scoreVoice(b, lang) - scoreVoice(a, lang))[0] || null;
}
function pickVoice() { return pickVoiceFor((sttLang() || "en").slice(0, 2).toLowerCase()); }
function fillVoiceSelect() {
  const sel = $("#voiceSelect"); if (!sel) return;
  const cur = store.get("voice_name", "");
  sel.innerHTML = '<option value="">Auto — best natural male voice</option>';
  for (const v of [..._voices].sort((a, b) => scoreVoice(b) - scoreVoice(a))) {
    const o = document.createElement("option");
    o.value = v.name;
    o.textContent = v.name.replace(/^Microsoft\s+/, "").replace(/\s*Online \(Natural\)/i, " (Natural)")
      + " — " + (v.lang || "?");
    sel.appendChild(o);
  }
  if (cur && _voices.some((v) => v.name === cur)) sel.value = cur;
  const hint = $("#voiceHint");
  if (hint) hint.textContent = _voices.some((v) => /natural/i.test(v.name))
    ? "✓ Natural (human-like) voices available on this browser."
    : "Tip: open Jackie in Microsoft Edge — its free “Natural” voices sound like a real human.";
}

// ---- text to speech (returns to callback when finished speaking) ----
function speak(text, done) {
  if (!state.speak || !text || !window.speechSynthesis) { if (done) done(); return; }
  const u = new SpeechSynthesisUtterance(text);
  const lang = detectLang(text);
  const v = pickVoiceFor(lang);
  if (v) { u.voice = v; u.lang = v.lang || (lang === "it" ? "it-IT" : "en-US"); }
  else u.lang = lang === "it" ? "it-IT" : "en-US";
  const natural = v && /natural/i.test(v.name);
  u.rate = natural ? 1.0 : 1.02;   // neural voices sound most human untouched
  u.pitch = natural ? 1.0 : 0.95;
  voice.speaking = true;
  let watch = 0, cap = 0;
  const finish = () => { clearInterval(watch); clearTimeout(cap);
    voice.speaking = false; if (done) { done(); done = null; } };
  u.onend = finish; u.onerror = finish;
  speechSynthesis.cancel(); speechSynthesis.speak(u);
  // Safety net for browsers that never fire onend: poll the synth instead of
  // guessing a duration — cutting voice.speaking early made JACKIE hear his
  // OWN voice as claps and commands.
  watch = setInterval(() => {
    if (!voice.speaking) { clearInterval(watch); return; }
    if (!speechSynthesis.speaking && !speechSynthesis.pending) finish();
  }, 400);
  cap = setTimeout(finish, Math.min(90000, 5000 + text.length * 120)); // hard cap
}

// ---- single-instance lock: only ONE Jackie tab may listen -------------
// Extra tabs used to fight over the microphone and kill listening entirely.
const TAB_ID = Math.random().toString(36).slice(2);
function otherTabListening() {
  const o = store.get("voice_owner", null);
  return !!(o && o.id !== TAB_ID && Date.now() - o.t < 6000);
}
function claimVoice() {
  store.set("voice_owner", { id: TAB_ID, t: Date.now() });
  clearInterval(voice.ownerT);
  voice.ownerT = setInterval(() => {
    if (state.wake) store.set("voice_owner", { id: TAB_ID, t: Date.now() });
  }, 2500);
}
function releaseVoice() {
  clearInterval(voice.ownerT);
  const o = store.get("voice_owner", null);
  if (o && o.id === TAB_ID) localStorage.removeItem("jacopus_voice_owner");
}
window.addEventListener("beforeunload", releaseVoice);

// ---- enable / disable the whole voice engine ----
async function enableVoice() {
  if (state.wake && voice.micStream) return true;
  if (otherTabListening()) {
    toast("Jackie is already listening in another tab — close this one.");
    addMsg("jarvis", "I'm already listening in another Jackie tab, sir — use that one (or close it and click the mic here).");
    return false;
  }
  try {
    voice.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    // If the OS yanks the device (unplug, driver reset, Bluetooth drop) the
    // track just ends — recover automatically instead of going silently deaf.
    voice.micStream.getTracks().forEach((tr) => (tr.onended = () => {
      if (!state.wake) return;
      toast("Mic device lost — reconnecting…");
      disableVoice();
      setTimeout(() => enableVoice(), 1200);
    }));
  } catch {
    toast("Microphone blocked — allow mic access to use clap/voice.");
    state.wake = false; store.set("wake", false); $("#wakeToggle").checked = false;
    $("#btnMic").classList.remove("active");
    return false;
  }
  state.wake = true; store.set("wake", true);
  claimVoice();
  $("#wakeToggle").checked = true; $("#btnMic").classList.add("active");
  startClapListening();
  micHealthCheck();
  return true;
}

// One-time check after the mic starts: if it delivers pure silence, the
// problem is OUTSIDE the browser (hardware mute key) — say so loudly.
function micHealthCheck() {
  setTimeout(() => {
    const an = voice.analyser;
    if (!an || !state.wake || voice.micWarned) return;
    const buf = new Uint8Array(an.fftSize);
    let maxP = 0, n = 0;
    const iv = setInterval(() => {
      try {
        an.getByteTimeDomainData(buf);
        let p = 0; for (const b of buf) p = Math.max(p, Math.abs(b - 128) / 128);
        maxP = Math.max(maxP, p);
      } catch { clearInterval(iv); return; }
      if (++n >= 15) {
        clearInterval(iv);
        if (maxP < 0.008) {
          voice.micWarned = true;
          toast("⚠️ Mic is SILENT — press the Fn mic key");
          addMsg("jarvis", "⚠️ Your microphone is delivering total silence, sir — it looks muted at the hardware level. Press the keyboard key with the microphone icon (often Fn+F4), then click the mic button again.");
        }
      }
    }, 100);
  }, 800);
}
function disableVoice() {
  state.wake = false; store.set("wake", false);
  releaseVoice();
  stopDictation(); stopWakeWord(); voice.mode = "idle";
  if (voice.rafId) cancelAnimationFrame(voice.rafId);
  try { voice.clapProc && voice.clapProc.disconnect(); } catch {}
  voice.clapProc = null;
  try { voice.src && voice.src.disconnect(); } catch {}
  voice.src = null; voice.analyser = null;                 // rebuild graph on re-enable
  if (voice.micStream) { voice.micStream.getTracks().forEach((t) => t.stop()); voice.micStream = null; }
  $("#btnMic").classList.remove("active"); $("#wakeToggle").checked = false;
  idleReactor();
}

// ---- continuous double-clap detection ----
// Runs inside the Web Audio graph (ScriptProcessor callback), NOT on
// requestAnimationFrame: rAF never fires in a hidden/minimized tab, which
// silently killed clap detection whenever the window wasn't in front.
// Audio callbacks keep firing in background tabs.
function startClapListening() {
  if (!voice.micStream) return;
  voice.mode = "clap";
  if (!voice.ctx) {
    voice.ctx = new (window.AudioContext || window.webkitAudioContext)();
    voice.ctx.onstatechange = () => {   // self-heal a suspended graph
      if (voice.ctx.state === "suspended" && state.wake) voice.ctx.resume();
    };
  }
  if (voice.ctx.state === "suspended") voice.ctx.resume();
  if (!voice.src) { voice.src = voice.ctx.createMediaStreamSource(voice.micStream);
    voice.analyser = voice.ctx.createAnalyser(); voice.analyser.fftSize = 512;
    voice.src.connect(voice.analyser); }
  reactor("listening");
  setWake(voice.srDead ? "Double-clap or tap the mic to talk…" : "Say “Hey Jackie” or double-clap…");
  startWakeWordListening();
  if (voice.clapProc) return;                     // persistent detector already wired
  const proc = voice.ctx.createScriptProcessor(2048, 1, 1);   // ~43 ms blocks
  const sink = voice.ctx.createGain(); sink.gain.value = 0;   // silent — no echo
  voice.clapProc = proc;
  // Dual-channel detection (mirrors the Python ClapDetector): plain amplitude
  // PLUS a "transient" channel (max sample-to-sample jump). A clap is a sharp
  // broadband SNAP — its transient is huge even when it's QUIET, while voices
  // and music ramp smoothly. Each channel has its own noise floor; a spike is
  // 5× its floor AND a 2.2× jump over the previous block.
  let lastClap = 0, firstClap = 0, prevAmp = 0, prevHp = 0;
  let ampFloor = 0.01, hpFloor = 0.004, prevSample = 0;
  proc.onaudioprocess = (e) => {
    voice.loopTs = performance.now();             // heartbeat for the watchdog
    if (voice.mode !== "clap" || voice.speaking) { prevAmp = prevHp = 0; firstClap = 0; return; }
    const data = e.inputBuffer.getChannelData(0);
    let amp = 0, hp = 0;
    for (let i = 0; i < data.length; i++) {
      const v = data[i], a = Math.abs(v);
      if (a > amp) amp = a;
      const d = Math.abs(v - prevSample);
      if (d > hp) hp = d;
      prevSample = v;
    }
    const now = performance.now();
    const ampThr = Math.max(0.02, Math.min(ampFloor * 5, 0.5));
    const hpThr = Math.max(0.012, Math.min(hpFloor * 5, 0.4));
    const spike = (amp > ampThr && amp > prevAmp * 2.2)
               || (hp > hpThr && hp > prevHp * 2.2);
    if (spike && now - lastClap > 120) {
      if (firstClap && now - firstClap < 900) {
        firstClap = 0; prevAmp = amp; prevHp = hp; onWake(); return;
      }
      firstClap = now; lastClap = now;
    }
    if (firstClap && now - firstClap > 900) firstClap = 0;
    if (amp < ampThr) ampFloor = ampFloor * 0.95 + amp * 0.05;
    if (hp < hpThr) hpFloor = hpFloor * 0.95 + hp * 0.05;
    prevAmp = amp; prevHp = hp;
  };
  voice.src.connect(proc); proc.connect(sink); sink.connect(voice.ctx.destination);
}

// ---- always-on "Jarvis" wake-word spotter (runs alongside clap detection) ----
function startWakeWordListening() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR || voice.wakeRecog || voice.srDead) return;
  const r = new SR();
  r.lang = sttLang(); r.continuous = true; r.interimResults = true; r.maxAlternatives = 1;
  voice.wakeRecog = r;
  let hintT = 0;
  r.onresult = (e) => {
    voice.srEverResult = true;
    if (voice.speaking || voice.mode !== "clap") return;   // ignore his own voice
    let finals = "", interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finals += res[0].transcript + " ";
      else interim += res[0].transcript + " ";
    }
    const re = wakeRegex();
    if (finals && re.test(finals)) {
      // Utterance finished. If a command followed the name, run it directly.
      clearTimeout(r._wakeT); stopWakeWord();
      const cmd = afterWakeCommand(finals);
      if (cmd.length > 2) onWakeCommand(cmd); else onWake();
      return;
    }
    if (re.test(interim)) {
      // Name heard mid-sentence — give the recognizer a beat to finalize so a
      // same-breath command isn't cut off; if nothing more comes, just wake.
      clearTimeout(r._wakeT);
      r._wakeT = setTimeout(() => {
        if (voice.wakeRecog === r) { stopWakeWord(); onWake(); }
      }, 1500);
      setWake("Yes? — listening…");
      return;
    }
    const heard = (finals + interim).trim();
    if (heard) {
      // live feedback: show what he heard, so failed wakes are debuggable
      setWake(`Heard “…${heard.slice(-26)}” — say “Hey Jackie”`);
      clearTimeout(hintT);
      hintT = setTimeout(() => { if (voice.mode === "clap") setWake("Say “Hey Jackie” or double-clap…"); }, 2500);
    }
  };
  r.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") stopWakeWord();
    if (e.error === "language-not-supported") markSrDead(e.error);
    // no-speech / aborted / network: onend below restarts it
  };
  r.onend = () => {
    if (voice.wakeRecog === r && state.wake && voice.mode === "clap") {
      // A recognizer that keeps dying without EVER producing a result is
      // broken (Edge in many locales) — stop burning CPU on restart loops.
      if (!voice.srEverResult && ++voice.srEndFails >= 6) { markSrDead("wake-restart-loop"); return; }
      setTimeout(() => { if (voice.wakeRecog === r) { try { r.start(); } catch {} } }, 250);
    }
  };
  try { r.start(); } catch {}
}
function stopWakeWord() {
  const r = voice.wakeRecog; voice.wakeRecog = null;
  if (r) { r.onend = null; r.onresult = null; r.onerror = null;
    try { r.stop(); } catch {} try { r.abort(); } catch {} }
}

// ---- the background clap launcher heard a double clap for us ----
// (Delivered via the /api/stats poll: the launcher can't focus our window,
// but it CAN make Jackie answer out loud and start listening.)
async function clapSignal() {
  if (state.busy || voice.mode === "command" || voice.mode === "wake") return;
  if (state.wake) { onWake(); return; }
  if (await enableVoice()) onWake();     // works without a click once the mic was granted before
}

// ---- woken: greet, then capture a full spoken command ----
function onWake() {
  voice.mode = "wake";
  voice.followUp = false; voice.sttRetry = false;
  reactor("speaking");
  // full "Systems online" greeting on the first activation, snappy after that
  const line = state.greeted ? "Yes?" : greetingText();
  state.greeted = true;
  speak(line, () => startDictation());
}

// ---- woken WITH a command in the same breath ("Jarvis, open notepad") ----
function onWakeCommand(cmd) {
  voice.mode = "wake";
  state.greeted = true;
  reactor("thinking");
  sendMessage(cmd).finally(afterVoiceReply);
}

// After answering a spoken command, immediately listen for a follow-up —
// a real conversation, not one question per wake. Silence ends it cleanly.
function afterVoiceReply() {
  voice.sttRetry = false;
  if (state.wake) { voice.followUp = true; startDictation(); }
  else idleReactor();
}

// ---- continuous dictation that DOESN'T die after a couple seconds ----
function startDictation() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (voice.srDead || !SR) { startServerDictation(); return; }
  stopDictation(); stopWakeWord();
  const r = new SR();
  r.lang = sttLang();
  r.continuous = true; r.interimResults = true; r.maxAlternatives = 1;
  voice.recog = r; voice.mode = "command"; voice.capturing = true;
  let finalText = "", silence = 0, gotAny = false, endCount = 0;
  reactor("listening"); setWake("Listening… speak your command");

  const fallback = (why) => {                      // native STT is broken here
    markSrDead(why); stopDictation(); startServerDictation();
  };
  const armSilence = () => {                       // end capture after a real pause
    clearTimeout(silence);
    // generous windows: 8s to start talking (5s on follow-ups), 2.5s pause
    // to finish a sentence
    silence = setTimeout(() => finalize(), gotAny ? 2500 : (voice.followUp ? 5000 : 8000));
  };
  const finalize = () => {
    if (!voice.capturing) return;
    voice.capturing = false; clearTimeout(silence);
    voice.forceFinalize = null;
    const t = finalText.trim();
    stopDictation();
    if (t) {
      voice.emptyCaptures = 0;
      $("#chatText").value = ""; sendMessage(t).finally(afterVoiceReply);
    } else if (voice.followUp) {
      voice.followUp = false; resumeListening();   // conversation over, no penalty
    } else if (!gotAny && ++voice.emptyCaptures >= 2) {
      // Two wakes in a row where the recognizer heard NOTHING — it's not
      // working in this browser. Switch to backend listening silently.
      voice.emptyCaptures = 0; fallback("silent-captures");
    } else { resumeListening(); }
  };
  voice.forceFinalize = finalize;                  // mic button tap = done talking

  r.onresult = (e) => {
    if (voice.speaking) return;                     // ignore JACKIE's own voice
    gotAny = true; voice.srEverResult = true;
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finalText += res[0].transcript + " ";
      else interim += res[0].transcript;
    }
    setWake("“" + (finalText + interim).trim().slice(0, 46) + "”");
    armSilence();
  };
  r.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") { disableVoice(); return; }
    if (e.error === "language-not-supported" || e.error === "audio-capture") { fallback(e.error); return; }
    if (e.error === "network" && ++voice.srNetErrors >= 2) { fallback("network"); return; }
    // no-speech / aborted: let onend auto-restart below
  };
  r.onend = () => {                                 // keep listening: restart if still capturing
    if (voice.capturing && voice.recog === r) {
      if (!gotAny && ++endCount >= 3) { fallback("restart-loop"); return; }
      try { r.start(); } catch {}
    }
  };
  try { r.start(); } catch { fallback("start-threw"); return; }
  armSilence();
}
function stopDictation() {
  const r = voice.recog; voice.recog = null; voice.capturing = false;
  if (r) { r.onend = null; r.onresult = null; r.onerror = null; try { r.stop(); } catch {} try { r.abort(); } catch {} }
}
function resumeListening() {
  if (state.wake) startClapListening(); else idleReactor();
}

/* ---- server-side dictation (Wispr-Flow style) --------------------------
   Records raw PCM with the Web Audio graph we already have for claps,
   detects when you stop talking, sends a WAV to /api/stt and runs the
   transcribed command. Works in ANY browser — used automatically when the
   native SpeechRecognition is missing or broken (Edge, some locales). */
function markSrDead(why) {
  if (voice.srDead) return;
  voice.srDead = true; store.set("stt_engine", "server");
  console.warn("SpeechRecognition unusable (" + (why || "?") + ") — switching to backend listening.");
  stopWakeWord();
}

function startServerDictation() {
  stopWakeWord(); stopDictation();
  if (!state.backend) {
    toast("Voice input needs the backend — start Jackie.bat");
    resumeListening(); return;
  }
  if (!voice.micStream) { resumeListening(); return; }
  voice.mode = "command"; voice.capturing = true;
  reactor("listening"); setWake("Listening… speak now");
  if (!voice.ctx) voice.ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (voice.ctx.state === "suspended") voice.ctx.resume();
  if (!voice.src) {
    voice.src = voice.ctx.createMediaStreamSource(voice.micStream);
    voice.analyser = voice.ctx.createAnalyser(); voice.analyser.fftSize = 512;
    voice.src.connect(voice.analyser);
  }
  const proc = voice.ctx.createScriptProcessor(4096, 1, 1);
  const mute = voice.ctx.createGain(); mute.gain.value = 0;   // no echo
  voice.proc = proc;
  const chunks = [];
  // Generous windows: 12s to start talking (6s on follow-ups), 2.2s pause =
  // sentence done, 30s cap.
  const NO_SPEECH_MS = voice.followUp ? 6000 : 12000, SILENCE_HOLD_MS = 2200, MAX_MS = 30000;
  let started = false, lastVoice = 0, t0 = performance.now(), vuT = 0;
  let floor = 0.004;                                // adaptive ambient floor
  const finalize = () => finishServerCapture(proc, chunks, started);
  voice.forceFinalize = finalize;                   // mic button tap = done talking
  proc.onaudioprocess = (e) => {
    if (!voice.capturing || voice.proc !== proc) return;
    const data = e.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(data));
    let peak = 0;
    for (let i = 0; i < data.length; i += 4) peak = Math.max(peak, Math.abs(data[i]));
    const now = performance.now();
    if (voice.speaking) { t0 = now; return; }       // TTS time doesn't count
    if (!started && now - t0 < 500) floor = Math.min(0.06, Math.max(floor, peak * 3));
    // live VU meter — you SEE that it hears you
    if (now - vuT > 150) {
      vuT = now;
      const bars = Math.min(8, Math.round(peak * 50));
      setWake((started ? "Listening " : "Listening… speak now ") + "▮".repeat(bars || 0));
    }
    if (peak > Math.max(0.006, floor)) { started = true; lastVoice = now; }
    if ((started && now - lastVoice > SILENCE_HOLD_MS) || (!started && now - t0 > NO_SPEECH_MS) || now - t0 > MAX_MS) {
      finalize();
    }
  };
  voice.src.connect(proc); proc.connect(mute); mute.connect(voice.ctx.destination);
}

function finishServerCapture(proc, chunks, started) {
  if (!voice.capturing || voice.proc !== proc) return;
  voice.capturing = false; voice.proc = null; voice.forceFinalize = null;
  try { proc.disconnect(); } catch {}
  if (!started) { voice.followUp = false; resumeListening(); return; }
  reactor("thinking"); setWake("Understanding…");
  const wav = encodeWav(chunks, voice.ctx.sampleRate, 16000);
  fetch("/api/stt?lang=" + encodeURIComponent(sttLang()), {
    method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav,
  })
    .then((r) => r.json())
    .then((j) => {
      const t = (j.text || "").trim();
      if (t) {
        voice.sttRetry = false;
        setWake("“" + t.slice(0, 46) + "”"); sendMessage(t).finally(afterVoiceReply);
      } else if (!voice.sttRetry) {
        // didn't catch it — apologize once and listen again right away
        voice.sttRetry = true;
        speak(sttLang().startsWith("it") ? "Non ho capito, ripeti pure." : "Sorry, I didn't catch that — say it again.", () => startDictation());
      } else {
        voice.sttRetry = false;
        speak(sttLang().startsWith("it") ? "Riproviamo più tardi, signore." : "Let's try again later, sir.", resumeListening);
      }
    })
    .catch(() => { toast("Speech recognition failed — try again."); resumeListening(); });
}

// Float32 chunks (ctx sample rate) -> 16 kHz 16-bit mono WAV ArrayBuffer.
// The signal is NORMALIZED to near full scale first: weak microphones produce
// audio the recognizer can't hear — software gain fixes that for free.
function encodeWav(chunks, srcRate, dstRate) {
  let len = 0; for (const c of chunks) len += c.length;
  const all = new Float32Array(len); let o = 0;
  for (const c of chunks) { all.set(c, o); o += c.length; }
  let maxAmp = 0;
  for (let i = 0; i < all.length; i++) maxAmp = Math.max(maxAmp, Math.abs(all[i]));
  const gain = maxAmp > 0.001 ? Math.min(0.95 / maxAmp, 40) : 1;  // up to 40x boost
  const ratio = srcRate / dstRate, outLen = Math.floor(all.length / ratio);
  const pcm = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const a = Math.floor(i * ratio), b = Math.min(all.length, Math.floor((i + 1) * ratio));
    let sum = 0, n = 0;
    for (let j = a; j < b; j++) { sum += all[j]; n++; }
    const s = Math.max(-1, Math.min(1, (n ? sum / n : 0) * gain));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const dv = new DataView(buf);
  const w = (off, str) => { for (let i = 0; i < str.length; i++) dv.setUint8(off + i, str.charCodeAt(i)); };
  w(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE");
  w(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, dstRate, true); dv.setUint32(28, dstRate * 2, true);
  dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
  w(36, "data"); dv.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return buf;
}

/* ---------------- reactor + idle state ---------------- */
function reactor(cls) { $("#reactor").className = "reactor" + (cls ? " " + cls : ""); }

/* ---------------- energy orb — the center UI ----------------
   A living plasma sphere: a white-hot nucleus inside layered
   chromatic wisps, a thin filament shell, and a sparse ring of
   orbiting sparks. Reads the reactor's state class every frame
   and CROSS-FADES its palette (no hard color jumps):
     idle      violet/blue, slow drift
     listening emerald/teal, alert
     thinking  amber/indigo, fast swirl
     speaking  cyan/violet, pulsing with the voice          */
function initOrb() {
  const host = $("#reactor"), cv = $("#orbCanvas");
  if (!host || !cv) return;
  const ctx = cv.getContext("2d");
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // palette per state: [wisp A, wisp B, accent] as r,g,b
  const PALETTES = {
    idle:      [[167, 139, 250], [ 96, 165, 250], [225, 221, 254]],
    listening: [[ 52, 211, 153], [ 45, 212, 191], [211, 250, 235]],
    thinking:  [[251, 191,  36], [129, 140, 248], [254, 243, 209]],
    speaking:  [[125, 211, 252], [167, 139, 250], [231, 244, 255]],
  };
  const cur = PALETTES.idle.map((c) => c.slice());       // animated (lerped) palette
  const sparks = Array.from({ length: 22 }, () => ({
    a: Math.random() * Math.PI * 2,                      // orbit angle
    r: 0.62 + Math.random() * 0.52,                      // orbit radius (×R)
    s: (0.25 + Math.random() * 0.55) * (Math.random() < 0.5 ? -1 : 1),
    e: 0.35 + Math.random() * 0.55,                      // ellipse squash
    tilt: Math.random() * Math.PI,                       // orbit plane rotation
    z: Math.random() * Math.PI * 2,                      // twinkle phase
  }));
  let t = 0, last = 0, vu = 0, vuBuf = null;

  // Live microphone level (0..1-ish) while Jackie is listening — drives the
  // orb so it visibly reacts to YOUR voice. Uses the analyser that the voice
  // engine already keeps in its audio graph; ×14 gain compensates weak mics.
  function micLevel() {
    const an = voice.analyser;
    if (!an || !state.wake) return 0;
    if (!vuBuf || vuBuf.length !== an.fftSize) vuBuf = new Uint8Array(an.fftSize);
    try { an.getByteTimeDomainData(vuBuf); } catch { return 0; }
    let p = 0;
    for (let i = 0; i < vuBuf.length; i += 2) {
      const a = Math.abs(vuBuf[i] - 128) / 128;
      if (a > p) p = a;
    }
    return Math.min(1, p * 14);
  }

  function blob(cx, cy, r, rot, wob1, wob2, color, width, blur) {
    ctx.beginPath();
    for (let a = 0; a <= Math.PI * 2 + 0.01; a += 0.1) {
      const w = 1 + wob1 * Math.sin(a * 2 + rot) + wob2 * Math.sin(a * 4 - rot * 1.7)
              + (wob2 / 2) * Math.sin(a * 7 + rot * 0.6);
      const x = cx + Math.cos(a) * r * w, y = cy + Math.sin(a) * r * w;
      a === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = color; ctx.lineWidth = width;
    ctx.shadowColor = color; ctx.shadowBlur = blur;
    ctx.stroke();
  }

  function draw(now) {
    if (now - last < 33) return;                     // ~30 fps, easy on the CPU
    // time-based stepping: a hidden tab draws at 2 fps (heartbeat below) and
    // must advance the same amount per second as a visible one
    const dtF = Math.min(20, last ? (now - last) / 33 : 1);
    last = now;
    const w = host.clientWidth, h = host.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);   // crisp on hi-DPI
    if (cv.width !== w * dpr || cv.height !== h * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cls = host.className;
    const mode = cls.includes("thinking") ? "thinking"
               : cls.includes("speaking") ? "speaking"
               : cls.includes("listening") ? "listening" : "idle";
    const target = PALETTES[mode];
    const k = 1 - Math.pow(0.94, dtF);               // palette cross-fade, ~1s
    for (let i = 0; i < 3; i++)
      for (let j = 0; j < 3; j++) cur[i][j] += (target[i][j] - cur[i][j]) * k;
    const C = (i, a) => `rgba(${cur[i][0] | 0},${cur[i][1] | 0},${cur[i][2] | 0},${a})`;

    // voice-reactive: fast attack, slow release, only while listening
    const lvl = (mode === "listening" && !voice.speaking) ? micLevel() : 0;
    vu += (lvl - vu) * (lvl > vu ? 0.55 : 0.10);

    const speed = REDUCED ? 0.12
                : mode === "thinking" ? 2.4 : mode === "speaking" ? 1.7
                : mode === "listening" ? 1.15 + vu * 1.6 : 0.55;
    t += 0.016 * speed * dtF;
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.33;
    const pulse = (REDUCED ? 1
                : mode === "speaking" ? 1 + 0.08 * Math.sin(t * 9)
                : mode === "listening" ? 1 + 0.03 * Math.sin(t * 4)
                : 1 + 0.015 * Math.sin(t * 2)) + (REDUCED ? 0 : vu * 0.22);

    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";

    // ambient halo (brightens with your voice)
    let g = ctx.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.65);
    g.addColorStop(0, C(0, Math.min(0.3, 0.13 + vu * 0.15)));
    g.addColorStop(0.55, C(1, 0.05));
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

    // white-hot nucleus
    g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.55 * pulse);
    g.addColorStop(0, "rgba(255,255,255,0.9)");
    g.addColorStop(0.22, C(2, 0.55));
    g.addColorStop(0.6, C(0, 0.2));
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R * 0.55 * pulse, 0, 7); ctx.fill();

    // thin filament shell (the glass sphere)
    blob(cx, cy, R * 1.08 * pulse,  t * 0.30,       0.045, 0.028, "rgba(238,242,255,0.28)", 1.5, 12);
    blob(cx, cy, R * 1.03 * pulse, -t * 0.22 + 2.1, 0.06,  0.03,  "rgba(215,225,255,0.16)", 1.2, 10);

    // chromatic plasma wisps (wobble harder while you speak)
    const vw = 1 + vu * 0.9;
    blob(cx, cy, R * 0.56 * pulse,  t * 0.9,        0.34 * vw, 0.18 * vw, C(0, Math.min(1, 0.6 + vu * 0.3)),  2.6, 22);
    blob(cx, cy, R * 0.46 * pulse, -t * 1.15 + 1.4, 0.38 * vw, 0.20 * vw, C(1, Math.min(1, 0.55 + vu * 0.3)), 2.2, 20);
    blob(cx, cy, R * 0.34 * pulse,  t * 1.5 + 3.0,  0.30 * vw, 0.16 * vw, C(2, Math.min(1, 0.42 + vu * 0.3)), 1.6, 16);

    // orbiting sparks
    ctx.shadowBlur = 9;
    for (const p of sparks) {
      p.a += 0.016 * speed * p.s * dtF;
      const rr = R * p.r * pulse;
      const ox = Math.cos(p.a) * rr, oy = Math.sin(p.a) * rr * p.e;
      const px = cx + ox * Math.cos(p.tilt) - oy * Math.sin(p.tilt);
      const py = cy + ox * Math.sin(p.tilt) + oy * Math.cos(p.tilt);
      const tw = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * 3 + p.z));
      ctx.shadowColor = C(1, 0.9);
      ctx.fillStyle = `rgba(255,255,255,${0.55 * tw})`;
      ctx.beginPath(); ctx.arc(px, py, 1 + tw * 1.2, 0, 7); ctx.fill();
    }
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";
  }
  (function loop(now) { requestAnimationFrame(loop); draw(now || performance.now()); })(0);
  // rAF pauses in hidden tabs — keep a slow heartbeat so the orb is never blank
  setInterval(() => { if (document.hidden) draw(performance.now()); }, 500);
}
function idleReactor() {
  if (state.wake) {
    reactor("listening");
    setWake(voice.srDead ? "Double-clap or tap the mic to talk…" : "Say “Hey Jackie” or double-clap…");
  }
  else { reactor(""); setWake((currentKey() || state.backend) ? "Ready — say “Hey Jackie”, clap, or type" : "Idle — connect your key"); }
}

/* ---------------- chat ---------------- */
function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  const time = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  div.innerHTML = `<span class="body"></span>${role !== "tool" ? `<span class="time">${time}</span>` : ""}`;
  div.querySelector(".body").textContent = text;
  const log = $("#chatLog");
  log.appendChild(div); log.scrollTop = 1e9;
  while (log.children.length > 200) log.removeChild(log.firstChild);  // keep the DOM light
  return div;
}
function timeGreeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
function greetingText() {
  return `${timeGreeting()}. Systems online. How may I assist you?`;
}
function greeting() {
  addMsg("jarvis", greetingText() + (state.backend
    ? "" : " (Backend offline — run Jackie.bat for full computer control.)"));
}

async function sendMessage(text) {
  text = (text || $("#chatText").value).trim();
  if (!text || state.busy) return;
  $("#chatText").value = ""; addMsg("user", text);
  state.commands++; state.messages.push({ role: "user", content: text });
  if (state.messages.length > 40) state.messages.splice(0, state.messages.length - 40);
  if (!state.backend && PROVIDERS[state.provider].kind === "claude-cli") {
    const m = "Claude Code runs locally, sir — start the Jackie backend (Jackie.bat) and reload this page.";
    addMsg("jarvis", m); speak(m); return;
  }
  if (!currentKey() && !state.backend) {
    const m = "I need an API key first. Open Settings (gear, top-right) and paste your free OpenRouter key.";
    addMsg("jarvis", m); speak(m); openSettings(); return;
  }
  state.busy = true; reactor("thinking"); setWake("Thinking…");
  try {
    if (state.backend) await runBackendAgent(text);
    else await runBrowserChat(text);
  } catch (e) {
    addMsg("jarvis", "⚠️ " + e.message);
  } finally {
    state.busy = false; idleReactor();
  }
}

// Full mode: the Python agent (real tools) runs the goal server-side.
async function runBackendAgent(text) {
  const r = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text }),
  });
  const j = await r.json();
  for (const ev of j.events || []) {
    if (ev.type === "tool") addMsg("tool", "⚙ " + ev.text);
    else { addMsg("jarvis", ev.text); if (ev.type !== "step") speak(ev.text); }
  }
  if (j.error) addMsg("jarvis", "⚠️ " + j.error);
}

// One browser-side chat request; speaks both wire protocols (OpenAI-shaped
// and Anthropic's native Messages API).
async function providerFetch(prov, key, model, sys, msgs, maxTokens) {
  if (prov.kind === "anthropic") {
    return fetch(prov.url, {
      method: "POST",
      headers: {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: JSON.stringify({ model, max_tokens: maxTokens || 1024, system: sys, messages: msgs }),
    });
  }
  return fetch(prov.url, {
    method: "POST",
    headers: { "Authorization": "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages: [{ role: "system", content: sys }, ...msgs], temperature: 0.5 }),
  });
}
function providerReply(prov, j) {
  if (prov.kind === "anthropic")
    return (j.content || []).filter((b) => b.type === "text").map((b) => b.text).join("").trim();
  return j.choices?.[0]?.message?.content?.trim() || "";
}

// Lite mode: chat straight from the browser to the provider.
// Tries the provider's models in order so one bad/renamed model doesn't fail.
async function runBrowserChat(text) {
  const prov = PROVIDERS[state.provider];
  const override = store.get("model", "");
  const models = override ? [override] : prov.models;
  const sys = "You are JACKIE (Jackie 1.0), an autonomous AI operating system in the style of Iron Man's assistant. "
    + "Address the user as 'sir'. Be concise, natural and proactive. Never fabricate results — "
    + "if you don't know, say so. Your computer-control backend is offline right now, so you can "
    + "converse and advise but cannot run commands; suggest launching Jackie.bat when a task needs real control. "
    + "Keep answers brief unless asked for detail.";
  const msgs = state.messages.slice(-10);
  let lastErr = "";
  for (const model of models) {
    let r;
    try {
      r = await providerFetch(prov, currentKey(), model, sys, msgs, 1024);
    } catch (e) {
      lastErr = "Network/CORS blocked. On the web version use OpenRouter, Gemini, Groq or Claude; "
        + "other providers need the Jackie backend.";
      continue;
    }
    if (r.ok) {
      const j = await r.json();
      const reply = providerReply(prov, j) || "…";
      state.messages.push({ role: "assistant", content: reply });
      if (state.messages.length > 40) state.messages.splice(0, state.messages.length - 40);
      const div = addMsg("jarvis", ""); typeOut(div.querySelector(".body"), reply); speak(reply);
      return;
    }
    lastErr = `Provider error ${r.status}` + (r.status === 401 || r.status === 403 ? " — check your API key." : "");
  }
  throw new Error(lastErr || "Could not reach the model.");
}
function typeOut(el, text) {
  let i = 0; (function t() { el.textContent = text.slice(0, i++); $("#chatLog").scrollTop = 1e9;
    if (i <= text.length) setTimeout(t, 12); })();
}

/* ---------------- news feed ---------------- */
function timeAgo(dateStr) {
  const t = new Date(dateStr).getTime();
  if (!t) return "";
  const m = Math.max(1, Math.round((Date.now() - t) / 60000));
  if (m < 60) return m + "m ago";
  const h = Math.round(m / 60);
  return h < 24 ? h + "h ago" : Math.round(h / 24) + "d ago";
}
async function refreshNews() {
  const list = $("#newsList");
  try {
    let items = [];
    if (state.backend) {
      try {
        items = (await (await fetch("/api/news", { cache: "no-store" })).json()).items || [];
      } catch {}
    }
    if (!items.length) {
      // lite mode (or proxy failure): Hacker News front page — free, no key, CORS-open
      const j = await (await fetch("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=10")).json();
      items = (j.hits || []).map((h) => ({
        title: h.title,
        link: h.url || "https://news.ycombinator.com/item?id=" + h.objectID,
        source: "Hacker News", date: h.created_at,
      }));
    }
    list.innerHTML = "";
    for (const it of items) {
      const a = document.createElement("a");
      a.className = "news-item"; a.href = it.link || "#"; a.target = "_blank"; a.rel = "noopener";
      const t = document.createElement("div"); t.className = "news-title"; t.textContent = it.title;
      const meta = document.createElement("div"); meta.className = "news-meta";
      const src = document.createElement("span"); src.className = "src"; src.textContent = it.source || "";
      const ago = document.createElement("span"); ago.textContent = timeAgo(it.date);
      meta.append(src, ago); a.append(t, meta); list.appendChild(a);
    }
    if (!items.length) list.innerHTML = '<div class="news-empty">No headlines right now.</div>';
  } catch {
    list.innerHTML = '<div class="news-empty">News unavailable — check the connection.</div>';
  }
}

/* ---------------- tasks ---------------- */
async function loadTasks() {
  if (state.backend) {
    try {
      state.tasks = (await (await fetch("/api/tasks", { cache: "no-store" })).json()).tasks || [];
      renderTasks(); return;
    } catch {}
  }
  state.tasks = store.get("tasks", []);
  renderTasks();
}
async function taskAction(action, payload) {
  if (state.backend) {
    try {
      const r = await fetch("/api/tasks", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...payload }) });
      state.tasks = (await r.json()).tasks || [];
      renderTasks(); return;
    } catch {}
  }
  // lite mode: localStorage
  if (action === "add") state.tasks.push({ id: Date.now(), text: payload.text, done: false });
  if (action === "toggle") state.tasks.forEach((t) => { if (t.id === payload.id) t.done = payload.done; });
  if (action === "delete") state.tasks = state.tasks.filter((t) => t.id !== payload.id);
  store.set("tasks", state.tasks);
  renderTasks();
}
function renderTasks() {
  const list = $("#taskList");
  list.innerHTML = "";
  const open = state.tasks.filter((t) => !t.done).length;
  $("#taskCount").textContent = open + " open";
  if (!state.tasks.length) {
    list.innerHTML = '<div class="task-empty">No tasks — add one below or just ask Jackie.</div>';
    return;
  }
  for (const t of [...state.tasks].reverse()) {
    const row = document.createElement("div");
    row.className = "task-row" + (t.done ? " done" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!t.done;
    cb.onchange = () => taskAction("toggle", { id: t.id, done: cb.checked });
    const txt = document.createElement("span"); txt.className = "task-text"; txt.textContent = t.text;
    const del = document.createElement("button");
    del.className = "task-del"; del.textContent = "×"; del.title = "Delete";
    del.onclick = () => taskAction("delete", { id: t.id });
    row.append(cb, txt, del); list.appendChild(row);
  }
}

/* ---------------- notifications ---------------- */
function pushNote(text, level) {
  state.notes.unshift({ id: Date.now(), ts: Date.now() / 1000, text, level: level || "info" });
  state.notes = state.notes.slice(0, 50);
  renderNotes();
}
async function pollNotes() {
  if (!state.backend) return;
  try {
    const j = await (await fetch("/api/notifications", { cache: "no-store" })).json();
    state.notes = j.items || [];
    renderNotes();
  } catch {}
}
function renderNotes() {
  const list = $("#notifList");
  list.innerHTML = "";
  if (!state.notes.length) {
    list.innerHTML = '<div class="notif-empty">All clear — no notifications.</div>';
  }
  for (const n of state.notes) {
    const d = document.createElement("div");
    d.className = "notif-item " + (n.level || "info");
    d.textContent = n.text;
    const time = document.createElement("span");
    time.className = "time"; time.textContent = timeAgo(n.ts * 1000);
    d.appendChild(time); list.appendChild(d);
  }
  const unread = state.notes.filter((n) => n.ts > store.get("notes_read_ts", 0)).length;
  const badge = $("#notifBadge");
  badge.textContent = unread;
  badge.classList.toggle("hidden", !unread);
}
function toggleNotifPanel(open) {
  const p = $("#notifPanel");
  const show = open != null ? open : p.classList.contains("hidden");
  p.classList.toggle("hidden", !show);
  if (show) { store.set("notes_read_ts", Date.now() / 1000); renderNotes(); }
}
async function clearNotes() {
  if (state.backend) {
    try {
      await fetch("/api/notifications", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "clear" }) });
    } catch {}
  }
  state.notes = [];
  renderNotes();
}

/* ---------------- settings ---------------- */
function fillProviders() {
  const sel = $("#providerSelect"); sel.innerHTML = "";
  for (const [k, v] of Object.entries(PROVIDERS)) {
    const o = document.createElement("option"); o.value = k; o.textContent = v.label; sel.appendChild(o);
  }
  sel.value = state.provider;
}
function syncSettingsUI() {
  $("#providerSelect").value = state.provider;  // stay in sync with the backend's active provider
  const prov = PROVIDERS[state.provider];
  const nokey = !!prov.nokey;
  $("#apiKey").value = nokey ? "" : currentKey();
  $("#apiKey").disabled = nokey;
  $("#apiKey").placeholder = nokey
    ? "No API key needed — uses your Claude Code login" : "Paste your API key";
  $("#modelInput").value = store.get("model", "");
  $("#sttLang").value = store.get("stt_lang", "");
  $("#wakeAliases").value = store.get("wake_aliases", "");
  $("#getKeyLink").href = prov.keyUrl;
  $("#getKeyLink").textContent = nokey
    ? "No key needed — one-time `claude` → /login ↗"
    : "Get a key ↗  " + prov.keyUrl.replace("https://", "");
  const cli = prov.kind === "claude-cli";
  $("#modelSelectField").hidden = !cli;
  $("#modelTextField").hidden = cli;
  if (cli) $("#modelSelect").value = store.get("model", "");
  fillVoiceSelect();
  $("#speakToggle").checked = state.speak;
  $("#wakeToggle").checked = state.wake;
  if (prov.kind === "claude-cli" && !state.backend)
    setMsg("Claude Code runs on your PC — start the backend (Jackie.bat) to use it.", "err");
  else if (!prov.browser && !state.backend)
    setMsg("Note: this provider may block direct browser calls (CORS). OpenRouter works best without the backend.", "err");
  else setMsg("", "");
}
function openSettings() { $("#settingsModal").classList.remove("hidden"); syncSettingsUI(); }
function setMsg(t, cls) { const m = $("#settingsMsg"); m.textContent = t; m.className = "settings-msg " + (cls || ""); }

async function saveSettings() {
  state.provider = $("#providerSelect").value;
  store.set("provider", state.provider);
  const key = $("#apiKey").value.trim();
  if (key) store.set("key_" + state.provider, key);
  const model = PROVIDERS[state.provider].kind === "claude-cli"
    ? $("#modelSelect").value : $("#modelInput").value.trim();
  store.set("model", model);
  store.set("voice_name", $("#voiceSelect").value);
  store.set("stt_lang", $("#sttLang").value);
  store.set("wake_aliases", $("#wakeAliases").value.trim());
  state.speak = $("#speakToggle").checked; store.set("speak", state.speak);
  if (state.backend) {
    try {
      await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: state.provider, key, model,
          speak: state.speak, stt_lang: sttLang() }) });
    } catch {}
  }
  setMsg("✅ Saved.", "ok");
  setStatus(state.backend, !!currentKey());
  setTimeout(() => $("#settingsModal").classList.add("hidden"), 700);
}
async function testKey() {
  setMsg("Testing…", "");
  try {
    if (state.backend) {
      await saveSilent();
      const j = await (await fetch("/api/test", { method: "POST" })).json();
      setMsg(j.ok ? "✅ " + j.message : "❌ " + j.message, j.ok ? "ok" : "err");
    } else {
      const prov = PROVIDERS[$("#providerSelect").value];
      if (prov.kind === "claude-cli") {
        setMsg("❌ Claude Code needs the backend — start Jackie.bat first.", "err");
        return;
      }
      const key = $("#apiKey").value.trim();
      const override = $("#modelInput").value.trim();
      const models = override ? [override] : prov.models;
      let last = "";
      for (const model of models) {
        let r;
        try {
          r = await providerFetch(prov, key, model, "Reply with one word.",
            [{ role: "user", content: "say online" }], 16);
        } catch { last = "Network/CORS blocked — this provider may need the Jackie backend (OpenRouter, Gemini, Groq & Claude work in-browser)."; continue; }
        if (r.ok) { setMsg(`✅ Connected — your key works (${model}).`, "ok"); return; }
        last = `Error ${r.status}` + (r.status === 401 || r.status === 403 ? " — check the key." : ` on ${model}`);
      }
      setMsg("❌ " + last, "err");
    }
  } catch (e) { setMsg("❌ " + e.message, "err"); }
}
async function saveSilent() {
  const key = $("#apiKey").value.trim();
  const prov = PROVIDERS[$("#providerSelect").value];
  const model = prov && prov.kind === "claude-cli" ? $("#modelSelect").value : $("#modelInput").value.trim();
  await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: $("#providerSelect").value, key, model }) }).catch(()=>{});
}

/* ---------------- extract / clear ---------------- */
function extractConversation() {
  const lines = [...document.querySelectorAll(".msg")].map((m) => {
    const who = m.classList.contains("user") ? "You" : m.classList.contains("tool") ? "Tool" : "JACKIE";
    return `${who}: ${m.querySelector(".body").textContent}`;
  });
  const blob = new Blob(["Jackie conversation\n\n" + lines.join("\n\n")], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "jackie-conversation.txt"; a.click();
}
function clearChat() { $("#chatLog").innerHTML = ""; state.messages = []; greeting(); }

/* ---------------- misc ---------------- */
let toastT;
function toast(t) { setWake(t); clearTimeout(toastT); toastT = setTimeout(() => setStatus(state.backend, !!currentKey()), 2500); }

/* ---------------- wiring ---------------- */
// Browsers require a user gesture before mic/AudioContext can start. If voice
// was on last time, resume it on the very first interaction with the page.
function armVoiceGesture() {
  const h = () => { document.removeEventListener("pointerdown", h); document.removeEventListener("keydown", h); enableVoice(); };
  document.addEventListener("pointerdown", h); document.addEventListener("keydown", h);
}

function init() {
  state.provider = store.get("provider", "openrouter");
  state.speak = store.get("speak", true);
  state.wake = false; // becomes true once the mic is actually granted

  fillProviders();
  initOrb();
  refreshWeather(); refreshStats();

  $("#settingsBtn").onclick = openSettings;
  $("#closeSettings").onclick = () => $("#settingsModal").classList.add("hidden");
  $("#providerSelect").onchange = () => { state.provider = $("#providerSelect").value; syncSettingsUI(); };
  $("#toggleKey").onclick = () => { const i = $("#apiKey"); i.type = i.type === "password" ? "text" : "password"; };
  $("#saveSettings").onclick = saveSettings;
  $("#testKey").onclick = testKey;
  refreshVoices();
  $("#voiceTest").onclick = () => {
    store.set("voice_name", $("#voiceSelect").value);
    speak("Good evening, sir. All systems fully operational.");
  };

  // ---- crash-proofing: recover instead of dying ----
  voice.srDead = store.get("stt_engine", "") === "server";
  voice.srEverResult = false; voice.srEndFails = 0; voice.srNetErrors = 0; voice.emptyCaptures = 0;
  let lastRecover = 0;
  const recover = () => {
    const now = Date.now();
    if (now - lastRecover < 8000) return;   // never loop on recovery itself
    lastRecover = now;
    try { if (state.wake && voice.mode === "clap") startClapListening(); } catch {}
  };
  window.addEventListener("error", recover);
  window.addEventListener("unhandledrejection", recover);
  setInterval(() => {   // watchdog: un-wedge the voice engine
    try {
      if (state.wake && voice.mode === "clap" && performance.now() - (voice.loopTs || 0) > 8000)
        startClapListening();
      if (voice.mode === "command" && !voice.capturing && !state.busy)
        resumeListening();
    } catch {}
  }, 15000);
  $("#speakToggle").onchange = () => { state.speak = $("#speakToggle").checked; };
  $("#wakeToggle").onchange = (e) => (e.target.checked ? enableVoice() : disableVoice());

  $("#chatForm").onsubmit = (e) => { e.preventDefault(); sendMessage(); };
  $("#clearChat").onclick = clearChat;
  $("#extractChat").onclick = extractConversation;

  $("#taskForm").onsubmit = (e) => {
    e.preventDefault();
    const text = $("#taskInput").value.trim();
    if (text) { $("#taskInput").value = ""; taskAction("add", { text }); }
  };
  $("#notifBtn").onclick = () => toggleNotifPanel();
  $("#notifClear").onclick = clearNotes;
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("#notifPanel") && !e.target.closest("#notifBtn")) toggleNotifPanel(false);
  });

  // Mic button / reactor = "talk now": turn voice on (if needed) and capture a command.
  $("#btnMic").onclick = async () => {
    // tap while he's listening = "I'm done talking, process it now"
    if (voice.mode === "command" && voice.forceFinalize) { voice.forceFinalize(); return; }
    if (await enableVoice()) startDictation();
  };
  $("#reactor").onclick = async () => { if (await enableVoice()) startDictation(); };
  $("#btnCamera").onclick = toggleCamera;
  $("#camPower").onclick = toggleCamera;
  $("#camSnap").onclick = snapshot;
  $("#camHand").onclick = toggleHandTracking;
  $("#btnKeyboard").onclick = () => $("#chatText").focus();

  // T toggles the microphone (same key as the desktop hotkey). Ignored while
  // typing in a field or holding modifiers, so normal typing never trips it.
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    if (e.target && e.target.closest && e.target.closest("input, textarea, select")) return;
    if (e.key === "t" || e.key === "T") {
      e.preventDefault();
      if (state.wake) { disableVoice(); toast("Microphone OFF — press T to re-enable"); }
      else enableVoice().then((ok) => { if (ok) toast("Microphone ON — listening"); });
    }
  });
  document.querySelectorAll("[data-refresh]").forEach((b) =>
    b.onclick = () => ({ weather: refreshWeather, news: refreshNews, stats: refreshStats }[b.dataset.refresh] || refreshStats)());

  // Keep the AudioContext alive across the autoplay policy.
  document.addEventListener("pointerdown", () => { if (voice.ctx && voice.ctx.state === "suspended") voice.ctx.resume(); });

  // Auto-resume clap-to-wake if it was enabled before (needs a prior mic grant).
  if (store.get("wake", false)) enableVoice().then((ok) => { if (!ok) armVoiceGesture(); });

  // PWA: register the service worker so Jackie installs as a phone app
  // ("Add to Home screen"). Needs a secure context (https or localhost).
  if ("serviceWorker" in navigator && (location.protocol === "https:"
      || ["127.0.0.1", "localhost"].includes(location.hostname))) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }

  // Greet + load panels once we know whether the backend is up (the source of
  // truth for tasks, notifications and the news proxy).
  detectBackend().then(() => { greeting(); loadTasks(); refreshNews(); pollNotes(); });
  setInterval(async () => { await detectBackend(); loadTasks(); pollNotes(); }, 15000);
  setInterval(refreshNews, 15 * 60 * 1000);
}
init();
