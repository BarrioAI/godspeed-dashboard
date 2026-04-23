/* ===================================
   GODSPEED RETAIL INTELLIGENCE SYSTEM
   Frontend JS
   =================================== */

// ─── TOAST NOTIFICATIONS ───
function showToast(message, type = 'default') {
  const container = document.getElementById('toast-container') || createToastContainer();
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function createToastContainer() {
  const div = document.createElement('div');
  div.id = 'toast-container';
  div.className = 'toast-container';
  document.body.appendChild(div);
  return div;
}

// ─── SEND PITCH ───
async function sendPitch(storeName) {
  const channel = 'Instagram DM';
  const message = `Hey! We're Godspeed — a premium streetwear brand that's the perfect fit for your store. We noticed you carry some of the hottest brands in the game. Mind if we send over our lookbook?`;

  const confirmed = confirm(`Send pitch to ${storeName} via ${channel}?`);
  if (!confirmed) return;

  try {
    const res = await fetch('/api/send-pitch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ store_name: storeName, channel, message })
    });

    const data = await res.json();
    if (data.success) {
      showToast(`✅ Pitch sent to ${storeName}`, 'success');
      // Update status badge in table
      const badge = document.querySelector(`[data-store="${storeName}"] .status-badge`);
      if (badge) {
        badge.className = 'badge badge-pitched';
        badge.textContent = 'Pitched';
      }
    } else {
      showToast(`❌ Error: ${data.error}`, 'error');
    }
  } catch (e) {
    showToast(`❌ Network error`, 'error');
  }
}

// ─── SEND REORDER ───
async function sendReorder(storeName) {
  const channel = 'Email';
  const message = `Hey! Just checking in — ready to restock Godspeed? Let us know what quantities you need and we'll get it shipped ASAP.`;

  const confirmed = confirm(`Send reorder message to ${storeName}?`);
  if (!confirmed) return;

  try {
    const res = await fetch('/api/send-reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ store_name: storeName, channel, message })
    });

    const data = await res.json();
    if (data.success) {
      showToast(`✅ Reorder request sent to ${storeName}`, 'success');
    } else {
      showToast(`❌ Error: ${data.error}`, 'error');
    }
  } catch (e) {
    showToast(`❌ Network error`, 'error');
  }
}

// ─── BULK SELECT ───
let selectedStores = new Set();

function initBulkSelect() {
  const selectAll = document.getElementById('select-all');
  if (!selectAll) return;

  selectAll.addEventListener('change', (e) => {
    const checkboxes = document.querySelectorAll('.store-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = e.target.checked;
      if (e.target.checked) {
        selectedStores.add(cb.dataset.store);
      } else {
        selectedStores.clear();
      }
    });
    updateBulkBar();
  });

  document.querySelectorAll('.store-checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      if (e.target.checked) {
        selectedStores.add(e.target.dataset.store);
      } else {
        selectedStores.delete(e.target.dataset.store);
      }
      updateBulkBar();
    });
  });
}

function updateBulkBar() {
  const bar = document.getElementById('bulk-bar');
  const count = document.getElementById('bulk-count');
  if (!bar || !count) return;

  if (selectedStores.size > 0) {
    bar.classList.add('show');
    count.textContent = `${selectedStores.size} store${selectedStores.size > 1 ? 's' : ''} selected`;
  } else {
    bar.classList.remove('show');
  }
}

async function bulkPitch() {
  if (selectedStores.size === 0) return;

  const stores = Array.from(selectedStores);
  const confirmed = confirm(`Send pitch to ${stores.length} stores?`);
  if (!confirmed) return;

  try {
    const res = await fetch('/api/bulk-pitch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stores: stores,
        channel: 'Instagram DM',
        message: `Hey! We're Godspeed — a premium streetwear brand that's the perfect fit for your store. Mind if we send over our lookbook?`
      })
    });

    const data = await res.json();
    if (data.success) {
      showToast(`✅ Bulk pitch sent to ${stores.length} stores`, 'success');
      selectedStores.clear();
      updateBulkBar();
      // Uncheck all
      document.querySelectorAll('.store-checkbox').forEach(cb => cb.checked = false);
      document.getElementById('select-all').checked = false;
    } else {
      showToast(`❌ Error: ${data.error}`, 'error');
    }
  } catch (e) {
    showToast(`❌ Network error`, 'error');
  }
}

// ─── PITCH MODAL ───
function openPitchModal(storeName) {
  const modal = document.getElementById('pitch-modal');
  if (!modal) return;
  document.getElementById('modal-store-name').textContent = storeName;
  document.getElementById('modal-store-input').value = storeName;
  modal.classList.add('show');
}

