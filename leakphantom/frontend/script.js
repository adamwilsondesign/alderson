// ═══════════════════════════════════════════════════════════════
// LEAKPHANTOM v2.3.1 — Terminal UI, Graph Renderer, Audio Engine
// ═══════════════════════════════════════════════════════════════

(() => {
"use strict";

// ── Protocol Colors ──
const COLORS = {
  wifi: "#00ff41", ble: "#00d4ff", zigbee: "#ff6600",
  thread: "#a855f7", matter: "#f59e0b", zwave: "#ef4444",
  correlation: "#ff00ff", unknown: "#666666", white: "#ffffff",
};

const NODE_CHARS = {
  device: "●", ssid: "◆", service: "■", cluster: "⬡", gateway: "▲",
};

const PARTICLE_CHARS = ["►", "▼", "◄", "▲", "◈", "◉", "⦿"];

// ── State ──
let ws = null;
let state = {
  nodes: [], edges: [], particles: [], log: [], stats: {},
  tick: 0, connected: false, demoMode: true, capturing: false,
};
let selectedNode = null;
let hoveredNode = null;
let creatorMode = false;
let creatorFirst = null;
let soundEnabled = true;
let focusMode = false;
let totalLeaksEver = 0;
let lastFrameTime = 0;
let fpsValues = [];

// ── Canvas Setup ──
const graphCanvas = document.getElementById("graph-canvas");
const ctx = graphCanvas.getContext("2d");
const matrixCanvas = document.getElementById("matrix-rain");
const mctx = matrixCanvas.getContext("2d");

function resizeCanvases() {
  const panel = document.getElementById("graph-panel");
  graphCanvas.width = panel.clientWidth;
  graphCanvas.height = panel.clientHeight;
  matrixCanvas.width = window.innerWidth;
  matrixCanvas.height = window.innerHeight;
}
window.addEventListener("resize", resizeCanvases);
resizeCanvases();

// ═══════════════════════════════════════════════════════════════
// WEBSOCKET
// ═══════════════════════════════════════════════════════════════
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    state.connected = true;
    document.getElementById("status-text").textContent = "CONNECTED";
    document.getElementById("status-text").classList.add("glow");
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      handleMessage(msg);
    } catch (e) { /* skip malformed */ }
  };

  ws.onclose = () => {
    state.connected = false;
    document.getElementById("status-text").textContent = "DISCONNECTED";
    document.getElementById("status-text").classList.remove("glow");
    setTimeout(connectWS, 2000);
  };

  ws.onerror = () => ws.close();
}

