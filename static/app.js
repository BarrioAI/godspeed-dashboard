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
  showToast(data.success ? `${data.message}` : `${data.error}`, data.success ? 'success' : 'error');
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
    showToast(`${data.message}`, 'success');
    stores.forEach(s => markPitched(s.row));
    clearSelection();
  } else {
    showToast(`${data.error}`, 'error');
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
  const brands = (btn.dataset.brands || '').split(',').map(b => b.trim()).filter(Boolean);
  const message = document.getElementById('modal-message');
  const hint = document.getElementById('modal-message-hint');
  const touch = Number(btn.dataset.followup || 0);
  const title = document.getElementById('pitch-modal-title');
  const template = document.getElementById('modal-template-input');
  if (title) title.textContent = touch ? 'Log a follow-up' : 'Log a pitch';
  if (template) template.value = touch ? `Follow-up ${touch}` : 'First pitch';
  if (message) message.value = touch ? draftFollowUp(store.name, brands) : draftPitch(store.name, brands);
  if (hint) hint.textContent = touch ? 'Follow-up message. Edit it before you send.' : (brands.length
    ? `Written from what ${store.name} stocks on its own site. Edit it before you send.`
    : 'Starter message. Edit it before you send.');
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
    message: document.getElementById('modal-message').value,
    template_used: (document.getElementById('modal-template-input') || {}).value || ''
  });
  if (data.success) {
    showToast(`${data.message}`, 'success');
    markPitched(row);
    closePitchModal();
  } else {
    showToast(`${data.error}`, 'error');
  }
}

// ─── REVIEW (approve / reject a store) ───
async function reviewStore(btn, decision) {
  const store = storeOf(btn);
  btn.disabled = true;
  const data = await postJSON('/api/review', { row: store.row, store_name: store.name, decision });
  if (!data.success) {
    btn.disabled = false;
    showToast(`${data.error}`, 'error');
    return;
  }
  showToast(decision === 'approve' ? `${store.name} added to qualified leads` : `${store.name} rejected`, 'success');
  const tr = btn.closest('tr');
  if (tr) tr.remove();
}

// ─── VERIFY JOB ───
let jobTimer = null;
let onJobDone = null;

