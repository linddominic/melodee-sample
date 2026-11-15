// Melodee's web page: the link to the MPC in the header on every page, the
// device page's update and plug-in uploads, and the docs' side lists.
"use strict";
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const tones = ["var(--coral)", "var(--amber)", "var(--mint)", "var(--lilac)"];

// The MPC answers one request at a time: no status asks while a file is on its way, and one at a time.
let sending = false, asking = false, last = null;

function link(state, word) {
  const el = $("#link");
  el.dataset.state = state;
  $("#link-word").textContent = word;
}

async function status() {
  try {
    const s = await (await fetch("/status", {cache: "no-store"})).json();
    link(update.watching ? "busy" : "on", "MPC " + s.version);
    device.show(s);
    last = s;
    return s;
  } catch (e) {
    link(update.watching === "install" ? "busy" : "off", update.watching === "install" ? "Restarting" : "Not connected");
    device.lost();
    return null;
  }
}

function gb(bytes) { return bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + " GB" : Math.round(bytes / 1e6) + " MB"; }

// ---- The device page ----

const device = {
  here: !!$("#device"),
  show(s) {
    if (!this.here) return;
    $("#v-version").textContent = s.version;
    $("#g-version").style.width = "100%";
    if (s.card) {
      $("#v-card").innerHTML = gb(s.card_free) + "<small>free</small>";
      $("#g-card").style.width = (s.card_total ? 100 * (1 - s.card_free / s.card_total) : 0) + "%";
    } else {
      $("#v-card").textContent = "None";
      $("#g-card").style.width = "0";
    }
    if (s.card !== this.card) { this.card = s.card; plugins(); }
    update.follow(s);
    panels.forEach(p => p.ready());
  },
  lost() {
    if (!this.here) return;
    this.card = false;
    panels.forEach(p => p.ready());
  },
};

// One upload panel: its drop zone, file, gauge, button and line of words.
function Panel(el, path) {
  const input = $("input", el), drop = $("[data-drop]", el);
  const self = {
    el, file: null, busy: false,
    say(text, kind) { const p = $("[data-say]", el); p.textContent = text || ""; p.className = "say" + (kind ? " " + kind : ""); },
    bar(part) { $("[data-bar]", el).style.width = (part * 100) + "%"; },
    ready() {
      el.classList.toggle("busy", self.busy);
      $("[data-send]", el).disabled = self.busy || !self.file || !device.card;
      if (!device.card && !self.busy && last) self.say(last.card === false ? "No SD card in the MPC" : "", "bad");
    },
    pick(file) {
      if (file && !/\.zip$/i.test(file.name)) { self.say("Not a .zip", "bad"); return; }
      self.file = file || null;
      $("[data-name]", el).textContent = file ? file.name : $("[data-name]", el).dataset.empty;
      $("[data-hint]", el).textContent = file ? gb(file.size) : "Drop here or choose";
      drop.classList.toggle("chosen", !!file);
      self.say("");
      self.bar(0);
      self.ready();
    },
    send(done) {
      const file = self.file;
      self.busy = sending = true;
      self.ready();
      self.say("Sending…");
      const xhr = new XMLHttpRequest();
      xhr.open("POST", path + "?name=" + encodeURIComponent(file.name));
      xhr.setRequestHeader("X-Melodee", "1");
      xhr.setRequestHeader("Content-Type", "application/zip");
      xhr.upload.onprogress = e => { if (e.lengthComputable) self.bar(e.loaded / e.total); };
      xhr.upload.onload = () => { self.bar(1); self.say(path === "/update" ? "Checking the zip…" : "Unzipping…"); };
      xhr.onerror = () => { sending = self.busy = false; self.say("The MPC stopped answering", "bad"); self.ready(); done(null); };
      xhr.onload = () => {
        sending = false;
        let r = {};
        try { r = JSON.parse(xhr.responseText); } catch (e) {}
        self.pick(null);
        done(xhr.status === 200 ? r : {error: r.error || "Failed"});
      };
      xhr.send(file);
    },
  };
  $("[data-name]", el).dataset.empty = $("[data-name]", el).textContent;
  input.addEventListener("change", () => self.pick(input.files[0]));
  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", e => { e.preventDefault(); drop.classList.remove("over"); if (!self.busy) self.pick(e.dataTransfer.files[0]); });
  $("[data-send]", el).addEventListener("click", () => self.file && self.send(el.id === "update" ? update.sent : installed));
  return self;
}

const panels = device.here ? [Panel($("#update"), "/update"), Panel($("#plugins"), "/plugin")] : [];
const [updatePanel, pluginPanel] = panels;

// The update: sent, asked on the MPC, then the MPC's own steps, then the restart.
const update = {
  watching: null, from: "",
  order: ["send", "ask", "saving", "checking", "writing", "starting"],
  step(name, how) {
    const at = this.order.indexOf(name);
    $$("#update .steps li").forEach((li, i) => {
      li.className = i < at ? "done" : i === at ? how || "now" : "";
    });
  },
  sent(r) {
    if (!r) { update.step("send", "failed"); return; }
    if (r.error) { updatePanel.busy = false; updatePanel.say(r.error, "bad"); update.step("send", "failed"); updatePanel.ready(); return; }
    update.watching = "offer";
    update.from = last ? last.version : "";
    update.step("ask", "now wait");
    updatePanel.say("Press INSTALL on the MPC to update to " + r.offered, "ask");
  },
  follow(s) {
    if (!updatePanel) return;
    if (this.watching && this.from && s.version !== this.from) {
      this.watching = null;
      $$("#update .steps li").forEach(li => li.className = "done");
      updatePanel.busy = false;
      updatePanel.say("Updated to " + s.version, "ok");
      return;
    }
    if (!this.watching) return;
    const words = {saving: "Saving the project…", checking: "Checking the update…", writing: "Copying to the card…", starting: "Restarting…"};
    if (s.phase === "failed") {
      this.step(this.order[Math.max(2, this.order.indexOf(this.lastPhase || "saving"))], "failed");
      updatePanel.say(s.error || "Update failed", "bad");
      this.watching = null;
      updatePanel.busy = false;
    } else if (words[s.phase]) {
      this.watching = "install";
      this.lastPhase = s.phase;
      this.step(s.phase);
      updatePanel.say(words[s.phase], "ask");
    } else if (this.watching === "offer" && !s.offer) {
      this.watching = null;
      this.step("ask", "failed");
      updatePanel.busy = false;
      updatePanel.say("LATER on the MPC: not installed", "");
    }
  },
};
if (device.here) update.step("none");

function installed(r) {
  pluginPanel.busy = false;
  if (!r) return;
  if (r.error) { pluginPanel.say(r.error, "bad"); pluginPanel.ready(); return; }
  pluginPanel.say("Installed " + (r.installed || []).join(", "), "ok");
  plugins(r.installed || []);
}

