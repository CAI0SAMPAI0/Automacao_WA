/* ══════════════════════════════════════════
   STATE
══════════════════════════════════════════ */
let filePath     = null;
let editFilePath = null;
let editTaskId   = null;
let currentMode  = 'text';
let wkResolve    = null;
let cardStates   = {};  // { id: status }

/* ══════════════════════════════════════════
   INIT
══════════════════════════════════════════ */
window.addEventListener('pywebviewready', init);

function init() {
  setDateDefault();
  setupTabs();
  setupModes();
  setupTimeInput('timeInput');
  setupTimeInput('editTime');
  setupDailyToggle();
  setupEditModeWatch();
  refreshCount();
  loadCards();
  setInterval(() => { loadCards(); refreshCount(); }, 2500);
}

/* ══════════════════════════════════════════
   TABS
══════════════════════════════════════════ */
function setupTabs() {
  document.querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      document.getElementById('panel-' + t.dataset.tab).classList.add('active');
    });
  });
}

/* ══════════════════════════════════════════
   UTILS
══════════════════════════════════════════ */
function setDateDefault() {
  const d  = new Date();
  const m2 = d.getMinutes() + 2 > 59 ? d.getMinutes() : d.getMinutes() + 2;
  document.getElementById('dateInput').value = toInputDate(d);
  document.getElementById('editDate').value  = toInputDate(d);
  document.getElementById('timeInput').value = `${pad(d.getHours())}:${pad(m2)}`;
}

function toInputDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function inputDateToBR(v) {
  const [y, m, d] = v.split('-');
  return `${d}/${m}/${y}`;
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function setupTimeInput(id) {
  const el = document.getElementById(id);
  el.addEventListener('input', () => {
    let v = el.value.replace(/\D/g, '').slice(0, 4);
    if (v.length > 2) v = v.slice(0, 2) + ':' + v.slice(2);
    el.value = v;
  });
}

/* ══════════════════════════════════════════
   MODE PILLS
══════════════════════════════════════════ */
function setupModes() {
  document.querySelectorAll('.mode-pill').forEach(p => {
    p.addEventListener('click', () => {
      document.querySelectorAll('.mode-pill').forEach(x => x.classList.remove('active'));
      p.classList.add('active');
      currentMode = p.dataset.mode;
      applyMode(currentMode);
    });
  });
  document.getElementById('fileArea').addEventListener('click', () => {
    if (!document.getElementById('fileArea').classList.contains('disabled')) {
      handleSelectFile();
    }
  });
}

function applyMode(mode) {
  const msgField = document.getElementById('msg-field');
  const fileArea = document.getElementById('fileArea');
  if (mode === 'text') {
    msgField.style.display = '';
    fileArea.classList.add('disabled');
    filePath = null;
    updateFileLabel('fileLabel', 'Nenhum arquivo selecionado');
  } else if (mode === 'file') {
    msgField.style.display = 'none';
    fileArea.classList.remove('disabled');
  } else {
    msgField.style.display = '';
    fileArea.classList.remove('disabled');
  }
}

/* ══════════════════════════════════════════
   DAILY TOGGLE
══════════════════════════════════════════ */
function setupDailyToggle() {
  document.getElementById('dailyToggle').addEventListener('change', e => {
    document.getElementById('dateInput').disabled     = e.target.checked;
    document.getElementById('dateInput').style.opacity = e.target.checked ? '.4' : '1';
  });
  document.getElementById('editDaily').addEventListener('change', e => {
    document.getElementById('editDate').disabled     = e.target.checked;
    document.getElementById('editDate').style.opacity = e.target.checked ? '.4' : '1';
  });
}

/* ══════════════════════════════════════════
   FILE SELECT
══════════════════════════════════════════ */
async function handleSelectFile() {
  const r = await pywebview.api.selecionar_arquivo();
  if (r.paths && r.paths.length) {
    filePath = r.joined;
    const names = r.paths.map(p => p.split('\\').pop()).join(', ');
    updateFileLabel('fileLabel', names);
  }
}

async function handleEditFile() {
  const r = await pywebview.api.selecionar_arquivo();
  if (r.paths && r.paths.length) {
    editFilePath = r.joined;
    const names  = r.paths.map(p => p.split('\\').pop()).join(', ');
    updateFileLabel('editFileLabel', names);
  }
}

function updateFileLabel(id, text) {
  document.getElementById(id).textContent = text;
}

/* ══════════════════════════════════════════
   ENVIAR AGORA
══════════════════════════════════════════ */
async function handleEnviarAgora() {
  const target  = document.getElementById('target').value.trim();
  const message = document.getElementById('message').value.trim();
  if (!validateFields(target, currentMode, message, filePath)) return;

  const btn = document.getElementById('btnEnviar');
  setLoading(btn, true);

  const r = await pywebview.api.enviar_agora({
    target, mode: currentMode, message, file_path: filePath
  });

  if (r.error) { setLoading(btn, false); toast(r.error, 'error'); return; }
  toast('Enviando... aguarde.', 'info');
  // resultado chega via evento __onEnvioResult (disparado pelo Python)
}

window.__onEnvioResult = function (payload) {
  const btn = document.getElementById('btnEnviar');
  setLoading(btn, false);
  if (payload.ok) {
    toast('Mensagem enviada com sucesso!', 'success');
    resetForm();
  } else {
    toast('Erro no envio: ' + (payload.error || 'desconhecido'), 'error');
  }
};

/* ══════════════════════════════════════════
   AGENDAR
══════════════════════════════════════════ */
async function handleAgendar() {
  const target  = document.getElementById('target').value.trim();
  const message = document.getElementById('message').value.trim();
  const timeStr = document.getElementById('timeInput').value.trim();
  const isDaily = document.getElementById('dailyToggle').checked;
  const dateVal = document.getElementById('dateInput').value;

  if (!validateFields(target, currentMode, message, filePath)) return;
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(timeStr)) {
    toast('Hora inválida. Use HH:MM', 'error');
    return;
  }

  let inclWk = true;
  if (isDaily) {
    inclWk = await askWeekends();
    if (inclWk === null) return;
  }

  const btn = document.getElementById('btnAgendar');
  setLoading(btn, true);

  const r = await pywebview.api.agendar({
    target,
    mode:             currentMode,
    message,
    file_path:        filePath,
    date_str:         isDaily ? '' : inputDateToBR(dateVal),
    time_str:         timeStr,
    daily:            isDaily,
    include_weekends: inclWk,
  });

  setLoading(btn, false);
  if (r.error) { toast(r.error, 'error'); return; }
  toast('Agendado com sucesso!', 'success');
  resetForm();
  loadCards();
}

/* ══════════════════════════════════════════
   WEEKEND MODAL
══════════════════════════════════════════ */
function askWeekends() {
  return new Promise(res => {
    wkResolve = res;
    document.getElementById('modalWk').classList.add('open');
  });
}

function resolveWk(v) {
  document.getElementById('modalWk').classList.remove('open');
  if (wkResolve) { wkResolve(v); wkResolve = null; }
}

