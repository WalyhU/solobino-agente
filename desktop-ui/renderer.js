const { ipcRenderer } = require('electron');

// ─────────────────────────────────────────────────────────────────────────
//  Sprites — el mapeo remapea las carpetas (sus nombres engañan).
//  blink/ = idle feliz · idle/ = durmiendo · react5/6 = alerta/escuchando · etc.
// ─────────────────────────────────────────────────────────────────────────
const SPRITE_ROOT = "assets/mascot/";

const SPRITES = {
  idle:   ["blink/blink1.png","blink/blink2.png","blink/blink3.png","blink/blink4.png","blink/blink5.png"],
  sleep:  ["idle/idle1.png","idle/idle2.png","idle/idle3.png","idle/idle4.png"],
  listen: ["react/react5.png","react/react6.png","react/react5.png","react/react6.png"],
  think:  ["thinking/thinking1.png","thinking/thinking2.png","thinking/thinking3.png","thinking/thinking4.png"],
  talk:   ["react/react1.png","react/react2.png","react/react3.png","react/react4.png"],
  react:  ["react/react5.png","react/react6.png","thinking/thinking4.png","react/react4.png"],
  music:  ["music/music1.png","music/music2.png","music/music3.png","music/music4.png","music/music5.png"],
  dance:  ["dance/dance1.png","dance/dance2.png"],
  error:  ["cry/cry1.png","cry/cry2.png","cry/cry3.png","cry/cry4.png"],
};

const FPS = {
  idle: 2, sleep: 1, listen: 6, think: 1.4, talk: 8,
  react: 4, music: 5, dance: 8, error: 2,
};

// Precarga para transiciones suaves.
Object.values(SPRITES).flat().forEach((src) => { const i = new Image(); i.src = SPRITE_ROOT + src; });

// ─────────────────────────────────────────────────────────────────────────
//  Controlador de la mascota (ciclo de frames)
// ─────────────────────────────────────────────────────────────────────────
const mascotEl = document.getElementById("mascot");
const mascotImg = document.getElementById("mascot-img");
let mascotTimer = null;

function setMascot(state) {
  const frames = SPRITES[state] || SPRITES.idle;
  const fps = FPS[state] || 3;
  let frame = 0;
  if (mascotTimer) clearInterval(mascotTimer);
  mascotImg.src = SPRITE_ROOT + frames[0];
  mascotEl.classList.toggle("dancing", state === "dance" || state === "music");
  if (frames.length > 1) {
    mascotTimer = setInterval(() => {
      frame = (frame + 1) % frames.length;
      mascotImg.src = SPRITE_ROOT + frames[frame];
    }, 1000 / fps);
  }
}

// ─────────────────────────────────────────────────────────────────────────
//  Moods + contenido por estado (porte de desktop.jsx STATE_CONTENT)
// ─────────────────────────────────────────────────────────────────────────
const MOODS = {
  feliz:    { color: "var(--blush-soft)", glyph: "♥", label: "feliz" },
  curiosa:  { color: "var(--gold-soft)",  glyph: "✦", label: "curiosa" },
  pensando: { color: "var(--cloud-2)",    glyph: "…", label: "pensando" },
  triste:   { color: "var(--cloud-2)",    glyph: "ᴗ", label: "confundida" },
  fiesta:   { color: "var(--lav)",        glyph: "✸", label: "fiesta" },
};