async function plugins(fresh = []) {
  if (!device.here) return;
  const list = $("#plugin-list");
  try {
    const p = await (await fetch("/plugins", {cache: "no-store"})).json();
    list.innerHTML = "";
    const real = p.plugins.filter(x => !x.folder || x.loadable);
    const ready = real.filter(x => x.loadable).length;
    $("#v-plugins").innerHTML = p.card ? ready + (real.length > ready ? "<small>of " + real.length + "</small>" : "") : "–";
    $("#g-plugins").style.width = real.length ? (100 * ready / real.length) + "%" : "0";
    if (!p.plugins.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = p.card ? "None yet" : "No SD card";
      list.append(li);
      return;
    }
    p.plugins.forEach((item, n) => {
      const li = document.createElement("li");
      li.style.setProperty("--stripe", tones[n % 4]);
      if (item.why) li.classList.add("off");
      if (fresh.includes(item.file)) li.classList.add("new");
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = item.name;
      li.append(name);
      if (item.why) {
        const why = document.createElement("span");
        why.className = "why";
        why.textContent = item.why;
        li.append(why);
      }
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = item.folder ? "FOLDER" : item.format;
      li.append(chip);
      const del = document.createElement("button");
      del.type = "button";
      del.className = "act del";
      del.title = "Delete";
      del.setAttribute("aria-label", "Delete " + item.name);
      del.innerHTML = glyphs.del;
      del.addEventListener("click", () => removePlugin(item));
      li.append(del);
      list.append(li);
    });
  } catch (e) { /* the next status ask says whether the MPC is there */ }
}

async function removePlugin(item) {
  const what = item.folder ? `Delete the folder "${item.file}" and everything in it?` : `Delete ${item.name} (${item.file})?`;
  if (!confirm(what + " This cannot be undone.")) return;
  try {
    const r = await fetch("/plugin/delete?file=" + encodeURIComponent(item.file), {method: "POST", headers: {"X-Melodee": "1"}, body: ""});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "Failed");
    pluginPanel.say("Deleted " + item.name, "ok");
  } catch (e) { pluginPanel.say(e.message, "bad"); }
  plugins();
}

// ---- Files: the card's folders ----

const glyphs = {
  dir: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M2.5 5h5.5l1.5 2h8v9h-15z" fill="currentColor" opacity=".9"/></svg>',
  audio: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M3 10h1.5M6 6v8M9 3v14M12 7v6M15 5v10M17.5 9v2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none"/></svg>',
  file: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 2.5h6.5l3.5 3.5v11.5H5z M11.5 2.5V6H15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 3v10l8.5-5z" fill="currentColor"/></svg>',
  stop: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4" y="4" width="8" height="8" rx="1" fill="currentColor"/></svg>',
  save: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  del: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 9h5.6l.7-9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>',
};
const audioKinds = /\.(wav|mp3|flac|ogg|oga|aif|aiff)$/i;

