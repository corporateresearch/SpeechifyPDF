/* ================================================================
   Kokoro PDF Reader — app.js
   Vanilla JS: landing, upload, reader, playback + word highlighting
   ================================================================ */

// ---------- State ----------
let currentDoc = null;
let voices = [];
let defaultVoice = 'af_heart';
let selectedVoice = 'af_heart';
let selectedSpeed = 1.0;

let audio = new Audio();
audio.preload = 'auto';
let playing = false;
let sid = -1;
let wid = -1;
let activeWords = [];
let loading = false;
let error = null;
let cache = new Map();
let inflight = new Map();
let curData = null;
let rafId = 0;
let wordCursor = 0;
let genId = 0;

// ---------- DOM refs ----------
const $ = (id) => document.getElementById(id);
const els = {
  landing:     $('landing'),
  reader:      $('reader'),
  dropzone:    $('dropzone'),
  fileInput:   $('file-input'),
  dzContent:   $('dz-content'),
  uploadError: $('upload-error'),
  btnLibrary:  $('btn-library'),
  docTitle:    $('doc-title'),
  voiceSelect: $('voice-select'),
  speedInput:  $('speed-input'),
  speedVal:    $('speed-val'),
  progressBar: $('progress-bar'),
  prose:       $('prose'),
  btnPlay:     $('btn-play'),
  playIcon:    $('play-icon'),
  playText:    $('play-text'),
  statusText:  $('status-text'),
  btnReadUrl:  $('btn-read-url'),
  urlInput:    $('url-input'),
  btnReadText: $('btn-read-text'),
  textInput:   $('text-input'),
};

// ---------- Init: fetch voices ----------
(async function init() {
  try {
    const res = await fetch('/api/voices');
    const data = await res.json();
    voices = data.voices;
    defaultVoice = data.default;
    selectedVoice = defaultVoice;
    els.voiceSelect.innerHTML = voices
      .map(v => `<option value="${v.id}">${v.label}</option>`)
      .join('');
    els.voiceSelect.value = selectedVoice;
  } catch (e) {
    console.warn('Could not fetch voices:', e);
  }
})();

// =====================================================================
// LANDING — file upload / drag-drop
// =====================================================================
els.dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  els.dropzone.classList.add('drag');
});
els.dropzone.addEventListener('dragleave', () => {
  els.dropzone.classList.remove('drag');
});
els.dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  els.dropzone.classList.remove('drag');
  handleFile(e.dataTransfer.files?.[0]);
});
els.fileInput.addEventListener('change', (e) => {
  handleFile(e.target.files?.[0]);
});

async function handleFile(file) {
  if (!file) return;
  els.dzContent.innerHTML = `
    <div class="dz-icon-wrap">
      <svg class="dz-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="animation: pulse-dot 1.2s ease-in-out infinite">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 6v6l4 2" stroke-linecap="round"/>
      </svg>
    </div>
    <span class="dz-main">Reading PDF…</span>
    <span class="dz-sub">Extracting text and reflowing paragraphs</span>
  `;
  els.uploadError.textContent = '';

  const form = new FormData();
  form.append('file', file);

  try {
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
      } catch {}
      throw new Error(detail);
    }
    const data = await res.json();
    openReader(data);
  } catch (e) {
    els.uploadError.textContent = e.message;
    resetDropzone();
  }
}

function resetDropzone() {
  els.dzContent.innerHTML = `
    <div class="dz-icon-wrap">
      <svg class="dz-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 16V4m0 0l-4 4m4-4l4 4" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M2 17l.621 2.485A2 2 0 004.561 21h14.878a2 2 0 001.94-1.515L22 17" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <span class="dz-main">Drop a PDF here</span>
    <span class="dz-sub">or click to choose a file</span>
  `;
}

// Handle Text & URL Inputs
els.btnReadUrl.addEventListener('click', async () => {
  const url = els.urlInput.value.trim();
  if (!url) return;
  els.uploadError.textContent = '';
  els.btnReadUrl.textContent = 'Loading...';
  try {
    const res = await fetch('/api/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url })
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { const body = await res.json(); if (body.detail) detail = body.detail; } catch {}
      throw new Error(detail);
    }
    const data = await res.json();
    openReader(data);
  } catch (e) {
    els.uploadError.textContent = e.message;
  } finally {
    els.btnReadUrl.textContent = 'Read URL';
  }
});

