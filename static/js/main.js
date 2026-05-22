const form = document.getElementById('proposal-form');
const submitBtn = document.getElementById('submit-btn');
const result = document.getElementById('result');

const STEPS = {
  diagnosing: 'Researching prospect website…',
  writing:    'Writing proposal content…',
  building:   'Building the deck…',
  uploading:  'Uploading to Google Drive…',
  done:       'Done.',
  error:      'Something went wrong.',
};

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  const selected = form.querySelectorAll('input[name="services"]:checked');
  if (selected.length === 0) {
    showResult('error', '<p>Select at least one service before generating.</p>');
    return;
  }

  setLoading(true);
  showProgress('diagnosing', STEPS.diagnosing);

  try {
    const response = await fetch('/generate', {
      method: 'POST',
      body: new FormData(form),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Unknown error.' }));
      throw new Error(err.detail || 'Generation failed.');
    }

    // Read the SSE stream
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // Returns true if the stream should stop (done or error event handled)
    const handlePayload = (payload) => {
      if (payload.step === 'error') {
        showResult('error', `<h3>Error</h3><p>${escapeHtml(payload.message)}</p>`);
        setLoading(false);
        return true;
      }
      if (payload.step === 'done') {
        const { drive_link, prospect } = payload.data;
        showResult('success', `
          <h3>${escapeHtml(prospect)} — proposal ready</h3>
          <p><a href="${drive_link}" target="_blank" rel="noopener">Open in Google Drive →</a></p>
        `);
        setLoading(false);
        return true;
      }
      showProgress(payload.step, payload.message);
      return false;
    };

    const processLines = (lines) => {
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const payload = JSON.parse(line.slice(6));
          if (handlePayload(payload)) return true;
        } catch (e) {
          // Partial or malformed line — skip and continue
          console.warn('SSE parse skip:', line);
        }
      }
      return false;
    };

    while (true) {
      const { value, done } = await reader.read();

      if (done) {
        // Flush any content left in the buffer (e.g. final "done" event with no trailing newline)
        if (buffer.trim()) processLines([buffer.trim()]);
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer

      if (processLines(lines)) return;
    }

  } catch (err) {
    showResult('error', `<h3>Error</h3><p>${escapeHtml(err.message)}</p>`);
    setLoading(false);
  }
});

function setLoading(loading) {
  submitBtn.disabled = loading;
  submitBtn.innerHTML = loading
    ? '<span class="spinner"></span>Generating…'
    : 'Generate proposal';
}

function showProgress(step, message) {
  result.className = 'result progress';
  result.innerHTML = `
    <div class="progress-steps">
      ${Object.entries(STEPS)
        .filter(([key]) => !['done', 'error'].includes(key))
        .map(([key, label]) => {
          const steps = Object.keys(STEPS).filter(k => !['done', 'error'].includes(k));
          const currentIndex = steps.indexOf(step);
          const thisIndex = steps.indexOf(key);
          let state = 'pending';
          if (thisIndex < currentIndex) state = 'done';
          if (thisIndex === currentIndex) state = 'active';
          return `<div class="progress-step ${state}">
            <span class="step-dot"></span>
            <span class="step-label">${label}</span>
          </div>`;
        }).join('')}
    </div>
  `;
}

function showResult(type, html) {
  result.className = `result ${type}`;
  result.innerHTML = html;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