const files = {
  here: !!$("#files"),
  path: "", writable: false, fresh: new Set(), playing: "",
  rel(name) { return this.path ? this.path + "/" + name : name; },
  url(rel, save) { return "/file?path=" + encodeURIComponent(rel) + (save ? "&save=1" : ""); },
  size(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + " GB" : n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : n >= 1e3 ? Math.round(n / 1e3) + " KB" : n + " B"; },
  when(t) {
    if (!t) return "";
    const d = new Date(t * 1000);
    return d.toLocaleDateString(undefined, {day: "numeric", month: "short", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric"});
  },
  async open(path) {
    this.path = path;
    const list = $("#entries");
    let r;
    try { r = await fetch("/list?path=" + encodeURIComponent(path), {cache: "no-store"}); } catch (e) { return; }
    const data = await r.json().catch(() => ({}));
    this.crumbs();
    list.innerHTML = "";
    if (!r.ok) { this.say(data.error || "Cannot open this folder"); this.writable = false; this.tools(); return; }
    this.writable = data.writable;
    this.tools();
    if (!data.entries.length) { this.say(this.writable ? "Empty. Drop files here." : "Empty"); return; }
    data.entries.forEach(e => list.append(this.row(e)));
    this.fresh.clear();
  },
  say(words) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = words;
    $("#entries").append(li);
  },
  tools() {
    $("#tools").hidden = !this.writable;
    $("#readonly").hidden = this.writable || !last || !last.card;
  },
  crumbs() {
    const nav = $("#crumbs");
    nav.innerHTML = "";
    const parts = this.path ? this.path.split("/") : [];
    const link = (label, to) => {
      const a = document.createElement("a");
      a.href = "#" + to.split("/").map(encodeURIComponent).join("/");
      a.textContent = label;
      return a;
    };
    nav.append(link("SD card", ""));
    parts.forEach((p, i) => {
      const s = document.createElement("span");
      s.className = "sep";
      s.textContent = "/";
      nav.append(s, link(p, parts.slice(0, i + 1).join("/")));
    });
  },
  row(e) {
    const li = document.createElement("li");
    const rel = this.rel(e.name);
    const audio = !e.dir && audioKinds.test(e.name);
    li.className = "entry " + (e.dir ? "dir" : audio ? "audio" : "file");
    li.style.setProperty("--stripe", e.dir ? "var(--amber)" : audio ? "var(--mint)" : "var(--lilac)");
    if (this.fresh.has(e.name)) li.classList.add("fresh");
    if (rel === this.playing) li.classList.add("playing");
    li.innerHTML = glyphs[e.dir ? "dir" : audio ? "audio" : "file"];
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = e.name;
    const size = document.createElement("span");
    size.className = "meta";
    size.textContent = e.dir ? "" : this.size(e.size);
    const when = document.createElement("span");
    when.className = "meta when";
    when.textContent = this.when(e.time);
    const acts = document.createElement("span");
    acts.className = "acts";
    const act = (kind, title, run) => {
      const b = document.createElement(kind === "save" ? "a" : "button");
      b.className = "act " + kind;
      b.title = title;
      b.setAttribute("aria-label", title + " " + e.name);
      b.innerHTML = glyphs[kind === "play" && rel === this.playing ? "stop" : kind];
      if (kind === "save") { b.href = this.url(rel, true); b.setAttribute("download", e.name); }
      else b.addEventListener("click", ev => { ev.stopPropagation(); run(); });
      return b;
    };
    if (audio) acts.append(act("play", "Play", () => this.play(rel)));
    if (!e.dir) acts.append(act("save", "Download"));
    if (this.writable) acts.append(act("del", "Delete", () => this.remove(e)));
    li.append(name, size, when, acts);
    if (e.dir) li.addEventListener("click", () => { location.hash = rel.split("/").map(encodeURIComponent).join("/"); });
    else if (audio) li.addEventListener("click", () => this.play(rel));
    return li;
  },
  play(rel) {
    const player = $("#player");
    if (this.playing === rel) { player.pause(); this.playing = ""; }
    else { player.src = this.url(rel); player.play().catch(() => {}); this.playing = rel; }
    this.mark();
  },
  mark() {
    $$("#entries .entry").forEach(li => {
      const rel = this.rel($(".name", li).textContent);
      const on = rel === this.playing;
      li.classList.toggle("playing", on);
      const b = $(".act.play", li);
      if (b) b.innerHTML = glyphs[on ? "stop" : "play"];
    });
  },
  async post(path) {
    const r = await fetch(path, {method: "POST", headers: {"X-Melodee": "1"}, body: ""});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "Failed");
    return data;
  },
  async folder() {
    const name = prompt("New folder name");
    if (!name) return;
    try {
      await this.post("/mkdir?path=" + encodeURIComponent(this.path) + "&name=" + encodeURIComponent(name.trim()));
      this.fresh.add(name.trim());
      this.open(this.path);
    } catch (e) { alert(e.message); }
  },
  async remove(e) {
    const what = e.dir ? `Delete the folder "${e.name}" and everything in it?` : `Delete "${e.name}"?`;
    if (!confirm(what + " This cannot be undone.")) return;
    try {
      if (this.playing === this.rel(e.name)) this.play(this.playing);
      await this.post("/delete?path=" + encodeURIComponent(this.rel(e.name)));
      this.open(this.path);
    } catch (err) { alert(err.message); }
  },
  // Files one at a time (the MPC serves one request at a time), into the folder open when they were dropped.
  async upload(list) {
    const queue = [...list].filter(f => f.size >= 0);
    if (!queue.length || !this.writable) return;
    const into = this.path;
    sending = true;
    $("#queue").hidden = false;
    let done = 0, failed = [];
    for (const file of queue) {
      $("#queue-words").textContent = `${done + 1} of ${queue.length} · ${file.name}`;
      $("#queue-bar").style.width = "0";
      const r = await new Promise(resolve => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/upload?path=" + encodeURIComponent(into) + "&name=" + encodeURIComponent(file.name));
        xhr.setRequestHeader("X-Melodee", "1");
        xhr.setRequestHeader("Content-Type", "application/octet-stream");
        xhr.upload.onprogress = e => { if (e.lengthComputable) $("#queue-bar").style.width = (100 * e.loaded / e.total) + "%"; };
        xhr.onload = () => { let d = {}; try { d = JSON.parse(xhr.responseText); } catch (e) {} resolve(xhr.status === 200 ? d : {error: d.error || "Failed"}); };
        xhr.onerror = () => resolve({error: "The MPC stopped answering"});
        xhr.send(file);
      });
      done++;
      if (r.error) failed.push(file.name + ": " + r.error);
      else this.fresh.add(r.name);
    }
    sending = false;
    $("#queue-words").textContent = failed.length ? failed.join(" · ") : `${done} uploaded`;
    $("#queue-bar").style.width = "100%";
    setTimeout(() => { if (!sending) $("#queue").hidden = true; }, failed.length ? 8000 : 2500);
    if (this.path === into) this.open(into);
  },
  start() {
    if (!this.here) return;
    const go = () => this.open(decodeURIComponent(location.hash.slice(1)).split("/").filter(Boolean).join("/"));
    addEventListener("hashchange", go);
    $("#player").addEventListener("ended", () => { this.playing = ""; this.mark(); });
    $("#new-folder").addEventListener("click", () => this.folder());
    $("#upload-input").addEventListener("change", e => { this.upload(e.target.files); e.target.value = ""; });
    const zone = $("#file-list");
    let depth = 0;
    zone.addEventListener("dragenter", e => { e.preventDefault(); if (this.writable && ++depth === 1) zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; zone.classList.remove("over"); } });
    zone.addEventListener("dragover", e => e.preventDefault());
    zone.addEventListener("drop", e => { e.preventDefault(); depth = 0; zone.classList.remove("over"); this.upload(e.dataTransfer.files); });
    go();
  },
};

// ---- Kits: the factory kits and the card's, and kits of one's own (docs/KIT_MANAGER.md) ----

// Waiting on the MPC for something one asked for: a thin bar under the top bar once it takes longer than feels
// instant (about a tenth of a second); background reads (preloads, the kit list filling in) do not show it.
const busy = {
  n: 0, timer: 0,
  start() { if (this.n++ === 0) this.timer = setTimeout(() => { const b = $("#busy"); if (b) b.hidden = false; }, 120); },
  end() {
    if (--this.n > 0) return;
    this.n = 0;
    clearTimeout(this.timer);
    const b = $("#busy");
    if (b) b.hidden = true;
  },
  async run(work) { this.start(); try { return await work(); } finally { this.end(); } },
};

// Kit sound: each pad's file fetched and decoded once, then played with Web Audio, so a tap sounds at once
// (an <audio> element asked the MPC again on every tap). The decoded audio also draws each pad's waveform.
const sound = {
  ctx: null, cache: new Map(), voices: new Map(), queue: Promise.resolve(),
  context() {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!this.ctx && C) this.ctx = new C({latencyHint: "interactive"});
    if (this.ctx && this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
    return this.ctx;
  },
  // {buffer, peaks, rate} or null when the browser cannot play it. Preloads wait in line, one request at a time
  // (the MPC's web server answers one at a time); `now` starts one at once, even one already waiting in line.
  load(url, now) {
    let e = this.cache.get(url);
    if (!e) {
      e = {started: false};
      e.promise = new Promise(done => { e.done = done; });
      this.cache.set(url, e);
      if (!now) this.queue = this.queue.then(() => this.fetch(url, e));
    }
    if (now) this.fetch(url, e, true);
    return e.promise;
  },
  ready(url) { const e = this.cache.get(url); return !!(e && e.ready); },
  fetch(url, e, asked) {
    if (e.started) return e.promise;
    e.started = true;
    if (asked) { busy.start(); e.promise.then(() => busy.end()); }
    e.promise.then(() => { e.ready = true; });
    if (this.cache.get(url) !== e) { e.done(null); return e.promise; } // forgotten while it waited
    (async () => {
      const ctx = this.context();
      if (!ctx) return null;
      const r = await fetch(url, {cache: "no-store"});
      if (!r.ok) return null;
      const bytes = await r.arrayBuffer();
      const rate = wavRate(bytes);
      const buffer = await ctx.decodeAudioData(bytes);
      return {buffer, peaks: peaksOf(buffer), rate: rate || buffer.sampleRate};
    })().catch(() => null).then(e.done);
    return e.promise;
  },
  forget(prefix) { for (const url of [...this.cache.keys()]) if (url.startsWith(prefix)) this.cache.delete(url); },
  // One voice a key: playing a key again restarts it, and a pad's mute group chokes the others in it.
  start(key, got, o = {}) {
    const ctx = this.context();
    this.stop(key);
    if (o.group) for (const [k, v] of this.voices) if (v.group === o.group) this.stop(k);
    const total = got.buffer.duration;
    let from = 0, to = total;
    if (o.end > o.start) { from = Math.min(o.start / got.rate, total); to = Math.min((o.end + 1) / got.rate, total); }
    if (to - from < 0.002) { from = 0; to = total; }
    const src = ctx.createBufferSource(), gain = ctx.createGain();
    src.buffer = got.buffer;
    src.playbackRate.value = o.rate || 1;
    gain.gain.value = o.gain ?? 1;
    src.connect(gain);
    if (ctx.createStereoPanner && o.pan) { const pan = ctx.createStereoPanner(); pan.pan.value = o.pan; gain.connect(pan).connect(ctx.destination); }
    else gain.connect(ctx.destination);
    src.start(0, from, to - from);
    const v = {src, gain, at: ctx.currentTime, from, to, total, speed: o.rate || 1, group: o.group || 0};
    src.onended = () => { if (this.voices.get(key) === v) { this.voices.delete(key); o.done && o.done(); } };
    this.voices.set(key, v);
    return v;
  },
  stop(key) {
    const v = this.voices.get(key);
    if (!v) return;
    this.voices.delete(key);
    const t = this.ctx.currentTime; // a short fade, no click
    v.gain.gain.setValueAtTime(v.gain.gain.value, t);
    v.gain.gain.linearRampToValueAtTime(0, t + 0.012);
    v.src.stop(t + 0.015);
  },
  // Where a voice is heard now, 0-1 of its whole file: the output's latency taken off, so the line meets the sound.
  where(key) {
    const v = this.voices.get(key);
    if (!v) return null;
    const late = (this.ctx.outputLatency || 0) + (this.ctx.baseLatency || 0);
    const t = Math.max(0, this.ctx.currentTime - late - v.at) * v.speed;
    return Math.min(v.from + t, v.to) / v.total;
  },
};

