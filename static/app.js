/* ===================================
   GODSPEED RETAIL INTELLIGENCE SYSTEM
   Frontend JS
   =================================== */

// ─── TOASTS ───
function showToast(message, type = 'default') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4500);
}

async function postJSON(url, body) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    const data = await res.json().catch(() => ({ success: false, error: `Server error (${res.status})` }));
    return data;
  } catch (e) {
    return { success: false, error: 'Network error — check your connection' };
  }
}

// A store is identified by its sheet row + name (names alone are not unique).
function storeOf(el) {
  return { row: Number(el.dataset.row), name: el.dataset.store };
}

function markPitched(row) {
  document.querySelectorAll(`tr[data-row="${row}"] .status-badge`).forEach(badge => {
    if (['Not Contacted', 'New Lead'].includes(badge.textContent.trim())) {
      badge.className = 'badge badge-pitched status-badge';
      badge.textContent = 'Pitched';
    }
  });
}

// ─── REORDER ───
async function sendReorder(btn) {
  const store = storeOf(btn);
  if (!confirm(`Log a reorder check-in for ${store.name}?`)) return;
  const data = await postJSON('/api/send-reorder', { row: store.row, store_name: store.name });
  showToast(data.success ? `✅ ${data.message}` : `❌ ${data.error}`, data.success ? 'success' : 'error');
}

// ─── BULK SELECT ───
const selectedStores = new Map();   // row -> name

function initBulkSelect() {
  const selectAll = document.getElementById('select-all');
  if (!selectAll) return;

  const toggle = (cb, on) => {
    cb.checked = on;
    if (on) selectedStores.set(cb.dataset.row, cb.dataset.store);
    else selectedStores.delete(cb.dataset.row);
  };

  selectAll.addEventListener('change', e => {
    document.querySelectorAll('.store-checkbox').forEach(cb => toggle(cb, e.target.checked));
    updateBulkBar();
  });
  document.querySelectorAll('.store-checkbox').forEach(cb => {
    cb.addEventListener('change', e => { toggle(cb, e.target.checked); updateBulkBar(); });
  });
}

function updateBulkBar() {
  const bar = document.getElementById('bulk-bar');
  const count = document.getElementById('bulk-count');
  if (!bar || !count) return;
  bar.classList.toggle('show', selectedStores.size > 0);
  count.textContent = `${selectedStores.size} store${selectedStores.size === 1 ? '' : 's'} selected`;
}

function clearSelection() {
  selectedStores.clear();
  document.querySelectorAll('.store-checkbox').forEach(cb => (cb.checked = false));
  const all = document.getElementById('select-all');
  if (all) all.checked = false;
  updateBulkBar();
}

async function bulkPitch() {
  if (selectedStores.size === 0) return;
  const stores = Array.from(selectedStores, ([row, name]) => ({ row: Number(row), name }));
  if (!confirm(`Log an Instagram DM pitch for ${stores.length} store${stores.length === 1 ? '' : 's'}?`)) return;
  const data = await postJSON('/api/bulk-pitch', { stores, channel: 'Instagram DM' });
  if (data.success) {
    showToast(`✅ ${data.message}`, 'success');
    stores.forEach(s => markPitched(s.row));
    clearSelection();
  } else {
    showToast(`❌ ${data.error}`, 'error');
  }
}

// ─── PITCH MODAL ───
function openPitchModal(btn) {
  const modal = document.getElementById('pitch-modal');
  if (!modal) return;
  const store = storeOf(btn);
  document.getElementById('modal-store-name').textContent = store.name;
  document.getElementById('modal-store-input').value = store.name;
  document.getElementById('modal-row-input').value = store.row;

  const links = document.getElementById('modal-links');
  links.textContent = '';
  const add = (label, href) => {
    const a = document.createElement('a');
    a.textContent = label;
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.className = 'table-link';
    if (links.childNodes.length) links.append(' · ');
    links.append(a);
  };
  const handle = (btn.dataset.instagram || '').replace(/^@/, '');
  if (handle) add(`open @${handle}`, `https://instagram.com/${encodeURIComponent(handle)}`);
  if (btn.dataset.email) add(`email ${btn.dataset.email}`, `mailto:${btn.dataset.email}`);
  if (!links.childNodes.length) links.textContent = 'no Instagram or email on file for this store.';
  document.getElementById('modal-channel').value = handle ? 'Instagram DM' : (btn.dataset.email ? 'Email' : 'Phone');
  modal.classList.add('show');
}