els.btnReadText.addEventListener('click', async () => {
  const text = els.textInput.value.trim();
  if (!text) return;
  els.uploadError.textContent = '';
  els.btnReadText.textContent = 'Loading...';
  try {
    const res = await fetch('/api/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { const body = await res.json(); if (body.detail) detail = body.detail; } catch {}
      throw new Error(detail);
    }
    const data = await res.json();
    openReader(data);
  } catch (e) {
    els.uploadError.textContent = e.message;
  } finally {
    els.btnReadText.textContent = 'Read Text';
  }
});

// =====================================================================
// READER — open / close
// =====================================================================
function openReader(doc) {
  currentDoc = doc;
  els.landing.style.display = 'none';
  els.reader.style.display = 'flex';
  els.docTitle.textContent = doc.title;
  els.docTitle.title = doc.title;

  // Reset player state
  sid = -1; wid = -1; playing = false;
  activeWords = []; cache.clear(); inflight.clear();
  curData = null; genId++;

  renderProse();
  updateStatus();
}

els.btnLibrary.addEventListener('click', () => {
  stopPlayback();
  currentDoc = null;
  els.reader.style.display = 'none';
  els.landing.style.display = '';
  resetDropzone();
  els.uploadError.textContent = '';
});

els.voiceSelect.addEventListener('change', (e) => {
  selectedVoice = e.target.value;
  resetPlayerState();
});
els.speedInput.addEventListener('input', (e) => {
  selectedSpeed = parseFloat(e.target.value);
  els.speedVal.textContent = selectedSpeed.toFixed(2) + '×';
  resetPlayerState();
});

// =====================================================================
// PLAYBACK ENGINE
// =====================================================================
function stopPlayback() {
  playing = false;
  audio.pause();
  audio.removeAttribute('src');
  audio.load();
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  sid = -1; wid = -1;
  activeWords = [];
  cache.clear(); inflight.clear();
  curData = null;
  updateStatus();
}

function resetPlayerState() {
  genId++;
  cache.clear(); inflight.clear();
  curData = null; wordCursor = 0;
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  audio.pause();
  audio.removeAttribute('src');
  audio.load();
  playing = false;
  sid = -1; wid = -1;
  activeWords = [];
  error = null;
  updateStatus();
  renderProse();
}

function ensure(index) {
  if (!currentDoc || index < 0 || index >= currentDoc.sentence_count) return null;
  if (cache.has(index)) return cache.get(index);
  if (inflight.has(index)) return inflight.get(index);
  const myGen = genId;
  const url = `/api/tts/${currentDoc.doc_id}/${index}?voice=${encodeURIComponent(selectedVoice)}&speed=${encodeURIComponent(selectedSpeed)}`;
  const p = fetch(url)
    .then(async (r) => {
      if (!r.ok) throw new Error('API Error');
      return r.json();
    })
    .then((data) => {
      if (myGen === genId) cache.set(index, data);
      inflight.delete(index);
      return data;
    })
    .catch((e) => {
      inflight.delete(index);
      throw e;
    });
  inflight.set(index, p);
  return p;
}

async function playFrom(index) {
  if (!currentDoc) return;
  index = Math.max(0, Math.min(index, currentDoc.sentence_count - 1));
  const myGen = genId;
  error = null;
  sid = index; wid = -1;
  playing = true;
  loading = !cache.has(index);
  updateStatus();
  renderProse();

  let data;
  try {
    data = await ensure(index);
  } catch (e) {
    error = "Couldn't synthesize audio";
    playing = false; loading = false;
    updateStatus();
    return;
  }
  if (myGen !== genId || sid !== index) return;
  loading = false;
  updateStatus();

  // Prefetch next sentence
  const next = ensure(index + 1);
  if (next && typeof next.catch === 'function') next.catch(() => {});

  if (!data || !data.words.length || data.duration === 0) {
    activeWords = [];
    advance(index);
    return;
  }

  curData = data;
  wordCursor = 0;
  activeWords = data.words;
  audio.src = data.audio;
  audio.onended = () => advance(index);
  try { await audio.play(); } catch {}
  startRaf();
  renderProse();
}

function advance(fromIndex) {
  const next = fromIndex + 1;
  if (!currentDoc || next >= currentDoc.sentence_count) {
    if (rafId) cancelAnimationFrame(rafId);
    playing = false;
    updateStatus();
    return;
  }
  playFrom(next);
}