// A WAV file's own sample rate (a pad's region is in its frames; decoding resamples to the browser's rate).
function wavRate(bytes) {
  const d = new DataView(bytes);
  if (d.byteLength < 12 || d.getUint32(0) !== 0x52494646 || d.getUint32(8) !== 0x57415645) return 0; // RIFF WAVE
  for (let at = 12; at + 8 <= d.byteLength;) {
    const size = d.getUint32(at + 4, true);
    if (d.getUint32(at) === 0x666d7420 && at + 16 <= d.byteLength) return d.getUint32(at + 12, true); // "fmt "
    at += 8 + size + (size & 1);
  }
  return 0;
}

// The loudest moment in each of `n` slices, over every channel.
function peaksOf(buffer, n = 160) {
  const peaks = new Float32Array(n), step = buffer.length / n;
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < n; i++) {
      let top = peaks[i];
      const end = Math.min(data.length, Math.floor((i + 1) * step));
      for (let j = Math.floor(i * step); j < end; j += 4) { const a = Math.abs(data[j]); if (a > top) top = a; }
      peaks[i] = top;
    }
  }
  let most = 0;
  for (const p of peaks) most = Math.max(most, p);
  if (most > 0) for (let i = 0; i < n; i++) peaks[i] /= most;
  return peaks;
}

// The pads' keys, by place on the keyboard (any layout): the top row of pads (13-16) on 1-4, the bottom (1-4) on Z-V.
const padKeys = ["KeyZ", "KeyX", "KeyC", "KeyV", "KeyA", "KeyS", "KeyD", "KeyF", "KeyQ", "KeyW", "KeyE", "KeyR", "Digit1", "Digit2", "Digit3", "Digit4"];
let padKeyNames = padKeys.map(k => k.slice(-1));
if (navigator.keyboard && navigator.keyboard.getLayoutMap)
  navigator.keyboard.getLayoutMap().then(m => { padKeyNames = padKeys.map((k, i) => (m.get(k) || padKeyNames[i]).toUpperCase()); if (kits.kit) kits.drawKit(); }).catch(() => {});

