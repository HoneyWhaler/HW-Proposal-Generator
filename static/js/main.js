const form = document.getElementById('proposal-form');
const submitBtn = document.getElementById('submit-btn');
const result = document.getElementById('result');

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  // Validate at least one service is selected
  const selected = form.querySelectorAll('input[name="services"]:checked');
  if (selected.length === 0) {
    showResult('error', '<h3>Select at least one service.</h3>');
    return;
  }

  setLoading(true);
  result.className = 'result hidden';

  try {
    const response = await fetch('/generate', {
      method: 'POST',
      body: new FormData(form),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || 'Something went wrong.');
    }

    showResult('success', `
      <h3>Proposal ready — ${escapeHtml(data.prospect)}</h3>
      <p><a href="${data.drive_link}" target="_blank" rel="noopener">Open in Google Drive →</a></p>
    `);

  } catch (err) {
    showResult('error', `<h3>Error</h3><p>${escapeHtml(err.message)}</p>`);
  } finally {
    setLoading(false);
  }
});

function setLoading(loading) {
  submitBtn.disabled = loading;
  submitBtn.innerHTML = loading
    ? '<span class="spinner"></span>Generating…'
    : 'Generate proposal';
}

function showResult(type, html) {
  result.className = `result ${type}`;
  result.innerHTML = html;
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
