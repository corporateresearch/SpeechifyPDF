(function() {
  if (window.speechifyOverlay) return; // already loaded
  
  const overlay = document.createElement('div');
  overlay.id = 'speechify-overlay';
  Object.assign(overlay.style, {
    position: 'fixed',
    bottom: '20px',
    right: '20px',
    width: '400px',
    backgroundColor: '#0f1e33',
    color: '#e8ecf4',
    border: '1px solid #00e0ff',
    borderRadius: '12px',
    padding: '20px',
    zIndex: '999999',
    fontFamily: 'sans-serif',
    boxShadow: '0 10px 30px rgba(0,0,0,0.5)'
  });

  const title = document.createElement('div');
  title.innerText = 'Speechify Reader';
  title.style.fontWeight = 'bold';
  title.style.marginBottom = '10px';
  title.style.color = '#00e0ff';
  overlay.appendChild(title);

  const content = document.createElement('div');
  content.style.fontSize = '16px';
  content.style.lineHeight = '1.5';
  content.innerText = 'Extracting text...';
  overlay.appendChild(content);

  const controls = document.createElement('div');
  controls.style.marginTop = '15px';
  controls.style.display = 'flex';
  controls.style.gap = '10px';
  
  const playBtn = document.createElement('button');
  playBtn.innerText = 'Pause';
  playBtn.style.padding = '5px 10px';
  playBtn.style.cursor = 'pointer';
  playBtn.style.background = '#00e0ff';
  playBtn.style.color = '#000';
  playBtn.style.border = 'none';
  playBtn.style.borderRadius = '4px';
  
  const closeBtn = document.createElement('button');
  closeBtn.innerText = 'Close';
  closeBtn.style.padding = '5px 10px';
  closeBtn.style.cursor = 'pointer';
  closeBtn.style.background = 'transparent';
  closeBtn.style.color = '#fff';
  closeBtn.style.border = '1px solid #fff';
  closeBtn.style.borderRadius = '4px';

  closeBtn.onclick = () => {
    if (window.speechifyAudio) {
        window.speechifyAudio.pause();
        window.speechifyAudio = null;
    }
    overlay.remove();
    window.speechifyOverlay = null;
  };

  controls.appendChild(playBtn);
  controls.appendChild(closeBtn);
  overlay.appendChild(controls);
  
  document.body.appendChild(overlay);
  window.speechifyOverlay = overlay;

  let docData = null;
  let currentSentenceIndex = 0;
  let isPlaying = false;

  // Extract text
  const sel = window.getSelection().toString();
  const text = sel.trim() ? sel : document.body.innerText;
  
  fetch('http://127.0.0.1:8000/api/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text, title: document.title })
  })
  .then(r => r.json())
  .then(data => {
    if (data.detail) {
        content.innerText = 'Error: ' + JSON.stringify(data.detail);
        return;
    }
    docData = data;
    content.innerText = 'Ready to play.';
    playNextSentence();
  })
  .catch(e => {
    content.innerText = 'Error connecting to SpeechifyPDF local server. Make sure it is running on port 8000.';
  });

  function playNextSentence() {
    if (!docData || currentSentenceIndex >= docData.sentence_count) {
      content.innerText = 'Finished reading.';
      playBtn.style.display = 'none';
      return;
    }
    content.innerText = 'Loading...';
    
    fetch(`http://127.0.0.1:8000/api/tts/${docData.doc_id}/${currentSentenceIndex}?voice=af_bella&speed=1.0`)
    .then(r => r.json())
    .then(data => {
      window.speechifyAudio = new Audio(data.audio);
      isPlaying = true;
      playBtn.innerText = 'Pause';
      
      content.innerHTML = '';
      const spans = [];
      
      data.words.forEach(wInfo => {
        const span = document.createElement('span');
        span.innerText = wInfo.word;
        span.style.marginRight = '4px';
        span.style.display = 'inline-block';
        content.appendChild(span);
        spans.push({span: span, start: wInfo.start, end: wInfo.end});
      });
      
      window.speechifyAudio.ontimeupdate = () => {
        const t = window.speechifyAudio.currentTime;
        spans.forEach(w => {
          if (t >= w.start && t <= w.end) {
            w.span.style.backgroundColor = '#00e0ff';
            w.span.style.color = '#000';
            w.span.style.borderRadius = '2px';
          } else {
            w.span.style.backgroundColor = 'transparent';
            w.span.style.color = '#e8ecf4';
          }
        });
      };
      
      window.speechifyAudio.onended = () => {
        currentSentenceIndex++;
        playNextSentence();
      };
      
      window.speechifyAudio.play();
    })
    .catch(e => {
        content.innerText = 'Error loading audio.';
    });
  }

  playBtn.onclick = () => {
    if (!window.speechifyAudio) return;
    if (isPlaying) {
      window.speechifyAudio.pause();
      isPlaying = false;
      playBtn.innerText = 'Play';
    } else {
      window.speechifyAudio.play();
      isPlaying = true;
      playBtn.innerText = 'Pause';
    }
  };

})();