function sendWS(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function handleMessage(msg) {
  if (msg.type === "init") {
    state.demoMode = msg.demo_mode;
    updateModeBadge();
    showWizard();
  } else if (msg.type === "frame") {
    const prevLeaks = state.stats.total_leaks || 0;
    state.nodes = msg.nodes || [];
    state.edges = msg.edges || [];
    state.particles = msg.particles || [];
    state.log = msg.log || [];
    state.stats = msg.stats || {};
    state.tick = msg.tick || 0;

    const newLeaks = (state.stats.total_leaks || 0) - prevLeaks;
    if (newLeaks > 0) {
      for (let i = 0; i < Math.min(newLeaks, 3); i++) {
        playSound("leak_blip");
      }
      totalLeaksEver = state.stats.total_leaks || 0;
      checkEasterEggs();
    }

    updateStats();
    updateLog();
  } else if (msg.type === "node_detail") {
    showNodeDetail(msg.data);
  }
}

// ═══════════════════════════════════════════════════════════════
// GRAPH RENDERER
// ═══════════════════════════════════════════════════════════════
const CELL_W = 9;
const CELL_H = 18;

function renderGraph() {
  const now = performance.now();
  const dt = now - lastFrameTime;
  lastFrameTime = now;
  fpsValues.push(1000 / dt);
  if (fpsValues.length > 30) fpsValues.shift();

  ctx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);
  ctx.font = "14px 'VT323', monospace";
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";

  const W = graphCanvas.width;
  const H = graphCanvas.height;
  const scaleX = W / 160;
  const scaleY = H / 50;

  // ── Draw edges ──
  for (const edge of state.edges) {
    const src = state.nodes.find(n => n.id === edge.source);
    const tgt = state.nodes.find(n => n.id === edge.target);
    if (!src || !tgt) continue;

    const x1 = src.x * scaleX;
    const y1 = src.y * scaleY;
    const x2 = tgt.x * scaleX;
    const y2 = tgt.y * scaleY;

    ctx.strokeStyle = edge.flash ? "#ffffff" : edge.color;
    ctx.globalAlpha = edge.flash ? 1 : 0.3 + edge.weight * 0.15;
    ctx.lineWidth = edge.type === "correlation" ? 2 : 1;

    if (edge.flash) {
      ctx.shadowColor = "#ffffff";
      ctx.shadowBlur = 15;
    }

    if (edge.animated && !edge.flash) {
      ctx.setLineDash([4, 6]);
      ctx.lineDashOffset = -(state.tick * 0.5);
    } else {
      ctx.setLineDash([]);
    }

    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    ctx.shadowBlur = 0;
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  // ── Draw particles ──
  for (const p of state.particles) {
    const x = p.x * scaleX;
    const y = p.y * scaleY;
    const ch = PARTICLE_CHARS[Math.floor(p.p * PARTICLE_CHARS.length) % PARTICLE_CHARS.length];

    ctx.fillStyle = p.color;
    ctx.globalAlpha = 1 - p.p * 0.5;
    ctx.font = "12px 'VT323', monospace";
    ctx.fillText(ch, x, y);

    if (p.label && p.p > 0.1 && p.p < 0.8) {
      ctx.globalAlpha = 0.6;
      ctx.font = "10px 'VT323', monospace";
      ctx.fillText(p.label, x, y - 10);
    }
    ctx.globalAlpha = 1;
  }

  // ── Draw nodes ──
  for (const node of state.nodes) {
    const x = node.x * scaleX;
    const y = node.y * scaleY;
    const ch = NODE_CHARS[node.type] || "●";
    const isHovered = node.hover || (hoveredNode && hoveredNode.id === node.id);
    const isSelected = selectedNode && selectedNode.id === node.id;

    const pulse = Math.sin(node.pulse_phase + state.tick * 0.05) * 0.3 + 0.7;
    const size = 14 + node.size * 2;

    // Dim non-focused nodes in focus mode
    if (focusMode && selectedNode && !isSelected) {
      const connected = state.edges.some(e =>
        (e.source === selectedNode.id && e.target === node.id) ||
        (e.target === selectedNode.id && e.source === node.id)
      );
      if (!connected) {
        ctx.globalAlpha = 0.15;
      }
    }

    // Cluster background glow
    if (node.cluster_id && node.confidence > 0.5) {
      ctx.fillStyle = node.color;
      ctx.globalAlpha = 0.08 * pulse;
      ctx.beginPath();
      ctx.arc(x, y, 20 + node.confidence * 15, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    // Node glow
    if (isHovered || isSelected) {
      ctx.shadowColor = node.color;
      ctx.shadowBlur = 20;
      ctx.strokeStyle = node.color;
      ctx.lineWidth = 1;
      ctx.strokeRect(x - 20, y - 10, 40, 20);
    }

    // Node character
    ctx.fillStyle = node.color;
    ctx.globalAlpha = pulse;
    ctx.font = `${size}px 'VT323', monospace`;
    ctx.fillText(ch, x, y);

    // Node label
    ctx.font = "12px 'VT323', monospace";
    ctx.globalAlpha = isHovered ? 1 : 0.7;
    ctx.fillText(node.label, x, y + size / 2 + 8);

    // Protocol tag
    if (isHovered) {
      ctx.font = "10px 'VT323', monospace";
      ctx.globalAlpha = 0.5;
      ctx.fillText(`[${node.protocol.toUpperCase()}]`, x, y - size / 2 - 6);
    }

    // Update tooltip position every frame for hovered node
    if (isHovered && hoveredNode) {
      updateTooltipPosition(node);
    }

    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }

  // ── Creator mode crosshair ──
  if (creatorMode && creatorFirst) {
    const src = state.nodes.find(n => n.id === creatorFirst);
    if (src) {
      ctx.strokeStyle = "#ff00ff";
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(src.x * scaleX, src.y * scaleY);
      ctx.lineTo(mouseX, mouseY);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // FPS counter
  const avgFps = fpsValues.reduce((a, b) => a + b, 0) / fpsValues.length;
  document.getElementById("fps-counter").textContent = `${Math.round(avgFps)} fps`;

  requestAnimationFrame(renderGraph);
}

// ═══════════════════════════════════════════════════════════════
// MATRIX RAIN
// ═══════════════════════════════════════════════════════════════
const matrixColumns = [];
const matrixChars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$%^&*()ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽﾀﾇﾍ";
let matrixIntensity = 1;

function initMatrixRain() {
  const cols = Math.floor(matrixCanvas.width / 14);
  for (let i = 0; i < cols; i++) {
    matrixColumns[i] = Math.random() * matrixCanvas.height;
  }
}

function renderMatrixRain() {
  mctx.fillStyle = "rgba(0, 0, 0, 0.05)";
  mctx.fillRect(0, 0, matrixCanvas.width, matrixCanvas.height);

  mctx.font = "14px 'VT323', monospace";

  for (let i = 0; i < matrixColumns.length; i++) {
    let ch;
    if (state.log.length > 0 && Math.random() < 0.3) {
      const logLine = state.log[Math.floor(Math.random() * state.log.length)];
      const text = logLine.text || "";
      ch = text[Math.floor(Math.random() * text.length)] || matrixChars[Math.floor(Math.random() * matrixChars.length)];
    } else {
      ch = matrixChars[Math.floor(Math.random() * matrixChars.length)];
    }

    const green = Math.floor(180 + Math.random() * 75);
    mctx.fillStyle = `rgba(0, ${green}, 65, ${0.4 * matrixIntensity})`;
    mctx.fillText(ch, i * 14, matrixColumns[i]);

    if (matrixColumns[i] > matrixCanvas.height && Math.random() > 0.975) {
      matrixColumns[i] = 0;
    }
    matrixColumns[i] += 14;
  }
}

setInterval(renderMatrixRain, 50);

// ═══════════════════════════════════════════════════════════════
// WEB AUDIO ENGINE
// ═══════════════════════════════════════════════════════════════
let audioCtx = null;
let masterGain = null;
let ambientOsc = null;
let ambientLfo = null;
let heartbeatInterval = null;

function initAudio() {
  if (audioCtx) return;
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    masterGain = audioCtx.createGain();
    masterGain.gain.value = 0.5;
    masterGain.connect(audioCtx.destination);
    startAmbientHum();
    startHeartbeat();
  } catch (e) {
    console.warn("Web Audio not available:", e);
  }
}

function startAmbientHum() {
  if (!audioCtx) return;
  ambientOsc = audioCtx.createOscillator();
  ambientOsc.type = "sawtooth";
  ambientOsc.frequency.value = 55;

  const filter = audioCtx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 120;
  filter.Q.value = 2;

  const gain = audioCtx.createGain();
  gain.gain.value = 0.015;

  ambientLfo = audioCtx.createOscillator();
  ambientLfo.frequency.value = 0.1;
  const lfoGain = audioCtx.createGain();
  lfoGain.gain.value = 5;
  ambientLfo.connect(lfoGain);
  lfoGain.connect(ambientOsc.frequency);

  ambientOsc.connect(filter);
  filter.connect(gain);
  gain.connect(masterGain);

  ambientOsc.start();
  ambientLfo.start();
}

function startHeartbeat() {
  heartbeatInterval = setInterval(() => {
    if (!audioCtx || !soundEnabled) return;
    playHeartbeat();
  }, 1500);
}

function playHeartbeat() {
  if (!audioCtx || !soundEnabled) return;
  const osc = audioCtx.createOscillator();
  osc.type = "sine";
  osc.frequency.value = 40;
  const gain = audioCtx.createGain();
  const now = audioCtx.currentTime;
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.08, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
  const filter = audioCtx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 80;
  filter.Q.value = 5;
  osc.connect(filter);
  filter.connect(gain);
  gain.connect(masterGain);
  osc.start(now);
  osc.stop(now + 0.5);
}

function playSound(name, options = {}) {
  if (!audioCtx || !soundEnabled) return;
  const now = audioCtx.currentTime;

  if (name === "leak_blip") {
    const freqMap = { wifi: 440, ble: 587, zigbee: 659, thread: 523, matter: 698, zwave: 392 };
    const freq = freqMap[options.protocol] || 440;
    const osc = audioCtx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = freq;
    const gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.04, now + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
    const panner = audioCtx.createStereoPanner();
    panner.pan.value = (Math.random() - 0.5) * 1.5;
    osc.connect(gain);
    gain.connect(panner);
    panner.connect(masterGain);
    osc.start(now);
    osc.stop(now + 0.2);
  }
  else if (name === "click") {
    const osc = audioCtx.createOscillator();
    osc.type = "square";
    osc.frequency.value = 800;
    const gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0.03, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.03);
    osc.connect(gain);
    gain.connect(masterGain);
    osc.start(now);
    osc.stop(now + 0.04);
  }
  else if (name === "correlation_lock") {
    const notes = [440, 554, 659, 880];
    notes.forEach((freq, i) => {
      const osc = audioCtx.createOscillator();
      osc.type = "triangle";
      osc.frequency.value = freq;
      const gain = audioCtx.createGain();
      const t = now + i * 0.08;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.05, t + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
      osc.connect(gain);
      gain.connect(masterGain);
      osc.start(t);
      osc.stop(t + 0.2);
    });
  }
  else if (name === "correlation_thunk") {
    const osc = audioCtx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 80;
    const gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.1, now + 0.001);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
    osc.connect(gain);
    gain.connect(masterGain);
    osc.start(now);
    osc.stop(now + 0.7);
    const bufferSize = audioCtx.sampleRate * 0.1;
    const buffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) data[i] = (Math.random() * 2 - 1) * 0.5;
    const noise = audioCtx.createBufferSource();
    noise.buffer = buffer;
    const noiseGain = audioCtx.createGain();
    noiseGain.gain.setValueAtTime(0.06, now);
    noiseGain.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
    const hpf = audioCtx.createBiquadFilter();
    hpf.type = "highpass";
    hpf.frequency.value = 4000;
    noise.connect(hpf);
    hpf.connect(noiseGain);
    noiseGain.connect(masterGain);
    noise.start(now);
    noise.stop(now + 0.15);
  }
  else if (name === "glitch") {
    for (let i = 0; i < 6; i++) {
      const osc = audioCtx.createOscillator();
      osc.type = "square";
      osc.frequency.value = 100 + Math.random() * 3000;
      const gain = audioCtx.createGain();
      const t = now + i * 0.02;
      gain.gain.setValueAtTime(0.04, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.02);
      osc.connect(gain);
      gain.connect(masterGain);
      osc.start(t);
      osc.stop(t + 0.025);
    }
  }
  else if (name === "sub_bass") {
    const osc = audioCtx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 30;
    const gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.15, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 1.5);
    osc.connect(gain);
    gain.connect(masterGain);
    osc.start(now);
    osc.stop(now + 2);
  }
  else if (name === "konami") {
    const notes = [262, 330, 392, 523, 659, 784, 1047];
    notes.forEach((freq, i) => {
      const osc = audioCtx.createOscillator();
      osc.type = "square";
      osc.frequency.value = freq;
      const gain = audioCtx.createGain();
      const filter = audioCtx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = 3000;
      const t = now + i * 0.06;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.04, t + 0.002);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.12);
      osc.connect(filter);
      filter.connect(gain);
      gain.connect(masterGain);
      osc.start(t);
      osc.stop(t + 0.15);
    });
  }
}