async function startJob(btn, name = 'verify') {
  if (name === 'sync' && !confirm('Update the STORES tab from the leads file in this deploy?')) return;
  if (btn) btn.disabled = true;
  const data = await postJSON('/api/job/start', { job: name });
  if (!data.success) {
    if (btn) btn.disabled = false;
    showToast(`${data.error}`, 'error');
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
  document.getElementById('job-stop').style.display = data.running && data.name === 'verify' ? '' : 'none';
  if (!data.running) {
    clearInterval(jobTimer);
    jobTimer = null;
    if (data.error) {
      showToast(`${data.error}`, 'error');
      document.querySelectorAll('button[onclick^="startJob"]').forEach(b => (b.disabled = false));
    } else if (onJobDone) {
      showToast(`${data.message}`, 'success');
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


// ─── REPLIES ───
function openReplyModal(btn) {
  const modal = document.getElementById('reply-modal');
  if (!modal) return;
  const store = storeOf(btn);
  document.getElementById('reply-store-name').textContent = store.name;
  document.getElementById('reply-store-input').value = store.name;
  document.getElementById('reply-row-input').value = store.row;
  document.getElementById('reply-text').value = '';
  document.getElementById('reply-outcome').value = 'interested';
  const channel = document.getElementById('reply-channel');
  const last = btn.dataset.channel || '';
  if ([...channel.options].some(o => o.value === last)) channel.value = last;
  modal.classList.add('show');
  document.getElementById('reply-text').focus();
}

function closeReplyModal() {
  const modal = document.getElementById('reply-modal');
  if (modal) modal.classList.remove('show');
}

async function submitReply(e) {
  e.preventDefault();
  const row = Number(document.getElementById('reply-row-input').value);
  const data = await postJSON('/api/log-reply', {
    row,
    store_name: document.getElementById('reply-store-input').value,
    outcome: document.getElementById('reply-outcome').value,
    channel: document.getElementById('reply-channel').value,
    reply: document.getElementById('reply-text').value
  });
  if (data.success) {
    showToast(data.message, 'success');
    closeReplyModal();
    if (document.querySelector('.reply-quote, [data-followup]')) setTimeout(() => window.location.reload(), 600);
    document.querySelectorAll(`tr[data-row="${row}"] .status-badge`).forEach(badge => {
      badge.textContent = data.badge;
      badge.className = `badge badge-${data.badge.toLowerCase().replace(/ /g, '')} status-badge`;
    });
  } else {
    showToast(data.error, 'error');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('reply-form');
  if (form) form.addEventListener('submit', submitReply);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeReplyModal(); });
});

function draftFollowUp(name, brands) {
  const fit = brands.length ? ` It would sit well next to ${brands[0]} in your store.` : '';
  return `Hey ${name}, following up on my note about Godspeed.${fit} Happy to send the line sheet and wholesale pricing whenever works. Who is the best person to talk to about buying?`;
}

// ─── PITCH DRAFT ───
// A first message built from the peer brands the store's own site shows.
function draftPitch(name, brands) {
  const list = brands.length > 1 ? brands.slice(0, -1).join(', ') + ' and ' + brands[brands.length - 1] : brands[0];
  const opener = brands.length
    ? `Hey ${name}, saw you carry ${list}. Godspeed sits right next to those on the rack.`
    : `Hey ${name}, we're Godspeed, a premium streetwear brand out of New York, and your store looks like the right home for it.`;
  return `${opener} We're opening a few wholesale accounts in your area. Can I send over the line sheet?`;
}

// ─── COMMAND BAR (Cmd/Ctrl+K or /) ───
(function () {
  const PAGES = [
    ['Overview', '/'], ['Leads: qualified', '/leads'], ['Leads: A tier', '/leads?tier=A-Tier'],
    ['Leads: stock peer brands', '/leads?brand=any'], ['Leads: needs review', '/leads?view=review'],
    ['Leads: contact to check', '/leads?contact=problem'], ['Outreach', '/outreach'], ['Retailers', '/retailers'],
    ['Orders', '/orders'], ['Data quality', '/quality'], ['Add store', '/add-store'],
    ['Download call list (CSV)', '/export/leads.csv'],
  ];
  let items = [], active = 0, timer = null, seq = 0;
  const el = id => document.getElementById(id);

  function render() {
    const box = el('cmd-results');
    box.textContent = '';
    items.forEach((item, i) => {
      const a = document.createElement('a');
      a.href = item.href;
      a.className = 'cmd-item' + (i === active ? ' active' : '');
      const main = document.createElement('span');
      main.className = 'cmd-main';
      main.textContent = item.label;
      const meta = document.createElement('span');
      meta.className = 'cmd-meta';
      meta.textContent = item.meta;
      a.append(main, meta);
      a.addEventListener('mousemove', () => { if (active !== i) { active = i; render(); } });
      box.append(a);
    });
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'cmd-empty';
      empty.textContent = 'Nothing matches.';
      box.append(empty);
    }
  }

  function pagesFor(q) {
    return PAGES.filter(p => p[0].toLowerCase().includes(q)).map(p => ({ label: p[0], meta: 'Page', href: p[1] }));
  }

  function search(q) {
    q = q.trim().toLowerCase();
    items = pagesFor(q).slice(0, q ? 4 : 12);
    active = 0;
    render();
    clearTimeout(timer);
    if (q.length < 2) return;
    const mine = ++seq;
    timer = setTimeout(async () => {
      try {
        const res = await fetch('/api/search?q=' + encodeURIComponent(q));
        const data = await res.json();
        if (mine !== seq) return;
        const stores = (data.results || []).map(s => ({
          label: s.name,
          meta: [s.city, s.state].filter(Boolean).join(', ') + ' · ' +
            (s.customer ? 'Retailer' : s.bucket === 'qualified' ? `${s.tier || 'C'} tier ${s.score}` : s.bucket),
          href: '/leads?view=all&q=' + encodeURIComponent(s.name),
        }));
        items = stores.concat(pagesFor(q).slice(0, 4));
        active = 0;
        render();
      } catch (e) { /* keep the page results */ }
    }, 140);
  }

  function open() {
    const overlay = el('cmd');
    if (!overlay) return;
    overlay.classList.add('show');
    el('cmd-input').value = '';
    search('');
    el('cmd-input').focus();
  }
  function close() { const overlay = el('cmd'); if (overlay) overlay.classList.remove('show'); }

  document.addEventListener('DOMContentLoaded', () => {
    if (!el('cmd')) return;
    el('cmd-trigger').addEventListener('click', open);
    el('cmd').addEventListener('click', e => { if (e.target === el('cmd')) close(); });
    el('cmd-input').addEventListener('input', e => search(e.target.value));
    el('cmd-input').addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, items.length - 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
      else if (e.key === 'Enter' && items[active]) { e.preventDefault(); window.location.href = items[active].href; }
    });
    document.addEventListener('keydown', e => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ''));
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); open(); }
      else if (e.key === '/' && !typing) { e.preventDefault(); open(); }
      else if (e.key === 'Escape') close();
    });
  });
})();
