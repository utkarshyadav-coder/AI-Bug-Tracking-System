(() => {
  const cfg = JSON.parse(document.getElementById('bs-config').textContent);
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const SEV_COLOR = { Critical: '#f72585', High: '#f8961e', Medium: '#4361ee', Low: '#43aa8b' };
  const isDev = cfg.mode === 'developer';

  // Safe DOM builder: text is always set via textContent/text nodes, never innerHTML.
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(kid));
    return el;
  }
  const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;
  const sevBadge = (s) => h('span', { class: `sev sev-${s}` }, s);

  async function api(url, opts = {}) {
    const o = { credentials: 'same-origin', ...opts };
    if (o.body && !(o.body instanceof FormData)) { o.headers = { 'Content-Type': 'application/json' }; o.body = JSON.stringify(o.body); }
    const r = await fetch(url, o);
    const data = await r.json().catch(() => ({ success: false, error: `HTTP ${r.status}` }));
    if (!r.ok || data.success === false) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  const showErr = (el, msg) => { el.textContent = msg; el.hidden = !msg; };

  // ---------- tabs
  function openTab(name) {
    $$('.bs-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    $$('.bs-panel').forEach((p) => { p.hidden = p.dataset.panel !== name; });
    if (name === 'queue') loadReports();
    if (name === 'insights') loadInsights();
  }
  $$('.bs-tabs button').forEach((b) => b.addEventListener('click', () => openTab(b.dataset.tab)));

  // ---------- charts (plain DOM)
  function hbars(el, entries, colorFn) {
    clear(el);
    const max = Math.max(1, ...entries.map((e) => e[1]));
    if (!entries.length) el.append(h('p', { class: 'bs-muted' }, 'No data yet.'));
    entries.forEach(([label, val, text]) => el.append(h('div', { class: 'bs-hbar' },
      h('span', {}, label),
      h('div', {}, h('i', { style: `width:${(val / max) * 100}%;background:${colorFn ? colorFn(label) : ''}` })),
      h('span', {}, text ?? String(val)))));
  }

  // ---------- KPIs + stats
  async function loadStats() {
    const s = await api('/api/bugsight/stats');
    const k = (label, val, color) => h('div', { class: 'bs-kpi', style: color ? `border-left-color:${color}` : '' }, h('b', {}, String(val)), h('span', {}, label));
    const box = clear($('#kpis'));
    box.append(k(isDev ? 'Reports tracked' : 'My reports', s.total), k('Open / in progress', s.open, '#f8961e'),
      k('Critical & open', s.critical_open, '#f72585'), k('Avg. model confidence', pct(s.avg_confidence), '#43aa8b'));
    if (s.model_agreement.judged) box.append(k('Model agreed with confirmed severity', `${s.model_agreement.agree}/${s.model_agreement.judged}`, '#4cc9f0'));
    return s;
  }

  async function loadModelChip() {
    try {
      const { model } = await api('/api/bugsight/model');
      $('#chip-rf').textContent = `Random Forest: ${model.n_trees} trees · ${pct(model.holdout_accuracy)} holdout acc.`;
      $('#chip-rf').title = model.label_source;
      return model;
    } catch (e) { $('#chip-rf').textContent = 'Random Forest: unavailable'; }
  }

  // ---------- prediction + recommendation rendering
  function renderPrediction(into, pred) {
    clear(into);
    const probs = Object.entries(pred.probabilities).sort((a, b) => b[1] - a[1]);
    into.append(
      h('div', { class: 'bs-big' }, sevBadge(pred.severity), h('div', {}, h('b', {}, pct(pred.confidence)), ' confidence'),
        h('div', {}, h('b', {}, `${pred.risk_score}/10`), ' risk score')),
      h('div', { class: 'bs-sub' }, 'Class probabilities'),
      (() => { const d = h('div'); hbars(d, probs.map(([s, p]) => [s, p, pct(p)]), (s) => SEV_COLOR[s]); return d; })(),
      h('div', { class: 'bs-sub' }, `Votes of ${pred.n_trees} trees (first ${pred.votes_sample.length} shown)`),
      h('div', { class: 'bs-votes' }, pred.votes_sample.map((v) => h('i', { style: `background:${SEV_COLOR[v]}`, title: v }))),
      h('div', { style: 'font-size:.82rem' }, Object.entries(pred.tree_votes).map(([s, n]) => `${s}: ${n}`).join('  ·  ')),
      h('div', { class: 'bs-sub' }, 'Top drivers (global feature importance)'),
      (() => { const d = h('div'); hbars(d, pred.importances.slice(0, 5).map((i) => [i.label, i.importance, pct(i.importance)])); return d; })());
    (pred.warnings || []).forEach((w) => into.append(h('div', { class: 'bs-err' }, w)));
  }

  const REC_LABELS = {
    summary: null, root_cause_hypotheses: 'Likely root causes', fix_steps: 'Fix steps', code_hints: 'Where to look',
    test_plan: 'Test plan', prevention: 'Prevention', repro_steps: 'Reproduction steps', missing_info: 'Missing information',
    verification_checklist: 'Verification checklist', regression_areas: 'Regression areas', report_quality_tips: 'Report quality tips',
    suggested_owner_skill: 'Suggested owner', eta_hours: 'Estimated effort (hours)', risk: 'Fix risk',
  };
  function renderRec(into, rec) {
    clear(into); into.hidden = false;
    const fb = rec.source !== 'claude';
    into.append(h('div', { class: 'bs-bar' }, h('h3', {}, h('i', { class: 'fas fa-robot' }), ' Recommendation'),
      h('span', { class: `bs-src ${fb ? 'fb' : ''}` }, fb ? 'Rule-based fallback (set ANTHROPIC_API_KEY for Claude)' : `Claude · ${rec.model}`)));
    const body = h('div', { class: 'bs-rec' });
    const d = rec.data || {};
    if (d.summary) body.append(h('p', {}, d.summary));
    for (const [key, label] of Object.entries(REC_LABELS)) {
      if (!label || d[key] == null || d[key] === '' || (Array.isArray(d[key]) && !d[key].length)) continue;
      body.append(h('h4', {}, label), Array.isArray(d[key]) ? h('ul', {}, d[key].map((x) => h('li', {}, String(x)))) : h('div', {}, String(d[key])));
    }
    into.append(body);
  }
  async function fetchRec(id, into, force = false) {
    into.hidden = false; clear(into).append(h('p', { class: 'bs-muted' }, 'Asking for a recommendation…'));
    try {
      const { recommendation } = await api('/api/bugsight/recommend', { method: 'POST', body: { id, force, mode: cfg.mode } });
      renderRec(into, recommendation);
      into.append(h('button', { class: 'bs-btn sm ghost', onclick: () => fetchRec(id, into, true) }, 'Regenerate'));
    } catch (e) { clear(into).append(h('div', { class: 'bs-err' }, e.message)); }
  }

  // ---------- analyze form
  const SAMPLES = [
    { title: 'Payment gateway timeout in production', bug_type: 'network', component: 'Payment', environment: 'production', affected_users: 8500, frequency_per_day: 45, workaround: 'no', time_to_reproduce: 'immediate', stack_depth: 32, error_rate_spike: '>50%', description: 'Payment API calls time out after 30s, breaking checkout for EU users.' },
    { title: 'SQL injection in product search', bug_type: 'security', component: 'Database', environment: 'production', affected_users: 10000, frequency_per_day: 5, workaround: 'no', time_to_reproduce: 'immediate', stack_depth: 8, error_rate_spike: '<5%', description: 'Unparameterized query allows data exfiltration.' },
    { title: 'Button misaligned on mobile Safari', bug_type: 'ui', component: 'UI', environment: 'production', affected_users: 150, frequency_per_day: 200, workaround: 'yes', time_to_reproduce: 'immediate', stack_depth: 2, error_rate_spike: '<5%', description: 'CTA overlaps nav bar on iOS 16 landscape.' },
  ];
  const form = $('#bs-form');
  if (form) {
    SAMPLES.forEach((s) => $('#samples').append(h('button', { type: 'button', onclick: () => { for (const [k, v] of Object.entries(s)) { const f = form.elements[k]; if (f) f.value = v; } } }, s.title)));
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const btn = $('#btn-analyze'), err = $('#form-err'); showErr(err, '');
      btn.disabled = true; btn.textContent = 'Analyzing…';
      try {
        const body = Object.fromEntries(new FormData(form).entries());
        const { id, prediction } = await api('/api/bugsight/predict', { method: 'POST', body });
        renderPrediction($('#result'), prediction);
        await Promise.all([fetchRec(id, $('#rec')), loadStats()]);
      } catch (e) { showErr(err, e.message); }
      finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-bolt"></i> Predict &amp; get recommendation'; }
    });
  }

  // ---------- reports table + drawer
  async function loadReports() {
    const body = $('#reports-body');
    try {
      const { reports } = await api(`/api/bugsight/reports${isDev ? '?sort=severity' : ''}`);
      const fs = $('#flt-status').value, fv = $('#flt-sev').value;
      const rows = reports.filter((r) => (!fs || r.status === fs) && (!fv || (r.confirmed_severity || r.predicted_severity) === fv));
      clear(body);
      if (!rows.length) body.append(h('tr', {}, h('td', { colspan: 8, class: 'bs-muted' }, 'No reports yet.')));
      rows.forEach((r) => body.append(h('tr', { onclick: () => openDrawer(r.id) },
        h('td', {}, String(r.id)), h('td', {}, sevBadge(r.confirmed_severity || r.predicted_severity)), h('td', {}, pct(r.confidence)),
        h('td', {}, r.title), h('td', {}, r.component), h('td', {}, r.environment), h('td', {}, r.status), h('td', {}, r.assigned_to || '—'))));
    } catch (e) { clear(body).append(h('tr', {}, h('td', { colspan: 8, class: 'bs-err' }, e.message))); }
  }
  ['#flt-status', '#flt-sev'].forEach((s) => $(s).addEventListener('change', loadReports));

  const drawer = $('#drawer');
  $('#drawer-close').addEventListener('click', () => { drawer.hidden = true; });
  drawer.addEventListener('click', (e) => { if (e.target === drawer) drawer.hidden = true; });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') drawer.hidden = true; });

  async function openDrawer(id) {
    const body = clear($('#drawer-body')); drawer.hidden = false;
    body.append(h('p', { class: 'bs-muted' }, 'Loading…'));
    try {
      const { report: r, prediction } = await api(`/api/bugsight/report/${id}`);
      clear(body).append(h('h3', {}, `#${r.id} · ${r.title}`),
        h('p', { class: 'bs-muted' }, `${r.component} · ${r.environment} · reported by ${r.reporter} · ${r.created_at || ''}`),
        r.description ? h('p', {}, r.description) : null);
      if (isDev) {
        const st = h('select', { id: 'd-status' }, cfg.statuses.map((s) => h('option', { value: s, selected: s === r.status }, s)));
        const cs = h('select', { id: 'd-sev' }, h('option', { value: '' }, '— not confirmed —'),
          cfg.severities.map((s) => h('option', { value: s, selected: s === r.confirmed_severity }, s)));
        const msg = h('span', { class: 'bs-muted' });
        const save = async (extra = {}) => {
          try { await api(`/api/bugsight/report/${id}/update`, { method: 'POST', body: { status: st.value, confirmed_severity: cs.value, ...extra } });
            msg.textContent = 'Saved ✓'; loadReports(); loadStats(); }
          catch (e) { msg.textContent = e.message; }
        };
        body.append(h('div', { class: 'bs-ctl' },
          h('div', { class: 'bs-field' }, h('label', {}, 'Status'), st),
          h('div', { class: 'bs-field' }, h('label', {}, 'Confirmed severity (trains the model)'), cs),
          h('button', { class: 'bs-btn sm', onclick: () => save() }, 'Save'),
          h('button', { class: 'bs-btn sm ghost', onclick: () => save({ claim: true }) }, `Assign to me${r.assigned_to ? ` (now ${r.assigned_to})` : ''}`), msg));
      }
      const predBox = h('div'); renderPrediction(predBox, prediction);
      const rec = h('div', { class: 'bs-card', style: 'box-shadow:none;border:1px solid #eceef6;margin-top:1rem' });
      body.append(predBox, rec); fetchRec(id, rec);
    } catch (e) { clear(body).append(h('div', { class: 'bs-err' }, e.message)); }
  }

  // ---------- bulk (tester)
  const bulkBtn = $('#btn-bulk');
  if (bulkBtn) bulkBtn.addEventListener('click', async () => {
    const f = $('#bulk-file').files[0], err = $('#bulk-err'), out = clear($('#bulk-out')); showErr(err, '');
    if (!f) return showErr(err, 'Choose a CSV file first.');
    bulkBtn.disabled = true;
    try {
      const fd = new FormData(); fd.append('file', f);
      const r = await api('/api/bugsight/batch', { method: 'POST', body: fd });
      out.append(h('p', {}, `Predicted ${r.count} bugs${r.skipped ? `, skipped ${r.skipped} without a title` : ''}${r.truncated ? ' (file truncated to 500 rows)' : ''}.`),
        h('div', { style: 'display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.6rem' }, Object.entries(r.summary).map(([s, n]) => h('span', {}, sevBadge(s), ` ${n}`))),
        h('div', { class: 'bs-scroll' }, h('table', { class: 'bs-table' },
          h('thead', {}, h('tr', {}, ['#', 'Severity', 'Conf.', 'Risk', 'Title', 'Component'].map((c) => h('th', {}, c)))),
          h('tbody', {}, r.results.map((x) => h('tr', { onclick: () => openDrawer(x.id) }, h('td', {}, String(x.id)), h('td', {}, sevBadge(x.severity)),
            h('td', {}, pct(x.confidence)), h('td', {}, `${x.risk_score}/10`), h('td', {}, x.title), h('td', {}, x.component)))))));
      loadStats();
    } catch (e) { showErr(err, e.message); } finally { bulkBtn.disabled = false; }
  });

  // ---------- insights (developer)
  async function loadInsights() {
    if (!isDev) return;
    const [s, m] = await Promise.all([loadStats(), loadModelChip()]);
    hbars($('#ch-sev'), Object.entries(s.severity), (k) => SEV_COLOR[k]);
    hbars($('#ch-comp'), Object.entries(s.components));
    const tr = clear($('#ch-trend')), mx = Math.max(1, ...s.trend.map((t) => t.count));
    s.trend.forEach((t) => tr.append(h('div', { style: `height:${(t.count / mx) * 100}%`, title: `${t.day}: ${t.count}` }, t.count ? h('span', {}, String(t.count)) : null)));
    if (m) {
      hbars($('#ch-imp'), m.importances.map((i) => [i.label, i.importance, pct(i.importance)]));
      clear($('#model-info')).append(h('div', {}, `Trained ${m.trained_at} · ${m.n_trees} trees · labels: ${m.label_source}`),
        h('div', {}, `Holdout accuracy ${pct(m.holdout_accuracy)} (within one severity level: ${pct(m.holdout_within_one)}) · ${m.n_real} confirmed real bugs used`),
        h('div', { style: 'margin-top:.4rem' }, 'Holdout is measured on the synthetic bootstrap set, so treat it as a sanity check; confirm severities on real bugs, then retrain.'));
    }
  }
  const brief = $('#btn-brief');
  if (brief) {
    brief.addEventListener('click', async () => {
      const box = clear($('#brief')); box.append(h('p', { class: 'bs-muted' }, 'Generating…')); brief.disabled = true;
      try {
        const { brief: b } = await api('/api/bugsight/brief', { method: 'POST', body: {} });
        clear(box);
        if (!b) return box.append(h('p', { class: 'bs-muted' }, 'No open bugs.'));
        const d = b.data;
        box.append(h('span', { class: `bs-src ${b.source === 'claude' ? '' : 'fb'}` }, b.source === 'claude' ? `Claude · ${b.model}` : 'Rule-based fallback'),
          h('p', { style: 'font-weight:600;margin-top:.6rem' }, d.headline),
          h('div', { class: 'bs-rec' }, h('h4', {}, 'Priorities'), h('ul', {}, (d.priorities || []).map((p) => h('li', {}, `#${p.id}: ${p.action}`))),
            h('h4', {}, 'Patterns'), h('ul', {}, (d.patterns || []).map((p) => h('li', {}, String(p)))),
            d.staffing ? [h('h4', {}, 'Staffing'), h('div', {}, d.staffing)] : null));
      } catch (e) { clear(box).append(h('div', { class: 'bs-err' }, e.message)); } finally { brief.disabled = false; }
    });
    $('#btn-retrain').addEventListener('click', async (ev) => {
      ev.target.disabled = true;
      try { await api('/api/bugsight/retrain', { method: 'POST', body: {} }); await loadInsights(); await loadModelChip(); }
      catch (e) { $('#model-info').textContent = e.message; } finally { ev.target.disabled = false; }
    });
  }

  // ---------- boot
  loadModelChip(); loadStats().catch(() => {});
  if (isDev) loadReports();
})();