function togglePlay() {
  if (playing) {
    audio.pause();
    if (rafId) cancelAnimationFrame(rafId);
    playing = false;
    updateStatus();
  } else {
    if (audio.src && curData) {
      playing = true;
      audio.play().catch(() => {});
      startRaf();
      updateStatus();
    } else {
      playFrom(sid >= 0 ? sid : 0);
    }
  }
}

els.btnPlay.addEventListener('click', togglePlay);

// Keyboard controls
window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT') return;
  if (!currentDoc) return;
  if (e.code === 'Space') {
    e.preventDefault();
    togglePlay();
  } else if (e.code === 'ArrowRight') {
    playFrom((sid < 0 ? -1 : sid) + 1);
  } else if (e.code === 'ArrowLeft') {
    playFrom(Math.max(0, (sid < 0 ? 0 : sid) - 1));
  }
});

// ---------- rAF word tracker ----------
function startRaf() {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(tick);
}

function tick() {
  if (!curData) return;
  const t = audio.currentTime;
  const words = curData.words;
  let i = wordCursor;
  if (i >= words.length || (i > 0 && t < words[i].start)) i = 0;
  let active = i > 0 ? i - 1 : -1;
  for (; i < words.length; i++) {
    if (words[i].start <= t) active = i;
    else break;
  }
  wordCursor = Math.max(0, active);
  if (wid !== active) {
    wid = active;
    updateHighlight();
  }
  rafId = requestAnimationFrame(tick);
}

function updateHighlight() {
  const sentEl = document.getElementById('s-' + sid);
  if (!sentEl) return;
  sentEl.querySelectorAll('.word').forEach(el => el.classList.remove('lit'));
  const wEl = sentEl.querySelector(`[data-w="${wid}"]`);
  if (wEl) {
    wEl.classList.add('lit');
    wEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}

// Global handlers for inline onclick
window.seekWord = function (index, wordIndex) {
  const data = cache.get(index);
  if (sid === index && curData && data && data.words[wordIndex]) {
    audio.currentTime = data.words[wordIndex].start + 0.001;
    wordCursor = wordIndex;
    if (!playing) {
      playing = true;
      audio.play().catch(() => {});
      startRaf();
      updateStatus();
    }
  } else {
    playFrom(index);
  }
};
window.playFromGlobal = function (index) {
  playFrom(index);
};

// =====================================================================
// RENDER
// =====================================================================
function renderProse() {
  if (!currentDoc) return;
  els.prose.innerHTML = '';

  currentDoc.paragraphs.forEach((para) => {
    const p = document.createElement('p');
    para.forEach((sIdx) => {
      const isAct = sIdx === sid;
      const text = currentDoc.sentences[sIdx];

      const span = document.createElement('span');
      span.id = 's-' + sIdx;
      span.className = 'sentence' + (isAct ? ' active' : '');

      if (isAct && activeWords && activeWords.length) {
        let html = '';
        activeWords.forEach((w) => {
          const litClass = w.i === wid ? ' lit' : '';
          html += `<span><span data-w="${w.i}" class="word${litClass}" onclick="event.stopPropagation(); seekWord(${sIdx}, ${w.i})">${w.text}</span> </span>`;
        });
        span.innerHTML = html;
      } else {
        span.textContent = text + ' ';
        span.title = 'Click to read from here';
        span.onclick = () => playFromGlobal(sIdx);
      }
      p.appendChild(span);
    });
    els.prose.appendChild(p);
  });

  // Update progress bar
  const progress = currentDoc.sentence_count
    ? Math.min(100, Math.round(((sid + 1) / currentDoc.sentence_count) * 100))
    : 0;
  els.progressBar.style.width = progress + '%';
}

function updateStatus() {
  els.playIcon.textContent = playing ? '❚❚' : '►';
  els.playText.textContent = playing ? 'Pause' : sid < 0 ? 'Read aloud' : 'Resume';

  if (error) {
    els.statusText.innerHTML = `<span class="status-error">${error}</span>`;
  } else if (loading) {
    els.statusText.innerHTML = `<span class="status-loading">Synthesizing…</span>`;
  } else if (sid >= 0 && currentDoc) {
    els.statusText.innerHTML = `Sentence ${sid + 1} of ${currentDoc.sentence_count}`;
  } else if (currentDoc) {
    els.statusText.innerHTML = `${currentDoc.sentence_count} sentences · press space to start`;
  } else {
    els.statusText.innerHTML = 'Press space to start';
  }
}