/* ══════════════════════════════════════════
   LOAD CARDS
══════════════════════════════════════════ */
async function loadCards() {
  const badge = document.getElementById('syncBadge');
  try {
    badge.className   = 'sync-badge';
    badge.textContent = 'atualizando...';

    const r    = await pywebview.api.listar_agendamentos();
    const list = r.agendamentos || [];

    const container  = document.getElementById('cardList');
    const existingIds = new Set([...container.querySelectorAll('.card')].map(c => +c.dataset.id));
    const newIds      = new Set(list.map(a => a.id));

    // remove cards de itens deletados
    existingIds.forEach(id => {
      if (!newIds.has(id)) {
        const el = container.querySelector(`[data-id="${id}"]`);
        if (el) el.remove();
      }
    });

    if (list.length === 0) {
      if (!container.querySelector('.no-items')) {
        container.innerHTML = '<div class="no-items"><span class="ico">📭</span>Nenhum agendamento ainda</div>';
      }
    } else {
      const noItems = container.querySelector('.no-items');
      if (noItems) noItems.remove();

      list.forEach(a => {
        const existing = container.querySelector(`[data-id="${a.id}"]`);
        if (existing) {
          // atualiza só o que mudou (evita piscar)
          const prevStatus = cardStates[a.id];
          if (prevStatus !== a.status) {
            existing.querySelector('.card-badge').className   = 'card-badge ' + statusBadgeClass(a.status);
            existing.querySelector('.card-badge').textContent = a.status.toUpperCase();
            const locked  = (a.status === 'running' || a.status === 'completed');
            const editBtn = existing.querySelector('.card-btn-edit');
            const delBtn  = existing.querySelector('.card-btn-del');
            if (editBtn) editBtn.disabled = locked;
            if (delBtn)  delBtn.disabled  = locked;
            cardStates[a.id] = a.status;
          }
        } else {
          container.insertAdjacentHTML('beforeend', renderCard(a));
          cardStates[a.id] = a.status;
        }
      });
    }

    const now = new Date();
    badge.className   = 'sync-badge ok';
    badge.textContent = `✓ ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  } catch (e) {
    badge.className   = 'sync-badge err';
    badge.textContent = 'erro';
  }
}

function renderCard(a) {
  const locked = (a.status === 'running' || a.status === 'completed');
  return `
<div class="card" data-id="${a.id}">
  <div class="card-top">
    <div>
      <div class="card-target">📱 ${esc(a.target)}</div>
      <div class="card-date">📅 ${esc(a.scheduled_time)} &nbsp;·&nbsp; ${modeLabel(a.mode)}</div>
    </div>
    <span class="card-badge ${statusBadgeClass(a.status)}">${a.status.toUpperCase()}</span>
  </div>
  <div class="card-actions">
    <button class="card-btn card-btn-edit" ${locked ? 'disabled' : ''} onclick="openEdit(${a.id})">✏ Editar</button>
    <button class="card-btn card-btn-del"  ${locked ? 'disabled' : ''} onclick="handleDelete(${a.id},'${esc(a.target)}')">🗑 Excluir</button>
  </div>
</div>`;
}

function statusBadgeClass(s) {
  return { pending: 'badge-pending', running: 'badge-running', completed: 'badge-completed', failed: 'badge-failed', cancelled: 'badge-cancelled' }[s] || 'badge-pending';
}

function modeLabel(m) {
  return { text: 'Texto', file: 'Arquivo', file_text: 'Arq+Texto' }[m] || m;
}

function esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* ══════════════════════════════════════════
   DELETE
══════════════════════════════════════════ */
async function handleDelete(id, target) {
  if (!confirm(`Excluir agendamento de "${target}"?`)) return;
  const r = await pywebview.api.excluir_agendamento(id);
  if (r.error) { toast(r.error, 'error'); return; }
  toast('Agendamento excluído', 'info');
  const el = document.querySelector(`[data-id="${id}"]`);
  if (el) el.remove();
}

/* ══════════════════════════════════════════
   EDIT MODAL
══════════════════════════════════════════ */
async function openEdit(id) {
  const r = await pywebview.api.obter_agendamento(id);
  if (r.error) { toast(r.error, 'error'); return; }
  const a  = r.agendamento;
  editTaskId   = id;
  editFilePath = a.file_path || null;

  document.getElementById('editTarget').value  = a.target  || '';
  document.getElementById('editMode').value    = a.mode    || 'text';
  document.getElementById('editMessage').value = a.message || '';
  document.getElementById('editTime').value    = a.time_str || '';

  if (a.date_str) {
    const [d, m, y] = a.date_str.split('/');
    document.getElementById('editDate').value = `${y}-${m}-${d}`;
  }

  document.getElementById('editDaily').checked = false;
  updateFileLabel('editFileLabel', editFilePath ? editFilePath.split('\n').length + ' arquivo(s)' : '—');
  applyEditMode(a.mode);
  document.getElementById('modalEdit').classList.add('open');
}

function setupEditModeWatch() {
  document.getElementById('editMode').addEventListener('change', e => applyEditMode(e.target.value));
}

function applyEditMode(mode) {
  document.getElementById('editMsgField').style.display  = mode === 'file' ? 'none' : '';
  document.getElementById('editFileArea').style.display  = mode === 'text' ? 'none' : '';
}

function closeEditModal() {
  document.getElementById('modalEdit').classList.remove('open');
}

async function handleSalvarEdit() {
  const isDaily = document.getElementById('editDaily').checked;
  let inclWk = true;
  if (isDaily) {
    inclWk = await askWeekends();
    if (inclWk === null) return;
  }

  const btn = document.getElementById('btnSalvarEdit');
  setLoading(btn, true);

  const dateVal = document.getElementById('editDate').value;
  const r = await pywebview.api.editar_agendamento({
    task_id:          editTaskId,
    target:           document.getElementById('editTarget').value.trim(),
    mode:             document.getElementById('editMode').value,
    message:          document.getElementById('editMessage').value.trim(),
    file_path:        editFilePath,
    date_str:         inputDateToBR(dateVal),
    time_str:         document.getElementById('editTime').value.trim(),
    daily:            isDaily,
    include_weekends: inclWk,
  });

  setLoading(btn, false);
  if (r.error) { toast(r.error, 'error'); return; }
  toast('Agendamento atualizado!', 'success');
  closeEditModal();
  loadCards();
}

/* ══════════════════════════════════════════
   EXEC COUNT
══════════════════════════════════════════ */
async function refreshCount() {
  const r = await pywebview.api.get_execucoes();
  document.getElementById('execCount').textContent = r.count || 0;
}

/* ══════════════════════════════════════════
   VALIDATION
══════════════════════════════════════════ */
function validateFields(target, mode, message, fp) {
  if (!target)                              { toast('Informe o contato ou número', 'error');                     return false; }
  if (mode === 'text'      && !message)     { toast('Escreva uma mensagem', 'error');                            return false; }
  if (mode === 'file'      && !fp)          { toast('Selecione um arquivo', 'error');                            return false; }
  if (mode === 'file_text' && (!fp || !message)) { toast('Selecione arquivo e escreva uma mensagem', 'error');  return false; }
  return true;
}

/* ══════════════════════════════════════════
   RESET FORM
══════════════════════════════════════════ */
function resetForm() {
  document.getElementById('target').value  = '';
  document.getElementById('message').value = '';
  filePath = null;
  updateFileLabel('fileLabel', 'Nenhum arquivo selecionado');
  document.querySelectorAll('.mode-pill').forEach(p => p.classList.remove('active'));
  document.querySelector('[data-mode="text"]').classList.add('active');
  currentMode = 'text';
  applyMode('text');
  setDateDefault();
  document.getElementById('dailyToggle').checked    = false;
  document.getElementById('dateInput').disabled     = false;
  document.getElementById('dateInput').style.opacity = '1';
}

/* ══════════════════════════════════════════
   LOADING STATE
══════════════════════════════════════════ */
function setLoading(btn, on) {
  btn.disabled = on;
  btn.classList.toggle('loading', on);
}

/* ══════════════════════════════════════════
   TOAST
══════════════════════════════════════════ */
function toast(msg, type = 'info') {
  const c  = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className   = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => {
    el.classList.add('fade-out');
    setTimeout(() => el.remove(), 320);
  }, 3200);
}