const kits = {
  here: !!$("#kits"),
  list: [], show: "all", kit: null, bank: 0, pad: null, source: "sd", folder: "", playing: "",
  async get(url, quiet) {
    if (!quiet) return busy.run(() => this.get(url, true));
    const r = await fetch(url, {cache: "no-store"});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "Failed");
    return data;
  },
  async post(url) {
    sending = true;
    busy.start();
    $("#kits").setAttribute("aria-busy", "true");
    try {
      const r = await fetch(url, {method: "POST", headers: {"X-Melodee": "1"}, body: ""});
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || "Failed");
      return data;
    } finally { sending = false; busy.end(); $("#kits").removeAttribute("aria-busy"); }
  },
  q(params) { return Object.entries(params).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&"); },
  mine(k) { return !k.readOnly; },
  // The MPC answers with every kit by name at once and reads a few more each time it is asked (a factory kit takes
  // it a fifth of a second): the list shows straight away and its pad counts fill in as the page asks again.
  async load() {
    const ul = $("#kit-list"), more = $("#kit-progress");
    clearTimeout(this.again);
    if (!this.list.length) { ul.innerHTML = ""; this.say(ul, "Loading kits from the MPC…"); }
    let data;
    try { data = await this.get("/api/kits", !!this.list.length); } // the first ask shows the bar, the filling in does not
    catch (e) {
      if (this.list.length) { this.again = setTimeout(() => this.load(), 2000); return; } // keep what is shown, try again
      ul.innerHTML = ""; this.say(ul, e.message); return;
    }
    this.list = data.kits;
    this.draw();
    const left = data.pending || 0;
    more.hidden = !left;
    more.textContent = `Reading kits… ${data.kits.length - left} of ${data.kits.length}`;
    if (left) this.again = setTimeout(() => this.load(), 50);
    else this.sounds(this.source).catch(() => {}); // ready before the first search
  },
  say(ul, words) { const li = document.createElement("li"); li.className = "empty"; li.textContent = words; ul.append(li); },
  draw() {
    const ul = $("#kit-list"), find = $("#kit-search").value.trim().toLowerCase();
    ul.innerHTML = "";
    const shown = this.list.filter(k => (this.show === "all" || (this.show === "factory" && k.source === "factory")
      || (this.show === "mine" && this.mine(k)) || (this.show === "sd" && k.source === "sd"))
      && (!find || k.name.toLowerCase().includes(find) || k.folder.toLowerCase().includes(find)));
    if (!shown.length) { this.say(ul, this.list.length ? "No kits match" : "No kits found"); return; }
    shown.forEach(k => {
      const li = document.createElement("li");
      li.className = "kit-row" + (k.kit ? "" : " off") + (this.kit && this.kit.id === k.id ? " here" : "") + (this.opening === k.id ? " opening" : "");
      li.style.setProperty("--stripe", k.source === "factory" ? "var(--lilac)" : this.mine(k) ? "var(--coral)" : "var(--amber)");
      li.tabIndex = 0;
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = k.name;
      const where = document.createElement("small");
      where.textContent = k.error ? k.error : (k.source === "factory" ? "Factory / " : "SD / ") + k.folder;
      name.append(where);
      const meta = document.createElement("span");
      meta.className = "why";
      meta.textContent = k.pending ? "…" : k.error ? "" : k.kit ? k.padCount + (k.padCount === 1 ? " pad" : " pads") : k.padCount ? "" : "No kit";
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = k.source === "factory" ? "FACTORY" : this.mine(k) ? "MINE" : k.format.toUpperCase();
      li.append(name, meta, chip);
      const open = () => this.open(k.id);
      li.addEventListener("click", open);
      li.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
      ul.append(li);
    });
  },
  async open(id, keepPad) {
    this.opening = id;
    this.draw();
    $("#kit-main").classList.add("loading");
    let kit;
    try { kit = await this.get("/api/kits/kit?" + this.q({id})); }
    catch (e) { alert(e.message); return; }
    finally { if (this.opening === id) { this.opening = null; $("#kit-main").classList.remove("loading"); } }
    if (this.opening && this.opening !== id) return; // another kit was clicked meanwhile
    this.kit = kit;
    sound.forget("/api/kits/audio?"); // only the open kit's pads are kept
    if (!keepPad) { this.pad = null; this.bank = this.kit.banks.findIndex(b => b.pads.length); if (this.bank < 0) this.bank = 0; }
    location.hash = encodeURIComponent(id);
    this.drawKit();
    this.draw();
  },
  drawKit() {
    const k = this.kit;
    $("#kit-none").hidden = !!k;
    $("#kit-open").hidden = !k;
    this.hint();
    if (!k) return;
    $("#kit-source").textContent = k.source === "factory" ? "Factory kit · read only" : k.readOnly ? "SD card · read only" : "My kit";
    $("#kit-source").style.setProperty("--tone", k.source === "factory" ? "var(--lilac)" : k.readOnly ? "var(--amber)" : "var(--coral)");
    $("#kit-name").textContent = k.name;
    $("#kit-sub").textContent = `${k.padCount} ${k.padCount === 1 ? "pad" : "pads"} in ${k.bankCount} ${k.bankCount === 1 ? "bank" : "banks"}`
      + (k.track ? ` · track "${k.track}"` : "") + ` · ${k.folder}`;
    $("#kit-rename").hidden = $("#kit-delete").hidden = k.readOnly;
    const warn = $("#kit-warn");
    warn.innerHTML = "";
    (k.warnings || []).forEach(w => { const li = document.createElement("li"); li.textContent = w; warn.append(li); });
    if (k.readOnly) { const li = document.createElement("li"); li.className = "note"; li.textContent = "Read only. Duplicate it to make an editable copy on the card."; warn.append(li); }
    const banks = $("#banks");
    banks.innerHTML = "";
    k.banks.forEach((b, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "seg" + (b.pads.length ? " full" : "");
      btn.textContent = b.name;
      btn.setAttribute("aria-pressed", i === this.bank);
      btn.addEventListener("click", () => { this.bank = i; this.pad = null; this.drawKit(); });
      banks.append(btn);
    });
    // The MPC's pads: 13-16 on top, 1-4 at the bottom.
    const grid = $("#pad-grid");
    grid.innerHTML = "";
    const bank = k.banks[this.bank] || {pads: []};
    for (const row of [12, 8, 4, 0]) for (let c = 0; c < 4; c++) {
      const n = this.bank * 16 + row + c, pad = bank.pads.find(p => p.index === n);
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pad" + (pad ? " used" : "") + (this.pad === n ? " on" : "") + (pad && pad.layers.some(l => l.missing) ? " missing" : "");
      b.style.setProperty("--tone", tones[(row / 4 + c) % 4]);
      b.dataset.n = n;
      const label = document.createElement("small");
      label.textContent = String.fromCharCode(65 + this.bank) + String(row + c + 1).padStart(2, "0");
      const key = document.createElement("kbd");
      key.textContent = padKeyNames[row + c];
      label.append(key);
      const name = document.createElement("span");
      name.textContent = pad ? pad.name || "(instrument)" : "";
      const wave = document.createElement("canvas");
      wave.className = "wave";
      wave.setAttribute("aria-hidden", "true");
      const head = document.createElement("i");
      head.className = "head";
      b.append(wave, head, label, name);
      // Sounds on the press, not the click; a click picks the pad. Enter or Space (a click with no pointer) does both.
      b.addEventListener("pointerdown", e => { if (e.button === 0) { b.setPointerCapture?.(e.pointerId); this.hit(n); } });
      const up = () => this.release(n);
      b.addEventListener("pointerup", up);
      b.addEventListener("pointercancel", up);
      b.addEventListener("click", e => { if (e.detail === 0) this.hit(n); this.pick(n); });
      b.addEventListener("dragover", e => {
        if (!e.dataTransfer.types.includes("application/x-melodee-sound")) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        b.classList.add("drop");
      });
      b.addEventListener("dragleave", () => b.classList.remove("drop"));
      b.addEventListener("drop", e => {
        b.classList.remove("drop");
        const id = e.dataTransfer.getData("application/x-melodee-sound");
        if (!id) return;
        e.preventDefault();
        document.body.classList.remove("dragging-sound");
        this.put(n, id);
      });
      grid.append(b);
      if (pad) this.wave(n);
    }
    this.drawPad();
  },
  pick(n) {
    this.pad = n;
    $$("#pad-grid .pad").forEach(p => p.classList.toggle("on", +p.dataset.n === n));
    this.drawPad();
  },
  // The pad's first layer the browser can play, and its address.
  heard(n) {
    const pad = this.padOf(n), l = pad && pad.layers.find(l => l.preview);
    return l ? {pad, url: this.padUrl(n, l.index)} : null;
  },
  async wave(n) {
    const h = this.heard(n);
    if (!h) return;
    const got = await sound.load(h.url);
    const b = $(`#pad-grid .pad[data-n="${n}"]`);
    if (!got || !b || this.padOf(n) !== h.pad) return;
    const canvas = b.querySelector(".wave"), dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), ht = Math.max(1, Math.round(canvas.clientHeight * dpr));
    canvas.width = w; canvas.height = ht;
    const g = canvas.getContext("2d"), peaks = got.peaks, bar = w / peaks.length;
    // The pad's region bright, the rest of the file dim.
    const total = got.buffer.duration, p = h.pad;
    const from = p.end > p.start ? Math.min(1, p.start / got.rate / total) : 0, to = p.end > p.start ? Math.min(1, (p.end + 1) / got.rate / total) : 1;
    g.fillStyle = getComputedStyle(canvas).color;
    for (let i = 0; i < peaks.length; i++) {
      const at = (i + .5) / peaks.length;
      g.globalAlpha = at >= from && at <= to ? .9 : .28;
      const y = Math.max(dpr, peaks[i] * ht * .92);
      g.fillRect(i * bar, (ht - y) / 2, Math.max(dpr, bar - dpr * .6), y);
    }
  },
  async hit(n) {
    const b = $(`#pad-grid .pad[data-n="${n}"]`);
    if (b) { b.classList.remove("hit"); void b.offsetWidth; b.classList.add("hit"); }
    sound.context(); // in the press itself, so the browser lets it sound
    const h = this.heard(n);
    if (!h) return;
    this.down = this.down || new Set();
    this.down.add(n);
    const voice = this.voice(n);
    if (b && !sound.ready(h.url)) b.classList.add("loading");
    const got = await sound.load(h.url, true);
    if (b) b.classList.remove("loading");
    if (this.voice(n) !== voice) return; // another kit opened while it loaded
    if (!got) { this.sayPad("The browser cannot play this file"); return; }
    const p = h.pad;
    if (p.play === "gate" && !this.down.has(n)) return; // let go while it loaded
    sound.start(voice, got, {start: p.start, end: p.end, gain: Math.min(1.5, (p.level ?? 100) / 100), pan: (p.pan || 0) / 50,
                                  rate: Math.pow(2, ((p.pitch || 0) + (p.fine || 0) / 100) / 12), group: p.group ? "g" + p.group : 0,
                                  done: () => this.playhead()});
    this.playhead();
  },
  // A pad's voice is its kit's: a pad of another kit still ringing out is not this kit's pad playing.
  voice(n) { return "pad:" + (this.kit ? this.kit.id : "") + ":" + n; },
  release(n) {
    if (!this.down || !this.down.delete(n)) return;
    const p = this.padOf(n);
    if (p && p.play === "gate") sound.stop(this.voice(n)); // Note on plays while held, as on the MPC
  },
  // Each sounding pad's line, moved every frame while any sounds.
  playhead() {
    if (this.frame) return;
    const step = () => {
      let any = false;
      $$("#pad-grid .pad").forEach(b => {
        const at = sound.where(this.voice(+b.dataset.n));
        b.classList.toggle("sounding", at !== null);
        if (at !== null) { any = true; b.style.setProperty("--pos", at); }
      });
      this.frame = any ? requestAnimationFrame(step) : 0;
    };
    this.frame = requestAnimationFrame(step);
  },
  sayPad(words) { const say = $("#pad-say"); if (say) { say.className = "say bad"; say.textContent = words; } },
  key(e, down) {
    if (!this.kit || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName))) return;
    const i = padKeys.indexOf(e.code);
    if (i < 0) return;
    e.preventDefault();
    const n = this.bank * 16 + i;
    if (!down) this.release(n);
    else if (!e.repeat) this.hit(n);
  },
  padOf(n) { for (const b of this.kit.banks) for (const p of b.pads) if (p.index === n) return p; return null; },
  drawPad() {
    const panel = $("#pad-panel"), k = this.kit;
    this.hint();
    // With no pad picked the panel stays, saying what it is for, so the pads do not jump.
    const none = this.pad === null;
    panel.classList.toggle("empty", none);
    $$("#pad-panel > :not(.pad-none)").forEach(x => { x.hidden = none; });
    let note = $("#pad-panel .pad-none");
    if (!note) { note = document.createElement("p"); note.className = "pad-none"; panel.prepend(note); }
    note.textContent = "Press a pad to hear it, click it to see its sample and settings.";
    note.hidden = !none;
    if (none) return;
    const pad = this.padOf(this.pad);
    $("#pad-label").textContent = "Pad " + String.fromCharCode(65 + Math.floor(this.pad / 16)) + String(this.pad % 16 + 1).padStart(2, "0");
    $("#pad-name").textContent = pad ? pad.name || "(instrument)" : "Empty";
    $("#pad-clear").hidden = k.readOnly || !pad;
    const layers = $("#pad-layers");
    layers.innerHTML = "";
    (pad ? pad.layers : []).forEach((l, i) => {
      const li = document.createElement("li");
      li.style.setProperty("--stripe", l.missing ? "var(--rec)" : "var(--mint)");
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = (pad.layers.length > 1 ? `Layer ${l.index + 1}: ` : "") + (l.sampleName || "(unnamed)");
      const path = document.createElement("small");
      path.textContent = l.samplePath;
      name.append(path);
      const why = document.createElement("span");
      why.className = "why";
      why.textContent = l.missing ? "Missing" : l.preview ? "" : l.kind === "instrument" ? "Instrument: no preview" : "No preview";
      li.append(name, why);
      if (l.preview) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "act";
        b.title = "Play";
        b.innerHTML = glyphs[this.playing === this.padUrl(this.pad, l.index) ? "stop" : "play"];
        b.addEventListener("click", () => this.play(this.pad, l.index, l, true));
        li.append(b);
      }
      layers.append(li);
    });
    if (!pad) this.say(layers, k.readOnly ? "No sample on this pad" : "No sample yet: pick one below");
    const params = $("#pad-params");
    params.innerHTML = "";
    if (pad) {
      const field = (key, label, value, min, max) => {
        const wrap = document.createElement("label");
        wrap.className = "param";
        const t = document.createElement("span");
        t.textContent = label;
        const input = document.createElement("input");
        input.type = "number"; input.min = min; input.max = max; input.value = value; input.disabled = k.readOnly;
        input.addEventListener("change", () => this.edit({[key]: input.value}));
        wrap.append(t, input);
        params.append(wrap);
      };
      field("level", "Level", pad.level, 0, 127);
      field("pan", "Pan", pad.pan, -50, 50);
      field("pitch", "Tune", pad.pitch, -48, 48);
      field("fine", "Fine", pad.fine, -99, 99);
      const wrap = document.createElement("label");
      wrap.className = "param";
      const t = document.createElement("span");
      t.textContent = "Play";
      const sel = document.createElement("select");
      sel.disabled = k.readOnly;
      [["oneshot", "One shot"], ["gate", "Note on"]].forEach(([v, w]) => { const o = document.createElement("option"); o.value = v; o.textContent = w; sel.append(o); });
      sel.value = pad.play;
      sel.addEventListener("change", () => this.edit({play: sel.value}));
      wrap.append(t, sel);
      params.append(wrap);
      const info = document.createElement("p");
      info.className = "param-info";
      info.textContent = `Region ${pad.start}–${pad.end || "end"} · mute group ${pad.group || "off"} · filter ${pad.filter}`
        + (pad.layers.length > 1 ? ` · layers ${pad.layerPlay.toLowerCase()}` : "") + (pad.reverse ? " · reversed" : "");
      params.append(info);
    }
    $("#pad-say").textContent = "";
    this.hint();
  },
  // What a sound can be put on: the Assign buttons show only with a pad of one's own kit picked.
  hint() {
    const k = this.kit, can = !!k && !k.readOnly && this.pad !== null;
    $("#sounds").dataset.assign = can ? "on" : "off";
    $("#sounds-hint").textContent = !k ? "Click a sound to hear it." : k.readOnly ? "Click to hear. Drop a sound on a pad to make an editable copy of this kit with it."
      : can ? `Click to hear, Assign to put it on pad ${this.padName(this.pad)}, or drop it on any pad.` : "Click to hear. Drop a sound on a pad, or pick a pad and press Assign.";
  },
  padName(n) { return String.fromCharCode(65 + Math.floor(n / 16)) + String(n % 16 + 1).padStart(2, "0"); },
  padUrl(n, layer) { return "/api/kits/audio?" + this.q({id: this.kit.id, pad: n, layer}); },
  play(n, layer, l, toggle) {
    const url = l && l.preview ? this.padUrl(n, layer) : null;
    this.audition(url, toggle);
  },
  async audition(url, toggle) {
    sound.context();
    if (!url || (toggle && this.playing === url)) { sound.stop("audition"); this.playing = ""; this.drawPadButtons(); return; }
    this.playing = url;
    this.drawPadButtons();
    const got = await sound.load(url, true);
    if (this.playing !== url) return;
    if (!got) { this.playing = ""; this.drawPadButtons(); this.sayPad("The browser cannot play this file"); return; }
    sound.start("audition", got, {done: () => { if (this.playing === url) { this.playing = ""; this.drawPadButtons(); } }});
  },
  drawPadButtons() {
    $$("#pad-layers .act").forEach((b, i) => { const pad = this.padOf(this.pad); if (pad) b.innerHTML = glyphs[this.playing === this.padUrl(this.pad, pad.layers.filter(l => l.preview)[i]?.index) ? "stop" : "play"]; });
    $$("#picker-list .act.play").forEach(b => { b.innerHTML = glyphs[this.playing === b.dataset.url ? "stop" : "play"]; });
  },
  async edit(values) {
    const say = $("#pad-say");
    say.className = "say"; say.textContent = "Saving…";
    const saving = $(`#pad-grid .pad[data-n="${this.pad}"]`);
    if (saving) saving.classList.add("saving");
    try {
      this.kit = await this.post("/api/kits/pad?" + this.q({id: this.kit.id, pad: this.pad, ...values}));
      sound.forget("/api/kits/audio?" + this.q({id: this.kit.id}) + "&");
      const keep = this.folder;
      this.drawKit();
      this.folder = keep;
      $("#pad-say").className = "say ok";
      $("#pad-say").textContent = "Saved to the card";
      this.refreshRow();
    } catch (e) { say.className = "say bad"; say.textContent = e.message; if (saving) saving.classList.remove("saving"); }
  },
  refreshRow() {
    const i = this.list.findIndex(x => x.id === this.kit.id);
    const row = {...this.kit};
    delete row.banks; delete row.warnings;
    if (i >= 0) this.list[i] = row; else this.list.push(row);
    this.draw();
  },
  async browse(folder) {
    this.folder = folder;
    if ($("#sound-search").value.trim()) return this.find();
    const ul = $("#picker-list"), nav = $("#picker-crumbs"), source = this.source;
    let data;
    try { data = await this.get("/api/kits/samples?" + this.q({source, path: folder})); }
    catch (e) { ul.innerHTML = ""; nav.innerHTML = ""; this.say(ul, e.message); return; }
    if (this.source !== source || this.folder !== folder || $("#sound-search").value.trim()) return; // moved on meanwhile
    nav.innerHTML = "";
    nav.hidden = false;
    const parts = folder ? folder.split("/") : [];
    const crumb = (label, to) => { const a = document.createElement("a"); a.href = "#"; a.textContent = label; a.addEventListener("click", e => { e.preventDefault(); this.browse(to); }); return a; };
    nav.append(crumb(this.source === "sd" ? "SD card" : "Factory samples", ""));
    parts.forEach((p, i) => { const s = document.createElement("span"); s.className = "sep"; s.textContent = "/"; nav.append(s, crumb(p, parts.slice(0, i + 1).join("/"))); });
    ul.innerHTML = "";
    const shown = data.entries.filter(e => e.dir || audioKinds.test(e.name));
    if (!shown.length) { this.say(ul, "No samples here"); return; }
    shown.forEach(e => {
      const rel = folder ? folder + "/" + e.name : e.name;
      if (!e.dir) { ul.append(this.soundRow(rel, e.name)); return; }
      const li = document.createElement("li");
      li.className = "entry dir";
      li.style.setProperty("--stripe", "var(--amber)");
      li.innerHTML = glyphs.dir;
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = e.name;
      li.append(name);
      li.addEventListener("click", () => this.browse(rel));
      ul.append(li);
    });
  },
  // Every sound under the source, fetched once a visit, then searched here as one types: all words, in any order,
  // in the file's name or its folders.
  async find() {
    const ul = $("#picker-list"), nav = $("#picker-crumbs"), source = this.source, words = $("#sound-search").value.trim().toLowerCase();
    if (!words) return this.browse(this.folder);
    nav.hidden = true;
    if (!this.indexed(source)) { ul.innerHTML = ""; this.say(ul, `Getting the list of sounds on the ${source === "sd" ? "card" : "MPC"}…`); }
    let index;
    try { index = await this.sounds(source); } catch (e) { ul.innerHTML = ""; this.say(ul, e.message); return; }
    if (this.source !== source || $("#sound-search").value.trim().toLowerCase() !== words) return; // typed on meanwhile
    const parts = words.split(/\s+/), found = [];
    for (const [rel, low] of index.files) if (parts.every(w => low.includes(w))) { found.push(rel); if (found.length > 300) break; }
    ul.innerHTML = "";
    const many = index.files.length.toLocaleString();
    if (!found.length) { this.say(ul, `No sounds match, of ${many}`); return; }
    found.slice(0, 300).forEach(rel => { const at = rel.lastIndexOf("/"); ul.append(this.soundRow(rel, rel.slice(at + 1), at > 0 ? rel.slice(0, at) : "")); });
    if (found.length > 300) this.say(ul, "Showing the first 300: type more to narrow it");
  },
  // Every sound under a source, asked for once a visit: [[path, lower case path]...] and whether the list was cut.
  sounds(source) {
    this.index = this.index || {};
    if (!this.index[source])
      this.index[source] = this.get("/api/kits/sounds?" + this.q({source}), true)
        .then(d => { const index = {files: d.files.map(f => [f, f.toLowerCase()]), full: d.full}; this.index[source].done = true; return index; })
        .catch(e => { delete this.index[source]; throw e; });
    return this.index[source];
  },
  indexed(source) { return !!(this.index && this.index[source] && this.index[source].done); },
  soundRow(rel, label, where) {
    const id = this.source + ":" + rel, url = "/api/kits/sample?" + this.q({sample: id});
    const li = document.createElement("li");
    li.className = "entry audio";
    li.style.setProperty("--stripe", "var(--mint)");
    li.draggable = true;
    li.innerHTML = glyphs.audio;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = label;
    if (where) { const small = document.createElement("small"); small.textContent = where; name.append(small); }
    const play = document.createElement("button");
    play.type = "button"; play.className = "act play"; play.title = "Play"; play.dataset.url = url;
    play.innerHTML = glyphs[this.playing === url ? "stop" : "play"];
    play.addEventListener("click", ev => { ev.stopPropagation(); this.audition(url, true); });
    const use = document.createElement("button");
    use.type = "button"; use.className = "use"; use.textContent = "Assign";
    use.addEventListener("click", ev => { ev.stopPropagation(); if (this.pad !== null) this.put(this.pad, id); });
    li.append(name, play, use);
    li.addEventListener("click", () => this.audition(url, true));
    li.addEventListener("dragstart", ev => {
      ev.dataTransfer.setData("application/x-melodee-sound", id);
      ev.dataTransfer.setData("text/plain", label);
      ev.dataTransfer.effectAllowed = "copy";
      document.body.classList.add("dragging-sound");
    });
    li.addEventListener("dragend", () => document.body.classList.remove("dragging-sound"));
    return li;
  },
  // A sound onto pad n; on a kit that is not one's own, an editable copy is made first (asked).
  async put(n, id) {
    if (this.kit.readOnly) {
      const name = prompt(`"${this.kit.name}" is read only. Name an editable copy to put the sound on:`, (this.kit.name + " copy").slice(0, 23));
      if (!name) return;
      try { this.kit = await this.post("/api/kits/duplicate?" + this.q({id: this.kit.id, name: name.trim()})); }
      catch (e) { alert(e.message); return; }
      sound.forget("/api/kits/audio?");
      this.bank = Math.floor(n / 16);
      location.hash = encodeURIComponent(this.kit.id);
      this.refreshRow();
    }
    this.pad = n;
    this.drawKit();
    await this.edit({sample: id});
  },
  async make() {
    const name = prompt("Name the new kit (at most 23 characters)");
    if (!name) return;
    try { this.kit = await this.post("/api/kits/new?" + this.q({name: name.trim()})); this.after(); } catch (e) { alert(e.message); }
  },
  async duplicate() {
    const name = prompt("Name the copy", (this.kit.name + " copy").slice(0, 23));
    if (!name) return;
    try { this.kit = await this.post("/api/kits/duplicate?" + this.q({id: this.kit.id, name: name.trim()})); this.after(); } catch (e) { alert(e.message); }
  },
  async rename() {
    const name = prompt("Rename the kit", this.kit.name);
    if (!name || name.trim() === this.kit.name) return;
    const old = this.kit.id;
    try {
      this.kit = await this.post("/api/kits/rename?" + this.q({id: old, name: name.trim()}));
      this.list = this.list.filter(x => x.id !== old);
      this.after();
    } catch (e) { alert(e.message); }
  },
  async remove() {
    if (!confirm(`Delete the kit "${this.kit.name}" from the card? This cannot be undone.`)) return;
    try {
      await this.post("/api/kits/delete?" + this.q({id: this.kit.id}));
      this.list = this.list.filter(x => x.id !== this.kit.id);
      this.kit = null;
      history.replaceState(null, "", location.pathname);
      this.drawKit();
      this.draw();
    } catch (e) { alert(e.message); }
  },
  after() {
    sound.forget("/api/kits/audio?");
    this.pad = null;
    this.bank = Math.max(0, this.kit.banks.findIndex(b => b.pads.length));
    location.hash = encodeURIComponent(this.kit.id);
    this.refreshRow();
    this.drawKit();
  },
  start() {
    if (!this.here) return;
    $("#kit-search").addEventListener("input", () => this.draw());
    $$("#kits .kit-side .seg").forEach(b => b.addEventListener("click", () => {
      this.show = b.dataset.show;
      $$("#kits .kit-side .seg").forEach(x => x.setAttribute("aria-pressed", x === b));
      this.draw();
    }));
    $$("#sounds .seg").forEach(b => b.addEventListener("click", () => {
      this.source = b.dataset.source;
      $$("#sounds .seg").forEach(x => x.setAttribute("aria-pressed", x === b));
      this.browse("");
    }));
    let typing = 0;
    $("#sound-search").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => this.find(), 120); });
    this.browse("");
    this.hint();
    $("#kit-new").addEventListener("click", () => this.make());
    $("#kit-dup").addEventListener("click", () => this.duplicate());
    $("#kit-rename").addEventListener("click", () => this.rename());
    $("#kit-delete").addEventListener("click", () => this.remove());
    $("#pad-clear").addEventListener("click", () => this.edit({clear: 1}));
    document.addEventListener("keydown", e => this.key(e, true));
    document.addEventListener("keyup", e => this.key(e, false));
    window.addEventListener("blur", () => { for (const n of [...(this.down || [])]) this.release(n); });
    let resized = 0;
    window.addEventListener("resize", () => { clearTimeout(resized); resized = setTimeout(() => this.kit && $$("#pad-grid .pad.used").forEach(b => this.wave(+b.dataset.n)), 150); });
    this.load().then(() => { const id = decodeURIComponent(location.hash.slice(1)); if (id) this.open(id); });
  },
};

// ---- The docs ----

function docs() {
  // On a phone the chapter list starts closed.
  const menu = $(".chapters-menu");
  if (menu && matchMedia("(max-width: 860px)").matches) menu.open = false;
  // The section in view is marked in the side list.
  const links = $$("aside .toc a");
  if (!links.length || !("IntersectionObserver" in window)) return;
  const byId = new Map(links.map(a => [decodeURIComponent(a.hash.slice(1)), a]));
  const seen = new Set();
  const watch = new IntersectionObserver(entries => {
    entries.forEach(e => e.isIntersecting ? seen.add(e.target.id) : seen.delete(e.target.id));
    const first = $$(".doc h2[id]").find(h => seen.has(h.id));
    if (!first) return;
    links.forEach(a => a.classList.toggle("here", a === byId.get(first.id)));
  }, {rootMargin: "-70px 0px -55% 0px"});
  $$(".doc h2[id]").forEach(h => watch.observe(h));
}

docs();
status().then(() => { plugins(); files.start(); kits.start(); });
setInterval(() => {
  if (sending || asking) return;
  asking = true;
  status().finally(() => { asking = false; });
}, 1500);