// ═══════════════════════════════════════════════════════════════
// UI UPDATES
// ═══════════════════════════════════════════════════════════════
function updateStats() {
  const s = state.stats;
  document.getElementById("val-leaks").textContent = s.total_leaks || 0;
  document.getElementById("val-devices").textContent = s.unique_devices || 0;
  document.getElementById("val-clusters").textContent = s.clusters || 0;
  document.getElementById("val-corr").textContent = s.correlations || 0;
  document.getElementById("val-wifi").textContent = s.proto_wifi || 0;
  document.getElementById("val-ble").textContent = s.proto_ble || 0;
  document.getElementById("val-zigbee").textContent = s.proto_zigbee || 0;
  document.getElementById("val-thread").textContent = s.proto_thread || 0;
  document.getElementById("val-matter").textContent = s.proto_matter || 0;
  document.getElementById("val-zwave").textContent = s.proto_zwave || 0;

  const uptime = Math.floor(s.uptime || 0);
  const m = Math.floor(uptime / 60);
  const sec = uptime % 60;
  document.getElementById("val-uptime").textContent = m > 0 ? `${m}m${sec}s` : `${sec}s`;
}

function updateLog() {
  const logEl = document.getElementById("log-content");
  const logs = state.log;

  if (logEl.children.length === logs.length) return;

  logEl.innerHTML = "";
  for (const line of logs) {
    const div = document.createElement("div");
    div.className = "log-line";
    const timeStr = new Date(line.ts * 1000).toLocaleTimeString("en-US", { hour12: false });
    div.innerHTML = `<span class="log-time">${timeStr}</span><span style="color:${line.color}">${escapeHtml(line.text)}</span>`;
    logEl.appendChild(div);
  }
  logEl.scrollTop = logEl.scrollHeight;
}

