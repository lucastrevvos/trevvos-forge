'use strict';

let _currentSessionId = null;

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function el(id) {
  return document.getElementById(id);
}

function escHtml(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function loadSessions() {
  const list = el('sessions-list');
  list.innerHTML = '<li class="loading">Loading…</li>';
  try {
    const sessions = await fetchJson('/sessions');
    if (!sessions.length) {
      list.innerHTML = '<li class="loading">No sessions found.</li>';
      return;
    }
    list.innerHTML = '';
    sessions.forEach(s => {
      const li = document.createElement('li');
      li.className = 'session-item';
      li.dataset.id = s.id;
      if (s.id === _currentSessionId) li.classList.add('active');
      const cmd = s.command || '—';
      const status = s.status ? `${s.status}` : '';
      const dur = s.duration_seconds != null ? ` · ${s.duration_seconds}s` : '';
      const short = s.id ? s.id.slice(-12) : s.id;
      li.innerHTML = `
        <span class="sess-id" title="${escHtml(s.id)}">${escHtml(short)}</span>
        <span class="sess-cmd">${escHtml(cmd)}</span>
        <span class="sess-meta">${escHtml(status)}${escHtml(dur)}</span>
      `;
      li.addEventListener('click', () => selectSession(s.id));
      list.appendChild(li);
    });
  } catch (err) {
    list.innerHTML = `<li class="error">Error: ${escHtml(err.message)}</li>`;
  }
}

async function selectSession(id) {
  _currentSessionId = id;

  document.querySelectorAll('.session-item').forEach(li => {
    li.classList.toggle('active', li.dataset.id === id);
  });

  el('session-details').innerHTML = '<p class="loading">Loading…</p>';
  el('artifacts-list').innerHTML = '';
  el('artifact-viewer').innerHTML = '<p class="placeholder">Select an artifact</p>';
  el('export-block').classList.add('hidden');

  try {
    const session = await fetchJson(`/sessions/${encodeURIComponent(id)}`);
    const meta = session.metadata || {};
    const fields = [
      ['ID', session.id],
      ['Command', meta.command],
      ['Status', meta.status],
      ['Mode', meta.mode],
      ['Provider', meta.provider],
      ['Model', meta.model],
      ['Duration', meta.duration_seconds != null ? `${meta.duration_seconds}s` : null],
      ['Created', meta.created_at],
    ].filter(([, v]) => v != null && v !== '');

    el('session-details').innerHTML = fields.length
      ? `<table class="meta-table">${fields.map(([k, v]) =>
          `<tr><th>${escHtml(k)}</th><td>${escHtml(String(v))}</td></tr>`
        ).join('')}</table>`
      : '<p class="empty">No metadata.</p>';

    el('export-cmd').textContent = `trevvos sessions export ${id}`;
    el('export-block').classList.remove('hidden');

    const artifacts = session.artifacts || [];
    const artList = el('artifacts-list');
    if (!artifacts.length) {
      artList.innerHTML = '<li class="empty">No artifacts.</li>';
    } else {
      artList.innerHTML = '';
      artifacts.forEach(a => {
        const li = document.createElement('li');
        li.className = 'artifact-item';
        const kb = (a.size_bytes / 1024).toFixed(1);
        li.innerHTML = `
          <span class="art-name">${escHtml(a.name)}</span>
          <span class="art-meta">${escHtml(a.kind)} · ${escHtml(kb)} KB</span>
        `;
        li.addEventListener('click', () => selectArtifact(id, a.name));
        artList.appendChild(li);
      });
    }
  } catch (err) {
    el('session-details').innerHTML = `<p class="error">Error: ${escHtml(err.message)}</p>`;
  }
}

async function selectArtifact(sessionId, name) {
  document.querySelectorAll('.artifact-item').forEach(li => {
    const nameEl = li.querySelector('.art-name');
    li.classList.toggle('active', nameEl != null && nameEl.textContent === name);
  });

  const viewer = el('artifact-viewer');
  viewer.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const artifact = await fetchJson(
      `/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(name)}`
    );
    let html = `<span class="artifact-name">${escHtml(name)}</span>`;
    if (artifact.truncated) {
      html += '<p class="warning">⚠ Content truncated (file too large).</p>';
    }
    if (artifact.kind === 'json' && artifact.content !== null && typeof artifact.content === 'object') {
      html += `<pre class="artifact-pre">${escHtml(JSON.stringify(artifact.content, null, 2))}</pre>`;
    } else {
      html += `<pre class="artifact-pre">${escHtml(String(artifact.content ?? ''))}</pre>`;
    }
    viewer.innerHTML = html;
  } catch (err) {
    viewer.innerHTML = `<p class="error">Error: ${escHtml(err.message)}</p>`;
  }
}

function copyExportCmd() {
  const cmd = el('export-cmd') ? el('export-cmd').textContent : '';
  if (navigator.clipboard) {
    navigator.clipboard.writeText(cmd).catch(() => {});
  }
}

document.addEventListener('DOMContentLoaded', loadSessions);