const STATE_CONTENT = {
  sleep: { mascot: "sleep", showBubble: false },
  wake: {
    mascot: "idle",
    bubble: {
      status: "HOLA", mood: "feliz",
      text: "¡Hola! Estoy aquí. ¿En qué te ayudo?",
      shortcuts: [
        { kbd: "1", label: "Poner música" },
        { kbd: "2", label: "Resumir email" },
        { kbd: "3", label: "Iniciar timer" },
      ],
    },
  },
  listen: {
    mascot: "listen", showRing: true,
    bubble: {
      status: "ESCUCHANDO", mood: "curiosa", eq: true,
      html: '<span style="color:var(--ink-soft);font-style:italic;">oye lo que estás diciendo<span class="typing-cursor"></span></span>',
    },
  },
  think: {
    mascot: "think",
    bubble: {
      status: "PENSANDO", mood: "pensando",
      html: '<span style="color:var(--ink-soft);">déjame ver<span class="typing-cursor"></span></span>',
    },
  },
  talk: {
    mascot: "talk",
    bubble: { status: "HABLANDO", mood: "feliz", eq: true, typed: "" },
  },
  react: {
    mascot: "react",
    bubble: { status: "¡AHA!", mood: "curiosa", typed: "¡Ya entendí lo que querías decir!" },
  },
  music: {
    mascot: "music",
    bubble: {
      status: "EN SPOTIFY", mood: "fiesta",
      app: { app: "spotify", track: "Lo-fi study beats" },
      html: "<span>Poniendo tu playlist favorita ♪</span>",
      shortcuts: [{ label: "⏯ Pausar" }, { label: "⏭ Siguiente" }, { label: "♥ Me gusta" }],
    },
  },
  dance: {
    mascot: "dance", showSparkles: true,
    bubble: { status: "FIESTA", mood: "fiesta", typed: "¡Terminaste todas tus tareas! Bien hecho ✨" },
  },
  error: {
    mascot: "error",
    bubble: {
      status: "PERDÓN", mood: "triste",
      typed: "Disculpa, no te escuché bien. ¿Me lo repites?",
      shortcuts: [{ label: "Reintentar" }, { label: "Escribir en su lugar" }],
    },
  },
  idle: {
    mascot: "idle",
    bubble: {
      status: "ESPERANDO", mood: "feliz",
      html: "<span>Aquí cuando me necesites ✨</span>",
      shortcuts: [{ label: "Preguntar algo" }, { label: "Tomar nota" }],
    },
  },
};

// ─────────────────────────────────────────────────────────────────────────
//  Render del bocadillo (HUD)
// ─────────────────────────────────────────────────────────────────────────
const hudEl = document.getElementById("hud");
let typingTimer = null;

function buildAppPill(app) {
  const map = {
    spotify: { ico: "♪", label: "Spotify", cls: "spotify" },
    browser: { ico: "◐", label: "Safari", cls: "browser" },
    calendar:{ ico: "□", label: "Calendar", cls: "calendar" },
  };
  const m = map[app.app] || map.spotify;
  return `<div class="app-pill ${m.cls}"><span class="ap-ico">${m.ico}</span>` +
         `<span>${m.label}${app.track ? " · " + app.track : ""}</span></div>`;
}