function updateModeBadge() {
  const badge = document.getElementById("mode-badge");
  if (state.demoMode) {
    badge.textContent = "DEMO";
    badge.className = "badge badge-demo";
  } else {
    badge.textContent = "LIVE";
    badge.className = "badge badge-live";
  }
}

function showNodeDetail(data) {
  if (!data) return;
  const panel = document.getElementById("detail-panel");
  const content = document.getElementById("detail-content");
  const title = document.getElementById("detail-title");

  panel.classList.remove("hidden");
  const protoColor = COLORS[data.node.protocol] || COLORS.unknown;
  title.textContent = `${data.node.label} [${data.node.protocol.toUpperCase()}]`;

  // Full address (strip dev_ / val_ prefix)
  const addr = data.node.id.replace(/^(dev_|val_)/, "");

  let html = `<div style="display:flex;gap:24px;flex-wrap:wrap">`;

  // Left column: identity
  html += `<div style="min-width:200px">`;
  html += `<div style="color:var(--green-dim);margin-bottom:4px">─── Identity ───</div>`;
  html += row("Address", addr);
  html += row("Protocol", `<span style="color:${protoColor}">${data.node.protocol.toUpperCase()}</span>`);
  html += row("Type", data.node.type);
  if (data.vendor) html += row("Vendor", data.vendor);
  if (data.node.cluster_id) {
    html += row("Cluster", `<span style="color:var(--magenta)">${(data.node.confidence * 100).toFixed(0)}% confidence</span>`);
  }
  if (data.rssi_min != null) {
    html += row("RSSI", `${data.rssi_min} to ${data.rssi_max} dBm`);
  }
  if (data.first_seen) {
    html += row("First seen", new Date(data.first_seen * 1000).toLocaleTimeString("en-US", { hour12: false }));
  }
  if (data.last_seen) {
    html += row("Last seen", new Date(data.last_seen * 1000).toLocaleTimeString("en-US", { hour12: false }));
  }
  html += row("Events", `${data.events.length}`);
  html += `</div>`;

  // Middle column: leaked values
  if (data.unique_leaks && data.unique_leaks.length > 0) {
    html += `<div style="min-width:200px">`;
    html += `<div style="color:var(--green-dim);margin-bottom:4px">─── Leaked Values ───</div>`;
    for (const val of data.unique_leaks.slice(0, 10)) {
      html += `<div style="color:${protoColor};font-size:12px">${escapeHtml(val)}</div>`;
    }
    if (data.unique_leaks.length > 10) {
      html += `<div style="color:var(--green-dim);font-size:11px">+${data.unique_leaks.length - 10} more</div>`;
    }
    html += `</div>`;
  }

  // Right column: connected nodes
  if (data.connected && data.connected.length > 0) {
    html += `<div style="min-width:180px">`;
    html += `<div style="color:var(--green-dim);margin-bottom:4px">─── Connected ───</div>`;
    for (const c of data.connected.slice(0, 8)) {
      const cc = COLORS[c.protocol] || COLORS.unknown;
      html += `<div style="font-size:12px"><span style="color:${cc}">${NODE_CHARS[c.type] || "●"}</span> ${escapeHtml(c.label)} <span style="color:var(--green-dim)">${c.protocol}</span></div>`;
    }
    if (data.connected.length > 8) {
      html += `<div style="color:var(--green-dim);font-size:11px">+${data.connected.length - 8} more</div>`;
    }
    html += `</div>`;
  }

  html += `</div>`;

  content.innerHTML = html;
  playSound("click");
}