function closePitchModal() {
  const modal = document.getElementById('pitch-modal');
  if (modal) modal.classList.remove('show');
}

async function submitPitch(e) {
  e.preventDefault();
  const storeName = document.getElementById('modal-store-input').value;
  const channel = document.getElementById('modal-channel').value;
  const message = document.getElementById('modal-message').value;

  try {
    const res = await fetch('/api/send-pitch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ store_name: storeName, channel, message })
    });

    const data = await res.json();
    if (data.success) {
      showToast(`✅ Pitch logged for ${storeName}`, 'success');
      closePitchModal();
    } else {
      showToast(`❌ ${data.error}`, 'error');
    }
  } catch (e) {
    showToast(`❌ Network error`, 'error');
  }
}

// ─── SCRAPER ───
let scraperInterval = null;

async function startScraper() {
  const btn = document.getElementById('scraper-btn');
  const terminal = document.getElementById('scraper-terminal');

  btn.disabled = true;
  btn.innerHTML = '<span class="progress-ring">⟳</span> Running...';
  terminal.innerHTML = '';

  appendTerminalLine('Godspeed Retail Intelligence Engine v2.0', 'sys');
  appendTerminalLine('Initializing...', 'sys');

  try {
    const res = await fetch('/api/scraper/start', { method: 'POST' });
    const data = await res.json();

    if (!data.success) {
      showToast(`❌ ${data.error}`, 'error');
      btn.disabled = false;
      btn.textContent = '▶ Run Scraper';
      return;
    }

    // Poll for updates
    scraperInterval = setInterval(pollScraperStatus, 1500);

  } catch (e) {
    showToast('❌ Failed to start scraper', 'error');
    btn.disabled = false;
    btn.textContent = '▶ Run Scraper';
  }
}

let lastProgressCount = 0;

async function pollScraperStatus() {
  try {
    const res = await fetch('/api/scraper/status');
    const data = await res.json();

    // Add new lines
    if (data.progress && data.progress.length > lastProgressCount) {
      for (let i = lastProgressCount; i < data.progress.length; i++) {
        appendTerminalLine(data.progress[i].message, 'output', data.progress[i].time);
      }
      lastProgressCount = data.progress.length;
    }

    if (!data.running && data.status !== 'idle') {
      clearInterval(scraperInterval);
      scraperInterval = null;
      lastProgressCount = 0;

      const btn = document.getElementById('scraper-btn');
      btn.disabled = false;
      btn.textContent = '▶ Run Scraper Again';

      if (data.results) {
        showResults(data.results);
      }
    }

  } catch (e) {
    clearInterval(scraperInterval);
  }
}

function appendTerminalLine(msg, type = 'output', time = null) {
  const terminal = document.getElementById('scraper-terminal');
  if (!terminal) return;

  const line = document.createElement('div');
  line.className = 'terminal-line';

  const timeStr = time || new Date().toLocaleTimeString('en-US', { hour12: false });
  line.innerHTML = `<span class="terminal-time">[${timeStr}]</span><span class="terminal-msg">${msg}</span>`;

  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}

function showResults(results) {
  const container = document.getElementById('results-container');
  if (!container) return;

  container.innerHTML = `
    <div class="card-title" style="margin-top: 24px;"><span>📊</span> Results Summary</div>
    <div class="results-grid">
      <div class="result-card">
        <div class="result-num">${results.stores_scanned}</div>
        <div class="result-label">Stores Scanned</div>
      </div>
      <div class="result-card">
        <div class="result-num" style="color: #2ECC71;">${results.new_leads}</div>
        <div class="result-label">New Leads Found</div>
      </div>
      <div class="result-card">
        <div class="result-num" style="color: #C9A84C;">${results.already_carrying}</div>
        <div class="result-label">Already Carrying Godspeed</div>
      </div>
      <div class="result-card">
        <div class="result-num" style="color: #8A9BB8;">${results.skipped}</div>
        <div class="result-label">Skipped</div>
      </div>
    </div>
  `;
  showToast('✅ Scraper complete! Check leads page for new stores.', 'success');
}

// ─── INIT ───
document.addEventListener('DOMContentLoaded', () => {
  initBulkSelect();

  // Highlight active nav link
  const path = window.location.pathname;
  document.querySelectorAll('.nav-link, .mobile-nav a').forEach(link => {
    if (link.getAttribute('href') === path) {
      link.classList.add('active');
    }
  });

  // Pitch form
  const pitchForm = document.getElementById('pitch-form');
  if (pitchForm) pitchForm.addEventListener('submit', submitPitch);

  // Close modal on overlay click
  const overlay = document.getElementById('pitch-modal');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closePitchModal();
    });
  }
});