function buildShortcuts(items) {
  const chips = items.map((it) =>
    `<button class="shortcut">${it.kbd ? `<span class="kbd">${it.kbd}</span>` : ""}${it.label}</button>`
  ).join("");
  return `<div class="shortcuts">${chips}</div>`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Renderiza el bocadillo. Si bubble.typed está definido, escribe el texto letra a letra.
function renderBubble(bubble) {
  if (typingTimer) { clearInterval(typingTimer); typingTimer = null; }
  if (!bubble) { hudEl.classList.add("hidden"); hudEl.innerHTML = ""; return; }

  const mood = MOODS[bubble.mood] || MOODS.feliz;
  const moodChip =
    `<div class="mood-chip" style="background:${mood.color}">` +
    `<span style="color:var(--hot);font-size:10px;">${mood.glyph}</span><span>${mood.label}</span></div>`;

  const eq = bubble.eq ? '<span class="eq"><span></span><span></span><span></span><span></span><span></span></span>' : "";
  const header =
    `<div class="hud-header"><span class="hh-dot"></span><span class="hh-name">SOLOBINO</span>` +
    `${bubble.status ? `<span class="hh-status">${bubble.status}</span>` : ""}${eq}</div>`;

  const appPill = bubble.app ? buildAppPill(bubble.app) : "";
  const shortcuts = bubble.shortcuts ? buildShortcuts(bubble.shortcuts) : "";

  // Cuerpo: typed (máquina de escribir) | html (estático) | vacío
  const bodyId = "hud-body";
  const initialBody = bubble.typed !== undefined ? "" : (bubble.html || "");

  hudEl.innerHTML =
    `<div class="hud-card">${moodChip}${header}${appPill}` +
    `<div class="hud-text" id="${bodyId}">${initialBody}</div>${shortcuts}` +
    `<div class="hud-tail"></div></div>`;
  hudEl.classList.remove("hidden");

  if (bubble.typed !== undefined && bubble.typed.length > 0) {
    typeInto(document.getElementById(bodyId), bubble.typed, bubble.onTyped);
  } else if (bubble.onTyped) {
    bubble.onTyped();
  }
}

// Render minimalista de Markdown a HTML para el bocadillo. Soporta:
// negrita, cursiva, código inline y en bloque, headings, listas, saltos de línea.
// Hecho a mano para no añadir dependencias.
function renderMarkdown(src) {
  if (!src) return "";
  const codeBlocks = [];
  const inlineCodes = [];
  const escHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Extrae bloques ``` y `code` con placeholders para protegerlos del resto del parseo.
  src = src.replace(/```([\s\S]*?)```/g, (_m, code) => {
    codeBlocks.push(code);
    return ` CB${codeBlocks.length - 1} `;
  });
  src = src.replace(/`([^`\n]+)`/g, (_m, code) => {
    inlineCodes.push(code);
    return ` IC${inlineCodes.length - 1} `;
  });

  src = escHtml(src);

  // Headings (mayor a menor para que ### no se trague #).
  src = src.replace(/^###### (.+)$/gm, "<h6>$1</h6>");
  src = src.replace(/^##### (.+)$/gm, "<h5>$1</h5>");
  src = src.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
  src = src.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  src = src.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  src = src.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Bold antes que italic para que ** no se rompa.
  src = src.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  src = src.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  src = src.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");

  // Listas: líneas consecutivas con "- " o "* ".
  src = src.replace(/(?:^|\n)((?:[-*] .+(?:\n|$))+)/g, (_m, block) => {
    const items = block.trim().split(/\n/).map((l) => `<li>${l.replace(/^[-*] /, "")}</li>`).join("");
    return `\n<ul>${items}</ul>`;
  });

  // Bloques (split por línea en blanco). Lo que ya es <h>, <ul>, <pre> se deja tal cual.
  const blocks = src.split(/\n{2,}/).map((b) => {
    const t = b.trim();
    if (!t) return "";
    if (/^<(h\d|ul|ol|pre|blockquote)/.test(t)) return t;
    return `<p>${t.replace(/\n/g, "<br>")}</p>`;
  });
  src = blocks.join("\n");

  // Restaurar código (escapando solo HTML, sin tocar markdown).
  const escCode = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  src = src.replace(/ IC(\d+) /g, (_m, i) => `<code>${escCode(inlineCodes[+i])}</code>`);
  src = src.replace(/ CB(\d+) /g, (_m, i) => {
    // Quita la etiqueta de lenguaje de la primera línea si existe (```js).
    const cleaned = codeBlocks[+i].replace(/^[a-zA-Z0-9_-]*\n/, "");
    return `<pre><code>${escCode(cleaned)}</code></pre>`;
  });

  return src;
}

// Reemplaza el contenido del bocadillo con markdown renderizado.
// Pensado para streaming de deltas y para la respuesta final del agente.
function setBubbleText(text) {
  if (typingTimer) { clearInterval(typingTimer); typingTimer = null; }
  const body = document.getElementById("hud-body");
  if (body) body.innerHTML = renderMarkdown(text);
}

function typeInto(el, text, onDone) {
  let i = 0;
  const cursor = '<span class="typing-cursor"></span>';
  el.innerHTML = cursor;
  typingTimer = setInterval(() => {
    i++;
    el.innerHTML = escapeHtml(text.slice(0, i)) + (i < text.length ? cursor : "");
    if (i >= text.length) {
      clearInterval(typingTimer);
      typingTimer = null;
      if (onDone) onDone();
    }
  }, 28);
}

// ─────────────────────────────────────────────────────────────────────────
//  Máquina de estados
// ─────────────────────────────────────────────────────────────────────────
const soloRoot = document.getElementById("solo-root");
const audioRing = document.getElementById("audio-ring");
const sparkles = document.getElementById("sparkles");

let currentState = "sleep";
let inactivityTimer = null;

function setState(name, opts = {}) {
  const cfg = STATE_CONTENT[name] || STATE_CONTENT.idle;
  const prev = currentState;
  currentState = name;

  // Pop-bounce al despertar desde sleep.
  const entering = prev === "sleep" && name !== "sleep";
  soloRoot.classList.toggle("sleeping", name === "sleep");
  soloRoot.classList.toggle("entering", entering);
  soloRoot.classList.toggle("floating", name !== "sleep" && !entering);
  if (entering) {
    setTimeout(() => {
      soloRoot.classList.remove("entering");
      soloRoot.classList.add("floating");
    }, 1000);
  }
  mascotEl.classList.toggle("mascot-breathe", name !== "sleep" && !entering);

  setMascot(cfg.mascot);
  audioRing.classList.toggle("hidden", !cfg.showRing);
  sparkles.classList.toggle("hidden", !cfg.showSparkles);

  // Bocadillo: permite override de texto (p.ej. respuesta del agente).
  let bubble = cfg.showBubble === false ? null : (cfg.bubble ? { ...cfg.bubble } : null);
  if (bubble && opts.text !== undefined) bubble.typed = opts.text;
  if (bubble && opts.onTyped) bubble.onTyped = opts.onTyped;
  renderBubble(bubble);

  resetInactivity();
}

function resetInactivity() {
  if (inactivityTimer) clearTimeout(inactivityTimer);
  // Tras inactividad en idle, vuelve a dormir.
  if (currentState === "idle") {
    inactivityTimer = setTimeout(() => setState("sleep"), 25000);
  }
}

// Tras terminar de "hablar", deja la respuesta visible INDEFINIDAMENTE.
// La escucha continua se reanuda y el wake word (o un click) dispara el siguiente
// turno. NO programamos auto-sleep: el usuario decide cuándo cerrar el contexto.
function restAfterTalk() {
  setMascot("idle");
  mascotEl.classList.add("mascot-breathe");
  const eq = hudEl.querySelector(".eq");
  if (eq) eq.remove();
  const status = hudEl.querySelector(".hh-status");
  if (status) status.textContent = "RESPUESTA";
  if (inactivityTimer) { clearTimeout(inactivityTimer); inactivityTimer = null; }
  // Estado lógico "resting": mascota en idle, respuesta en pantalla, escucha activa.
  currentState = "resting";
  startContinuousListening();
}

// ─────────────────────────────────────────────────────────────────────────
//  WebSocket con el backend
// ─────────────────────────────────────────────────────────────────────────
const wakePill = document.getElementById("wake-pill");
const wakePillText = document.getElementById("wake-pill-text");
let ws = null;
// Blob de comando pendiente cuando el WS estaba cerrado al terminar de grabar.
// Se reenvía en el próximo ws.onopen para no perder la orden del usuario.
let pendingCommandBlob = null;

function setWakePill(connected) {
  wakePill.classList.toggle("paused", !connected);
  wakePillText.innerText = connected ? 'ESCUCHANDO "SOLOBINO"' : "DESCONECTADO";
}

function connectWebSocket() {
  ws = new WebSocket("ws://127.0.0.1:8000/ws");

  ws.onopen = () => {
    setWakePill(true);
    if (pendingCommandBlob) {
      // Reenviar la orden que quedó en el aire por una caída momentánea del WS.
      ws.send(pendingCommandBlob);
      pendingCommandBlob = null;
      // No reanudes wake-listening: estamos esperando la respuesta del agente.
    } else {
      startContinuousListening();
    }
  };

  ws.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }

    if (data.type === "transcription") {
      console.log("[Solobino] escuchado:", data.text);
      streamingBuf = "";
      setState("think");
    } else if (data.type === "agent_delta") {
      // Trozo incremental: TTFT bajo. Cambia a talk en el primer delta y va
      // renderizando texto sin esperar al final.
      clearWatchdog();
      streamingBuf += data.text || "";
      if (currentState !== "talk") setState("talk", { text: "" });
      setBubbleText(streamingBuf);
    } else if (data.type === "agent_response") {
      // Texto final. Renderiza markdown directamente (no typewriter para que negrita,
      // listas, código se vean correctos en lugar de letra-a-letra escapado).
      clearWatchdog();
      const finalText = (data.text && data.text.length >= streamingBuf.length) ? data.text : streamingBuf;
      streamingBuf = "";
      if (currentState !== "talk") setState("talk", { text: "" });
      setBubbleText(finalText);
      restAfterTalk();
    } else if (data.type === "wake_word_detected") {
      activate();
    }
  };

  ws.onclose = () => {
    setWakePill(false);
    stopContinuousListening();
    setTimeout(connectWebSocket, 3000);
  };
}

// ─────────────────────────────────────────────────────────────────────────
//  Activación (wake word o click) → wake → listen → grabar comando
// ─────────────────────────────────────────────────────────────────────────
let responseWatchdog = null;
function clearWatchdog() {
  if (responseWatchdog) { clearTimeout(responseWatchdog); responseWatchdog = null; }
}

function activate() {
  // Bloquea wake mientras el agente está generando (talk con streaming activo, think,
  // listen, wake). Permite interrumpir cuando ya descansamos con la respuesta visible (resting).
  if (
    isRecording ||
    currentState === "listen" ||
    currentState === "think" ||
    currentState === "talk" ||
    currentState === "wake"
  ) return;
  stopContinuousListening();
  streamingBuf = "";
  setState("wake");
  // Graba el comando de inmediato: la orden suele seguir a "solobino" al instante.
  startCommandRecording();
  setTimeout(() => { if (isRecording) setState("listen"); }, 900);

  // Watchdog: si no hay respuesta del agente, no te quedes colgado en listen/think.
  clearWatchdog();
  responseWatchdog = setTimeout(() => {
    if (currentState === "listen" || currentState === "think") {
      setState("error");
      // Tras el error, vuelve a idle y reanuda wake-listening.
      setTimeout(() => {
        setState("idle");
        startContinuousListening();
      }, 2500);
    }
  }, COMMAND_MAX_MS + 15000);
}

// ─────────────────────────────────────────────────────────────────────────
//  Audio: grabación del comando (webm completo) + escucha continua wake word
// ─────────────────────────────────────────────────────────────────────────
let mediaRecorder = null;
let isRecording = false;
let audioChunks = [];
// Cap duro del comando. La detección de fin-de-habla (watchSilence) cierra antes
// cuando el usuario calla, así que esto es solo el techo.
const COMMAND_MAX_MS = 20000;
// Opus 24kbps: suficiente para STT y reduce ~3x el ancho de banda WS frente al default.
const REC_OPTS = { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 24000 };
// Buffer de texto en streaming del agente (deltas).
let streamingBuf = "";

async function startCommandRecording() {
  if (isRecording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const opts = MediaRecorder.isTypeSupported(REC_OPTS.mimeType) ? REC_OPTS : { mimeType: "audio/webm" };
    mediaRecorder = new MediaRecorder(stream, opts);
    audioChunks = [];

    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = () => {
      const blob = new Blob(audioChunks, { type: "audio/webm" });
      if (blob.size > 0) {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(blob);
        } else {
          pendingCommandBlob = blob;
        }
      }
      stream.getTracks().forEach((t) => t.stop());
      isRecording = false;
    };

    mediaRecorder.start();
    isRecording = true;
    // Fin-de-habla: corta cuando hay 600ms de silencio tras hablar.
    watchSilence(stream, () => {
      if (isRecording && mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
      }
    });
    // Cap duro por si nunca se detecta silencio.
    setTimeout(() => { if (isRecording) mediaRecorder.stop(); }, COMMAND_MAX_MS);
  } catch (err) {
    console.error("Error micrófono:", err);
    setState("error");
  }
}

// Vigila el nivel del micrófono y dispara onSilence cuando hay un periodo de silencio
// suficiente DESPUÉS de detectar voz. Diseñado para tolerar pausas largas dentro de
// la frase: solo corta cuando el usuario claramente terminó.
function watchSilence(stream, onSilence) {
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  const src = ac.createMediaStreamSource(stream);
  const an = ac.createAnalyser();
  an.fftSize = 1024;
  src.connect(an);
  const buf = new Float32Array(an.fftSize);
  const startedAt = performance.now();
  // Umbrales más sensibles: capta voz baja sin cortar a media frase.
  const SPEECH_RMS = 0.012;          // mínimo para contar como "habla"
  const SILENCE_RMS = 0.008;         // por debajo de esto = silencio real
  const MIN_SPEECH_MS = 200;         // necesitamos al menos esto antes de poder cerrar
  const SILENCE_TO_STOP_MS = 1500;   // 1.5 s de silencio tras hablar = fin
  // Espera grande antes de exigir voz: si el usuario tarda en empezar, no cerramos.
  const NO_SPEECH_TIMEOUT_MS = 8000;
  let lastT = startedAt;
  let silentMs = 0;
  let spokeMs = 0;
  let fired = false;
  const tick = () => {
    if (fired) { try { ac.close(); } catch {} return; }
    if (!isRecording) { try { ac.close(); } catch {} return; }
    an.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();
    const dt = now - lastT;
    lastT = now;
    if (rms >= SPEECH_RMS) {
      spokeMs += dt;
      silentMs = 0;
    } else if (rms < SILENCE_RMS) {
      silentMs += dt;
    }
    // Caso A: ya habló y luego se quedó callado el tiempo suficiente.
    if (spokeMs >= MIN_SPEECH_MS && silentMs >= SILENCE_TO_STOP_MS) {
      fired = true;
      try { ac.close(); } catch {}
      onSilence();
      return;
    }
    // Caso B: nunca habló y pasó mucho tiempo: tampoco te quedes grabando aire.
    if (spokeMs < MIN_SPEECH_MS && (now - startedAt) >= NO_SPEECH_TIMEOUT_MS) {
      fired = true;
      try { ac.close(); } catch {}
      onSilence();
      return;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function stopCommandRecording() {
  if (isRecording && mediaRecorder) mediaRecorder.stop();
}

// Escucha continua: graba SEGMENTOS webm completos de ~3s para el wake-word.
const WAKE_SEGMENT_MS = 3000;
let continuousStream = null;
let continuousActive = false;
let segmentRecorder = null;

async function startContinuousListening() {
  if (continuousActive || isRecording) return;
  try {
    continuousStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    continuousActive = true;
    recordWakeSegment();
  } catch (err) {
    console.error("Escucha continua:", err);
  }
}

function recordWakeSegment() {
  if (!continuousActive || !continuousStream || isRecording) return;
  const chunks = [];
  const opts = MediaRecorder.isTypeSupported(REC_OPTS.mimeType) ? REC_OPTS : { mimeType: "audio/webm" };
  segmentRecorder = new MediaRecorder(continuousStream, opts);
  segmentRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  segmentRecorder.onstop = () => {
    const blob = new Blob(chunks, { type: "audio/webm" });
    if (blob.size > 0 && ws && ws.readyState === WebSocket.OPEN && !isRecording) {
      const reader = new FileReader();
      reader.readAsDataURL(blob);
      reader.onloadend = () => {
        const base64data = reader.result.split(",")[1];
        ws.send(JSON.stringify({ type: "wake_word_check", audio: base64data }));
      };
    }
    if (continuousActive) setTimeout(recordWakeSegment, 200);
  };
  segmentRecorder.start();
  setTimeout(() => {
    if (segmentRecorder && segmentRecorder.state === "recording") segmentRecorder.stop();
  }, WAKE_SEGMENT_MS);
}

function stopContinuousListening() {
  continuousActive = false;
  if (segmentRecorder && segmentRecorder.state === "recording") segmentRecorder.stop();
  segmentRecorder = null;
  if (continuousStream) {
    continuousStream.getTracks().forEach((t) => t.stop());
    continuousStream = null;
  }
}

// ─────────────────────────────────────────────────────────────────────────
//  Interacción: click para activar, drag para mover, click-through
// ─────────────────────────────────────────────────────────────────────────
let isDragging = false;
let moved = false;
let offsetX = 0, offsetY = 0;

const dragHandle = document.getElementById("drag-handle");

function startDrag(e) {
  isDragging = true;
  moved = false;
  const rect = soloRoot.getBoundingClientRect();
  offsetX = e.clientX - rect.left;
  offsetY = e.clientY - rect.top;
  e.preventDefault();
}
dragHandle.addEventListener("mousedown", startDrag);

document.addEventListener("mousemove", (e) => {
  if (!isDragging) return;
  moved = true;
  let x = e.clientX - offsetX;
  let y = e.clientY - offsetY;
  x = Math.max(0, Math.min(x, window.innerWidth - soloRoot.offsetWidth));
  y = Math.max(0, Math.min(y, window.innerHeight - soloRoot.offsetHeight));
  soloRoot.style.right = "auto";
  soloRoot.style.bottom = "auto";
  soloRoot.style.left = `${x}px`;
  soloRoot.style.top = `${y}px`;
});

document.addEventListener("mouseup", () => { isDragging = false; });

// Click en la mascota: activa (si dormido/idle) o detiene grabación (si escuchando).
mascotEl.addEventListener("click", () => {
  if (moved) return;
  if (isRecording) { stopCommandRecording(); return; }
  if (currentState === "sleep" || currentState === "idle" || currentState === "resting") activate();
});

// Click-through: solo el overlay y la wake-pill capturan el mouse.
[soloRoot, wakePill].forEach((el) => {
  el.addEventListener("mouseenter", () => ipcRenderer.send("set-ignore-mouse-events", false));
  el.addEventListener("mouseleave", () => ipcRenderer.send("set-ignore-mouse-events", true, { forward: true }));
});

// ─────────────────────────────────────────────────────────────────────────
//  Arranque
// ─────────────────────────────────────────────────────────────────────────
setState("sleep");
connectWebSocket();