function row(key, val) {
  return `<div class="detail-row"><div class="detail-key">${key}</div><div class="detail-val">${val}</div></div>`;
}

// ═══════════════════════════════════════════════════════════════
// SETUP WIZARD
// ═══════════════════════════════════════════════════════════════
let wizardStep = 0;
let wizardData = {};

function showWizard() {
  wizardStep = 0;
  // Stop any existing capture on wizard reopen
  fetch("/api/stop", { method: "POST" }).catch(() => {});
  document.getElementById("wizard-overlay").classList.remove("hidden");
  renderWizardStep();
}

function hideWizard() {
  document.getElementById("wizard-overlay").classList.add("hidden");
}

function renderWizardStep() {
  const content = document.getElementById("wizard-content");
  const backBtn = document.getElementById("wizard-back");
  const nextBtn = document.getElementById("wizard-next");

  backBtn.classList.toggle("hidden", wizardStep === 0);

  if (wizardStep === 0) {
    content.innerHTML = `
      <div class="wizard-step">
        <div class="wizard-heading" style="animation: glitch-1 0.3s ease-out">
          ░▒▓ WELCOME TO LEAKPHANTOM v2.3.1 ▓▒░
        </div>
        <div class="wizard-text">
          Multi-Protocol Identity Leakage Capturer<br>
          Passive network reconnaissance and correlation engine.
        </div>
        <div style="border:1px solid var(--red); padding:10px; margin:10px 0; color:var(--red)">
          ⚠ LEGAL DISCLAIMER<br><br>
          <span style="color:var(--green-dim); font-size:12px">
            This tool is for AUTHORIZED security research and educational purposes ONLY.
            Unauthorized monitoring of network traffic may violate local, state, and federal laws
            including the Wiretap Act (18 U.S.C. § 2511) and CFAA (18 U.S.C. § 1030).
            Always obtain proper written authorization before use.
            The developers assume no liability for misuse.
          </span>
        </div>
        <div style="margin-top:12px">
          <label style="cursor:pointer">
            <input type="checkbox" id="legal-accept" onchange="document.getElementById('wizard-next').disabled = !this.checked" />
            I understand and accept responsibility for lawful use only.
          </label>
        </div>
      </div>
    `;
    nextBtn.textContent = "ACCEPT & CONTINUE ►";
    nextBtn.disabled = true;

  } else if (wizardStep === 1) {
    content.innerHTML = `
      <div class="wizard-step">
        <div class="wizard-heading">HARDWARE DETECTION</div>
        <div class="wizard-text">Scanning for capture hardware...</div>
        <div id="hw-results" style="color:var(--green-dim)">
          <div class="hw-item"><span>Scanning...</span><span>⟳</span></div>
        </div>
      </div>
    `;
    nextBtn.textContent = "NEXT ►";
    nextBtn.disabled = true;

    fetch("/api/wizard/detect", { method: "POST" })
      .then(r => r.json())
      .then(data => {
        wizardData.hardware = data;
        const el = document.getElementById("hw-results");
        if (!el) return;
        el.innerHTML = "";

        // Cloud deployment — show friendly message and auto-advance
        if (data.cloud) {
          el.innerHTML = `
            <div style="border:1px solid var(--yellow); padding:12px; margin:8px 0; text-align:center">
              <div style="color:var(--yellow); font-size:16px; margin-bottom:8px">☁ CLOUD DEPLOYMENT DETECTED</div>
              <div style="color:var(--green-dim)">Hardware capture is not available on cloud servers.<br>Demo mode will provide realistic simulated multi-protocol traffic.</div>
            </div>
          `;
          nextBtn.disabled = false;
          // Auto-skip past hardware + thread key steps after short delay
          setTimeout(() => {
            wizardStep = 3; // Jump to Initialize step
            renderWizardStep();
          }, 2500);
          return;
        }

        const items = [
          { label: "WiFi (Monitor Mode)", ok: data.wifi?.available, detail: data.wifi?.monitor_capable?.join(", ") || "None" },
          { label: "Bluetooth (BLE)", ok: data.bluetooth?.available, detail: data.bluetooth?.adapters?.join(", ") || "None" },
          { label: "Serial Ports", ok: data.serial?.available, detail: data.serial?.ports?.map(p => p.port).join(", ") || "None" },
          { label: "airmon-ng", ok: data.tools?.["airmon-ng"], detail: data.tools?.["airmon-ng"] ? "Found" : "Not found" },
          { label: "tshark", ok: data.tools?.tshark, detail: data.tools?.tshark ? "Found" : "Not found" },
          { label: "Scapy", ok: data.tools?.py_scapy, detail: data.tools?.py_scapy ? "Installed" : "Not installed" },
          { label: "Bleak (BLE)", ok: data.tools?.py_bleak, detail: data.tools?.py_bleak ? "Installed" : "Not installed" },
        ];

        for (const item of items) {
          const statusClass = item.ok ? "hw-status-ok" : "hw-status-missing";
          const icon = item.ok ? "✓" : "✗";
          el.innerHTML += `<div class="hw-item"><span>${item.label}</span><span class="${statusClass}">${icon} ${item.detail}</span></div>`;
        }

        if (!items.some(i => i.ok)) {
          el.innerHTML += `<div style="margin-top:10px;color:var(--yellow)">No capture hardware detected. Demo mode will be used.</div>`;
        }
        nextBtn.disabled = false;
      })
      .catch(() => {
        const el = document.getElementById("hw-results");
        if (el) el.innerHTML = `<div style="color:var(--yellow)">Detection skipped. Demo mode will be used.</div>`;
        nextBtn.disabled = false;
      });

  } else if (wizardStep === 2) {
    content.innerHTML = `
      <div class="wizard-step">
        <div class="wizard-heading">THREAD NETWORK KEY (Optional)</div>
        <div class="wizard-text">
          Provide a Thread/OpenThread network master key for 802.15.4 decryption.<br>
          This is optional — skip if you don't have Thread devices.
        </div>
        <div style="margin:12px 0">
          <input type="text" id="thread-key-input" placeholder="32 hex characters (e.g., 00112233445566778899aabbccddeeff)" maxlength="32" />
        </div>
        <button class="wizard-btn" style="font-size:12px" onclick="autoExtractOTBR()">
          ⚡ Auto-Extract from Local OTBR
        </button>
        <div id="thread-key-status" style="margin-top:8px;font-size:12px"></div>
      </div>
    `;
    nextBtn.textContent = "SKIP / NEXT ►";
    nextBtn.disabled = false;

  } else if (wizardStep === 3) {
    content.innerHTML = `
      <div class="wizard-step">
        <div class="wizard-heading">INITIALIZE PROTOCOLS</div>
        <div class="wizard-text">
          Ready to initialize all detected capture protocols.
        </div>
        <div id="init-status" style="margin:12px 0"></div>
        <button class="wizard-btn" id="init-btn" onclick="initializeProtocols()">
          ⚡ INITIALIZE ALL PROTOCOLS
        </button>
      </div>
    `;
    nextBtn.textContent = "NEXT ►";
    nextBtn.disabled = true;

  } else if (wizardStep === 4) {
    content.innerHTML = `
      <div class="wizard-step">
        <div class="wizard-heading">READY TO CAPTURE</div>
        <div class="wizard-text">
          All systems initialized. ${state.demoMode ? "Running in DEMO MODE (no hardware detected)." : "LIVE capture ready."}
        </div>
        <div style="border:1px solid var(--green); padding:10px; margin:12px 0">
          <div style="text-align:center; font-size:16px; letter-spacing:3px">
            ░▒▓ PHANTOM PROTOCOL ARMED ▓▒░
          </div>
        </div>
      </div>
    `;
    nextBtn.textContent = "▶ BEGIN CAPTURING";
    nextBtn.disabled = false;
  }
}