function closePitchModal() {
  const modal = document.getElementById('pitch-modal');
  if (modal) modal.classList.remove('show');
}

async function copyPitch() {
  const text = document.getElementById('modal-message').value;
  try {
    await navigator.clipboard.writeText(text);
    showToast('Message copied', 'success');
  } catch (e) {
    showToast('Could not copy — select the text and copy it manually', 'error');
  }
}

async function submitPitch(e) {
  e.preventDefault();
  const row = Number(document.getElementById('modal-row-input').value);
  const name = document.getElementById('modal-store-input').value;
  const data = await postJSON('/api/send-pitch', {
    row,
    store_name: name,
    channel: document.getElementById('modal-channel').value,
    message: document.getElementById('modal-message').value
  });
  if (data.success) {
    showToast(`✅ ${data.message}`, 'success');
    markPitched(row);
    closePitchModal();
  } else {
    showToast(`❌ ${data.error}`, 'error');
  }
}

// ─── REVIEW (approve / reject a store) ───
async function reviewStore(btn, decision) {
  const store = storeOf(btn);
  btn.disabled = true;
  const data = await postJSON('/api/review', { row: store.row, store_name: store.name, decision });
  if (!data.success) {
    btn.disabled = false;
    showToast(`❌ ${data.error}`, 'error');
    return;
  }
  showToast(decision === 'approve' ? `✅ ${store.name} added to qualified leads` : `${store.name} rejected`, 'success');
  const tr = btn.closest('tr');
  if (tr) tr.remove();
}

// ─── VERIFY JOB ───
let jobTimer = null;
let onJobDone = null;

async function startJob(btn) {
  if (btn) btn.disabled = true;
  const data = await postJSON('/api/job/start', {});
  if (!data.success) {
    if (btn) btn.disabled = false;
    showToast(`❌ ${data.error}`, 'error');
    return;
  }
  watchJob();
}

async function stopJob() {
  await postJSON('/api/job/stop');
  showToast('Stopping after the checks already in flight…');
}

function watchJob() {
  const panel = document.getElementById('job-panel');
  if (!panel || jobTimer) return;
  panel.classList.add('show');
  jobTimer = setInterval(pollJob, 1500);
  pollJob();
}

async function pollJob() {
  let data;
  try {
    data = await (await fetch('/api/job/status')).json();
  } catch (e) {
    return;                       // transient — keep polling
  }
  document.getElementById('job-message').textContent = data.error ? `Failed: ${data.error}` : data.message;
  const fill = document.getElementById('job-bar-fill');
  fill.style.width = data.total ? `${Math.round((data.done / data.total) * 100)}%` : (data.running ? '8%' : '100%');
  document.getElementById('job-stop').style.display = data.running ? '' : 'none';
  if (!data.running) {
    clearInterval(jobTimer);
    jobTimer = null;
    if (data.error) {
      showToast(`❌ ${data.error}`, 'error');
      document.querySelectorAll('button[onclick^="startJob"]').forEach(b => (b.disabled = false));
    } else if (onJobDone) {
      showToast(`✅ ${data.message}`, 'success');
      setTimeout(onJobDone, 1200);
    }
  }
}

// ─── SCRAPER (queued — runs outside the dashboard) ───
async function startScraper() {
  const data = await postJSON('/api/scraper/start');
  showToast(data.message || data.error || 'Scrape queued', data.success ? 'success' : 'error');
}

// ─── INIT ───
document.addEventListener('DOMContentLoaded', () => {
  initBulkSelect();

  const pitchForm = document.getElementById('pitch-form');
  if (pitchForm) pitchForm.addEventListener('submit', submitPitch);

  const overlay = document.getElementById('pitch-modal');
  if (overlay) {
    overlay.addEventListener('click', e => { if (e.target === overlay) closePitchModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closePitchModal(); });
  }

  const panel = document.getElementById('job-panel');
  if (panel && panel.dataset.running === 'true') watchJob();
});