window.autoExtractOTBR = function() {
  const status = document.getElementById("thread-key-status");
  if (status) status.innerHTML = '<span style="color:var(--yellow)">Attempting auto-extract...</span>';

  fetch("/api/wizard/set-thread-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_extract: true }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.status === "ok") {
        if (status) status.innerHTML = `<span style="color:var(--green)">✓ Key extracted: ${data.key}</span>`;
        const input = document.getElementById("thread-key-input");
        if (input) input.value = data.key;
      } else {
        if (status) status.innerHTML = `<span style="color:var(--red)">✗ ${data.message}</span>`;
      }
    })
    .catch(() => {
      if (status) status.innerHTML = '<span style="color:var(--red)">✗ Failed to connect to OTBR</span>';
    });
};

window.initializeProtocols = function() {
  const status = document.getElementById("init-status");
  const btn = document.getElementById("init-btn");
  if (btn) btn.disabled = true;
  if (status) status.innerHTML = '<span style="color:var(--yellow)">Initializing...</span>';

  const keyInput = document.getElementById("thread-key-input");
  const threadKey = keyInput ? keyInput.value.trim() : "";
  if (threadKey) {
    fetch("/api/wizard/set-thread-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: threadKey }),
    }).catch(() => {});
  }

  fetch("/api/wizard/initialize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  })
    .then(r => r.json())
    .then(data => {
      state.demoMode = data.demo_mode;
      updateModeBadge();

      let html = "";
      for (const [proto, info] of Object.entries(data.protocols || {})) {
        const ok = info.status === "ok" || info.status === "active";
        const cls = ok ? "hw-status-ok" : "hw-status-partial";
        const icon = ok ? "✓" : "~";
        html += `<div class="hw-item"><span>${proto}</span><span class="${cls}">${icon} ${info.status}${info.fallback ? " (demo)" : ""}</span></div>`;
      }
      if (status) status.innerHTML = html;
      document.getElementById("wizard-next").disabled = false;
    })
    .catch(() => {
      if (status) status.innerHTML = '<span style="color:var(--yellow)">Using demo mode</span>';
      document.getElementById("wizard-next").disabled = false;
    });
};

document.getElementById("wizard-next").addEventListener("click", () => {
  playSound("click");
  if (wizardStep === 4) {
    hideWizard();
    fetch("/api/wizard/start", { method: "POST" }).then(() => {
      state.capturing = true;
      document.getElementById("status-text").textContent = "CAPTURING";
    });
    return;
  }
  wizardStep++;
  renderWizardStep();
});

document.getElementById("wizard-back").addEventListener("click", () => {
  playSound("click");
  if (wizardStep > 0) {
    wizardStep--;
    renderWizardStep();
  }
});

document.getElementById("btn-wizard").addEventListener("click", () => {
  playSound("click");
  showWizard();
});

document.getElementById("detail-close").addEventListener("click", () => {
  document.getElementById("detail-panel").classList.add("hidden");
  // Unpin selected node
  if (selectedNode) {
    sendWS({ cmd: "unpin_node", node_id: selectedNode.id });
  }
  selectedNode = null;
  focusMode = false;
  document.body.classList.remove("focus-mode");
  playSound("click");
});

// ═══════════════════════════════════════════════════════════════
// MOUSE INTERACTION
// ═══════════════════════════════════════════════════════════════
let mouseX = 0, mouseY = 0;

graphCanvas.addEventListener("mousemove", (e) => {
  const rect = graphCanvas.getBoundingClientRect();
  mouseX = e.clientX - rect.left;
  mouseY = e.clientY - rect.top;

  const scaleX = graphCanvas.width / 160;
  const scaleY = graphCanvas.height / 50;

  // Find nearest node — generous 45px hit radius
  let nearest = null;
  let minDist = 45;
  for (const node of state.nodes) {
    const nx = node.x * scaleX;
    const ny = node.y * scaleY;
    const d = Math.sqrt((mouseX - nx) ** 2 + (mouseY - ny) ** 2);
    if (d < minDist) {
      minDist = d;
      nearest = node;
    }
  }

  if (nearest !== hoveredNode) {
    hoveredNode = nearest;
    if (nearest) {
      sendWS({ cmd: "hover_node", node_id: nearest.id });
      showTooltip(nearest);
    } else {
      sendWS({ cmd: "unhover" });
      hideTooltip();
    }
  }
});

graphCanvas.addEventListener("click", (e) => {
  initAudio();

  if (hoveredNode) {
    if (creatorMode) {
      if (!creatorFirst) {
        creatorFirst = hoveredNode.id;
        document.getElementById("bottom-status").textContent = `Creator: Selected ${hoveredNode.label} — click second node to link`;
        playSound("click");
      } else {
        sendWS({ cmd: "force_correlate", a: creatorFirst, b: hoveredNode.id });
        playSound("correlation_lock");
        document.getElementById("bottom-status").textContent = `Creator: Linked ${creatorFirst} ↔ ${hoveredNode.id}`;
        creatorFirst = null;
      }
      return;
    }

    // Unpin previously selected node
    if (selectedNode && selectedNode.id !== hoveredNode.id) {
      sendWS({ cmd: "unpin_node", node_id: selectedNode.id });
    }

    selectedNode = hoveredNode;
    sendWS({ cmd: "select_node", node_id: hoveredNode.id });
    sendWS({ cmd: "pin_node", node_id: hoveredNode.id });
    focusMode = true;
    document.body.classList.add("focus-mode");
    playSound("click");
  } else {
    // Unpin and deselect
    if (selectedNode) {
      sendWS({ cmd: "unpin_node", node_id: selectedNode.id });
    }
    selectedNode = null;
    focusMode = false;
    document.body.classList.remove("focus-mode");
    document.getElementById("detail-panel").classList.add("hidden");
  }
});

graphCanvas.addEventListener("mouseleave", () => {
  hoveredNode = null;
  sendWS({ cmd: "unhover" });
  hideTooltip();
});

function showTooltip(node) {
  const tooltip = document.getElementById("node-tooltip");
  updateTooltipPosition(node);
  tooltip.style.borderColor = node.color;

  const ageStr = node.age < 60 ? `${Math.floor(node.age)}s ago` : `${Math.floor(node.age / 60)}m ago`;
  const edgeCount = state.edges.filter(e => e.source === node.id || e.target === node.id).length;

  tooltip.innerHTML = `
    <div style="color:${node.color};font-size:14px">${NODE_CHARS[node.type] || "●"} ${escapeHtml(node.label)}</div>
    <div style="color:var(--green-dim);font-size:11px">${node.protocol.toUpperCase()} ${node.type} · ${edgeCount} links</div>
    <div style="color:var(--green-dim);font-size:11px">Last seen: ${ageStr}</div>
    ${node.cluster_id ? `<div style="color:var(--magenta);font-size:11px">Cluster: ${node.confidence ? (node.confidence * 100).toFixed(0) + "%" : "?"}</div>` : ""}
    <div style="color:var(--green-dim);font-size:10px;margin-top:2px">Click for details</div>
  `;
  tooltip.classList.remove("hidden");
}

function updateTooltipPosition(node) {
  const tooltip = document.getElementById("node-tooltip");
  if (tooltip.classList.contains("hidden")) return;
  const scaleX = graphCanvas.width / 160;
  const scaleY = graphCanvas.height / 50;
  let left = node.x * scaleX + 15;
  let top = node.y * scaleY - 10;
  // Keep tooltip within graph panel bounds
  if (left + 250 > graphCanvas.width) left = node.x * scaleX - 260;
  if (top + 80 > graphCanvas.height) top = graphCanvas.height - 85;
  if (top < 0) top = 5;
  tooltip.style.left = left + "px";
  tooltip.style.top = top + "px";
}

function hideTooltip() {
  document.getElementById("node-tooltip").classList.add("hidden");
}

// ═══════════════════════════════════════════════════════════════
// SOUND TOGGLE
// ═══════════════════════════════════════════════════════════════
document.getElementById("btn-sound").addEventListener("click", () => {
  initAudio();
  soundEnabled = !soundEnabled;
  document.getElementById("btn-sound").textContent = soundEnabled ? "♪" : "♪̸";
  document.getElementById("btn-sound").style.opacity = soundEnabled ? 1 : 0.4;
  if (masterGain) {
    masterGain.gain.value = soundEnabled ? 0.5 : 0;
  }
  playSound("click");
});

// ═══════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS & EASTER EGGS
// ═══════════════════════════════════════════════════════════════
const konamiSequence = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65];
let konamiIndex = 0;
let textBuffer = "";

document.addEventListener("keydown", (e) => {
  initAudio();

  if (e.keyCode === konamiSequence[konamiIndex]) {
    konamiIndex++;
    if (konamiIndex === konamiSequence.length) {
      konamiIndex = 0;
      triggerKonami();
    }
  } else {
    konamiIndex = 0;
  }

  textBuffer += e.key.toLowerCase();
  if (textBuffer.length > 20) textBuffer = textBuffer.slice(-20);
  if (textBuffer.endsWith("fsociety")) {
    triggerFsociety();
    textBuffer = "";
  }

  if (e.ctrlKey && e.shiftKey && e.key === "C") {
    e.preventDefault();
    creatorMode = !creatorMode;
    creatorFirst = null;
    document.body.classList.toggle("creator-mode", creatorMode);
    document.getElementById("bottom-status").textContent = creatorMode
      ? "CREATOR MODE: Click two nodes to force correlation"
      : "Ready";
    playSound(creatorMode ? "correlation_lock" : "click");
  }

  if (e.key === "Escape") {
    if (selectedNode) {
      sendWS({ cmd: "unpin_node", node_id: selectedNode.id });
    }
    selectedNode = null;
    focusMode = false;
    document.body.classList.remove("focus-mode");
    document.getElementById("detail-panel").classList.add("hidden");
    hideWizard();
  }
});

function triggerKonami() {
  playSound("konami");
  document.body.classList.toggle("inverted");
  const overlay = document.getElementById("easter-overlay");
  overlay.classList.remove("hidden");
  overlay.style.color = "#00ff41";
  overlay.textContent = "Hello, friend…";
  overlay.style.animation = "glitch-1 0.5s ease-out";
  setTimeout(() => {
    overlay.classList.add("hidden");
    overlay.style.animation = "";
  }, 3000);
}

function triggerFsociety() {
  playSound("glitch");
  matrixIntensity = 5;
  const overlay = document.getElementById("easter-overlay");
  overlay.classList.remove("hidden");
  overlay.style.color = "#ff0000";
  overlay.innerHTML = "THEY OWN YOU<br><span style='font-size:24px;color:#ff000088'>control is an illusion</span>";
  overlay.style.animation = "glitch-1 0.3s ease-out 3";
  setTimeout(() => {
    overlay.classList.add("hidden");
    overlay.style.animation = "";
    matrixIntensity = 1;
  }, 4000);
}

function checkEasterEggs() {
  if (totalLeaksEver === 666) {
    playSound("sub_bass");
    const overlay = document.getElementById("easter-overlay");
    overlay.classList.remove("hidden");
    overlay.style.color = "#ff0000";
    overlay.textContent = "E";
    overlay.style.fontSize = "200px";
    setTimeout(() => {
      overlay.classList.add("hidden");
      overlay.style.fontSize = "";
    }, 1500);
  }
}

// ═══════════════════════════════════════════════════════════════
// CLOCK
// ═══════════════════════════════════════════════════════════════
function updateClock() {
  const now = new Date();
  document.getElementById("clock").textContent = now.toLocaleTimeString("en-US", { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// ═══════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// ═══════════════════════════════════════════════════════════════
// BOOT
// ═══════════════════════════════════════════════════════════════
initMatrixRain();
connectWS();
requestAnimationFrame(renderGraph);

document.getElementById("status-text").textContent = "CONNECTING";
document.getElementById("bottom-status").textContent = "LEAKPHANTOM v2.3.1 — Phantom Protocol";

})();
