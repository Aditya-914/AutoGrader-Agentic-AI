/**
 * AutoGrader AI — Full Client Controller
 * Handles: Code editor, Quick Run, Grading, Rules Editor, Reports tab
 */

let editor = null;
let lastReportData = null;
let activeRulesData = null;   // Currently loaded rule set object
let activeRulesFile = 'mcm_rules.json'; // Currently selected rules filename
let presetsCache = [];

// ═══════════════════════════════════════════════════════════════════════════
// Bootstrap
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
  editor = new CodeEditor('code-textarea', 'line-numbers', 'editor-cursor-pos');

  initTheme();
  initTabNav();
  initCodeTabEvents();
  initRulesTabEvents();
  initReportsTabEvents();

  // Load everything in order
  await loadPresetsList();
  await loadRulesList();
  await loadPreset('mcm.c');
  await checkStatus();
});

// ═══════════════════════════════════════════════════════════════════════════
// Theme
// ═══════════════════════════════════════════════════════════════════════════

function initTheme() {
  const toggleBtn = document.getElementById('theme-toggle-btn');
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  if (toggleBtn) {
    toggleBtn.textContent = saved === 'dark' ? '🌙' : '☀️';
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      toggleBtn.textContent = next === 'dark' ? '🌙' : '☀️';
    });
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Tab Navigation
// ═══════════════════════════════════════════════════════════════════════════

function initTabNav() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;

      // Update button states
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Update content panels
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      const panel = document.getElementById(target);
      if (panel) panel.classList.add('active');

      // Load reports lazily when tab opens
      if (target === 'reports-tab') {
        loadReports();
      }
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// Code Tab Events
// ═══════════════════════════════════════════════════════════════════════════

function initCodeTabEvents() {
  // Preset selector
  const presetSelect = document.getElementById('preset-select');
  if (presetSelect) {
    presetSelect.addEventListener('change', e => loadPreset(e.target.value));
  }

  // Grade rules selector (live-updates banner and rubric)
  const gradeRulesSelect = document.getElementById('grade-rules-select');
  if (gradeRulesSelect) {
    gradeRulesSelect.addEventListener('change', e => {
      loadRuleFile(e.target.value);
    });
  }

  // Clear button
  const clearBtn = document.getElementById('clear-code-btn');
  if (clearBtn) clearBtn.addEventListener('click', () => editor.clear());

  // File upload
  const uploader = document.getElementById('file-uploader');
  if (uploader) {
    uploader.addEventListener('change', e => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = evt => {
        editor.setValue(evt.target.result);
        showToast(`Uploaded: ${file.name}`);
      };
      reader.readAsText(file);
    });
  }

  // Quick Run toggle (collapsible)
  const qrToggle = document.getElementById('quick-run-toggle');
  const qrBody = document.getElementById('quick-run-body');
  if (qrToggle && qrBody) {
    qrToggle.addEventListener('click', () => {
      const isVisible = qrBody.style.display !== 'none';
      qrBody.style.display = isVisible ? 'none' : 'block';
      qrToggle.querySelector('.toggle-icon').textContent = isVisible ? '▶' : '▼';
    });
  }

  // Quick Run button
  const qrBtn = document.getElementById('quick-run-btn');
  if (qrBtn) qrBtn.addEventListener('click', handleQuickRun);

  // Grade button
  const gradeBtn = document.getElementById('grade-btn');
  if (gradeBtn) gradeBtn.addEventListener('click', handleGrade);
}

// ═══════════════════════════════════════════════════════════════════════════
// System Status
// ═══════════════════════════════════════════════════════════════════════════

async function checkStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    const badge = document.getElementById('system-status-badge');
    if (badge && data.tools) {
      const gccOk = data.tools.gcc?.installed;
      const ollamaOk = data.tools.ollama?.installed;
      badge.innerHTML = `<span class="status-dot" style="background:${gccOk ? 'var(--color-success)' : 'var(--color-danger)'}"></span> GCC ${gccOk ? 'Ready' : 'Missing'}${ollamaOk ? ' · Ollama On' : ''}`;
    }
  } catch (e) {
    console.warn('Status check failed:', e);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Preset Loader
// ═══════════════════════════════════════════════════════════════════════════

async function loadPresetsList() {
  try {
    const res = await fetch('/api/presets');
    if (res.ok) {
      const data = await res.json();
      presetsCache = data.presets || [];
    }
  } catch (e) {
    console.warn('Failed to fetch presets:', e);
  }
}

async function loadPreset(filename) {
  try {
    const res = await fetch(`/api/submissions/${filename}`);
    if (res.ok) {
      const data = await res.json();
      editor.setValue(data.code);
    }

    // Determine matching rules file
    let targetRule = 'mcm_rules.json';
    const presetMeta = presetsCache.find(p => p.file === filename || p.id === filename);
    if (presetMeta && presetMeta.default_rules) {
      targetRule = presetMeta.default_rules;
    } else if (filename.includes('mcm')) {
      targetRule = 'mcm_rules.json';
    } else if (filename.includes('maze')) {
      targetRule = 'maze_rules.json';
    } else if (filename.includes('substring')) {
      targetRule = 'new_rules.json';
    } else if (filename.includes('add') || filename.includes('infinite') || filename.includes('syntax')) {
      targetRule = 'add_rules.json';
    }

    // Update grade rules dropdown and load rule file if present
    const gradeRulesSel = document.getElementById('grade-rules-select');
    if (gradeRulesSel && [...gradeRulesSel.options].some(o => o.value === targetRule)) {
      gradeRulesSel.value = targetRule;
      await loadRuleFile(targetRule);
    }
  } catch (e) {
    console.error('Failed to load preset:', e);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Quick Runner
// ═══════════════════════════════════════════════════════════════════════════

async function handleQuickRun() {
  const code = editor.getValue();
  const stdinVal = document.getElementById('stdin-input').value;
  const outBox = document.getElementById('quick-run-output');
  const qrBtn = document.getElementById('quick-run-btn');

  if (!code.trim()) { showToast('Please enter C code to run.'); return; }

  qrBtn.disabled = true;
  qrBtn.textContent = 'Running...';
  outBox.textContent = '$ Compiling and executing in sandbox...\n';
  outBox.style.color = '#38bdf8';

  try {
    const res = await fetch('/api/quick-run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, stdin: stdinVal })
    });

    const data = await res.json();
    qrBtn.disabled = false;
    qrBtn.textContent = '▶ Run with Stdin';

    if (!data.compiled) {
      outBox.style.color = '#f87171';
      outBox.textContent = `[COMPILATION FAILED (exit ${data.returncode})]\n${data.compile_output}`;
    } else if (data.timed_out) {
      outBox.style.color = '#f87171';
      outBox.textContent = `[TIMED OUT]\n${data.stderr}`;
    } else {
      outBox.style.color = '#38bdf8';
      let msg = `[OK] Finished in ${data.execution_time_s}s (exit ${data.returncode})\n`;
      if (data.compile_output) msg += `[DIAGNOSTICS]\n${data.compile_output}\n`;
      msg += `[STDOUT]\n${data.stdout || '(no output)'}\n`;
      if (data.stderr) msg += `[STDERR]\n${data.stderr}\n`;
      outBox.textContent = msg;
    }
  } catch (err) {
    qrBtn.disabled = false;
    qrBtn.textContent = '▶ Run with Stdin';
    outBox.style.color = '#f87171';
    outBox.textContent = `Error: ${err.message}`;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Full Grading
// ═══════════════════════════════════════════════════════════════════════════

async function handleGrade() {
  const code = editor.getValue();
  const overlay = document.getElementById('loading-overlay');
  const gradeBtn = document.getElementById('grade-btn');

  if (!code.trim()) { showToast('Please enter C code before grading.'); return; }

  overlay.classList.add('active');
  gradeBtn.disabled = true;

  try {
    const presetSelect = document.getElementById('preset-select');
    const submissionName = presetSelect ? presetSelect.value : 'submission.c';

    // Pick the selected rules file from the grade-rules dropdown
    const gradeRulesSelect = document.getElementById('grade-rules-select');
    const selectedRules = gradeRulesSelect ? gradeRulesSelect.value : 'add_rules.json';

    const res = await fetch('/api/grade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        submission_file: submissionName,
        rules_file: selectedRules
      })
    });

    const report = await res.json();
    overlay.classList.remove('active');
    gradeBtn.disabled = false;

    if (!res.ok) {
      alert(`Grading Error: ${report.error || 'Failed to grade submission'}`);
      return;
    }

    lastReportData = report;
    renderResults(report, selectedRules);
    showToast(`Grading Complete: ${report.grade} / 100`);

  } catch (err) {
    overlay.classList.remove('active');
    gradeBtn.disabled = false;
    alert(`Grading failed: ${err.message}`);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Render Results (Code Tab — right column)
// ═══════════════════════════════════════════════════════════════════════════

function renderResults(report, rulesFile) {
  const rubricCard = document.getElementById('rubric-overview-card');
  const resultsContainer = document.getElementById('results-container');
  if (rubricCard) rubricCard.style.display = 'none';
  if (resultsContainer) resultsContainer.style.display = 'block';

  // 1. Grade Letter & Score
  const grade = Number(report.grade || 0);
  const gradeNumEl = document.getElementById('grade-number');
  const gradeLetterEl = document.getElementById('grade-letter');
  const gradeVerdictEl = document.getElementById('grade-verdict');

  if (gradeNumEl) gradeNumEl.textContent = grade.toFixed(1);

  let letter = 'F', letterBg = 'var(--color-danger)', verdictText = 'Needs Revisions';
  if (grade >= 88)       { letter = 'A'; letterBg = 'var(--color-success)'; verdictText = 'Outstanding — Production Ready'; }
  else if (grade >= 75)  { letter = 'B'; letterBg = 'var(--color-primary)'; verdictText = 'Good — Minor Improvements Needed'; }
  else if (grade >= 60)  { letter = 'C'; letterBg = 'var(--color-warning)'; verdictText = 'Acceptable — Review Edge Cases & Modularity'; }
  else if (grade >= 40)  { letter = 'D'; letterBg = 'var(--color-warning)'; verdictText = 'Passable — Critical Flaws Present'; }

  if (gradeLetterEl) { gradeLetterEl.textContent = letter; gradeLetterEl.style.background = letterBg; }
  if (gradeVerdictEl) gradeVerdictEl.textContent = verdictText;

  // 2. Meta Row
  const timeEl = document.getElementById('eval-time');
  const rulesEl = document.getElementById('rules-used');
  const compEl = document.getElementById('compile-status');
  const loopEl = document.getElementById('loop-status');

  if (timeEl) timeEl.textContent = `${report.total_time_s || 0}s`;
  if (rulesEl) rulesEl.textContent = rulesFile || 'add_rules.json';
  if (compEl) {
    const ok = report.first_pass?.compiled;
    compEl.textContent = ok ? '✓ Passed' : '✕ Failed';
    compEl.style.color = ok ? 'var(--color-success)' : 'var(--color-danger)';
  }
  if (loopEl) {
    const loop = report.first_pass?.suspected_infinite_loop;
    loopEl.textContent = loop ? '⚠ Suspected' : '✓ Safe';
    loopEl.style.color = loop ? 'var(--color-danger)' : 'var(--color-success)';
  }

  // 3. Defense Loop
  const defenseSummary = document.getElementById('defense-summary');
  const defenseList = document.getElementById('defense-dismissed-list');
  const logicalMetric = (report.metrics || []).find(m => m.name === 'logical' || m.analyzer === 'edge_case_runner');
  const dismissed = logicalMetric?.evidence?.defended_against_llm || [];

  if (defenseList) {
    if (dismissed.length > 0) {
      defenseSummary.textContent = `The agent defended against ${dismissed.length} false LLM allegation(s) using the Python reference oracle:`;
      defenseList.innerHTML = dismissed.map(d => `
        <div class="defense-item">
          <strong style="color:var(--color-success);">✓ DISMISSED:</strong> Input <code>${escapeHtml(d.input)}</code> — Output matched reference. LLM claim dismissed.
        </div>
      `).join('');
    } else {
      defenseSummary.textContent = `All adversarial cases were checked against the Python solver oracle before evaluation.`;
      defenseList.innerHTML = '';
    }
  }

  // 4. Metrics Table
  const tbody = document.getElementById('metrics-table-body');
  if (tbody) {
    tbody.innerHTML = (report.metrics || []).map(m => {
      const rawScore = Number(m.score || 0);
      const scorePct = Math.round(rawScore * 100);
      const weightPct = Math.round((m.weight || 0) * 100);
      const earned = Number(m.contribution || 0).toFixed(1);

      let pillClass = 'pass';
      if (rawScore < 0.5) pillClass = 'fail';
      else if (rawScore < 0.8) pillClass = 'warn';

      let fb = (m.feedback || 'Evaluated.').replace(/\n/g, ' ').replace(/\r/g, '').trim();
      if (fb.length > 70) fb = fb.substring(0, 67) + '...';

      return `
        <tr>
          <td><strong>${escapeHtml(m.name)}</strong></td>
          <td>${weightPct}%</td>
          <td><span class="score-pill ${pillClass}">${scorePct}%</span></td>
          <td><strong>${earned}</strong></td>
          <td style="color:var(--text-secondary);">${escapeHtml(fb)}</td>
        </tr>
      `;
    }).join('');
  }

  // 5. Failures
  const failuresCard = document.getElementById('failures-card');
  const failuresContainer = document.getElementById('failures-container');
  const failingTests = [];

  (report.metrics || []).forEach(m => {
    if (m.evidence?.failing && Array.isArray(m.evidence.failing))
      m.evidence.failing.forEach(f => failingTests.push(f));
    if (m.evidence?.counter_test_cases && Array.isArray(m.evidence.counter_test_cases))
      m.evidence.counter_test_cases.forEach(f => failingTests.push(f));
  });

  if (failuresCard && failuresContainer) {
    if (failingTests.length > 0) {
      failuresCard.style.display = 'block';
      failuresContainer.innerHTML = failingTests.slice(0, 3).map(f => `
        <div class="failure-item">
          <div class="failure-grid">
            <div class="failure-cell">
              <div class="failure-cell-label">Input</div>
              <code>${escapeHtml(f.input || '')}</code>
            </div>
            <div class="failure-cell">
              <div class="failure-cell-label">Expected</div>
              <div style="color:var(--color-success);"><code>${escapeHtml(f.expected || '')}</code></div>
            </div>
            <div class="failure-cell">
              <div class="failure-cell-label">Your Output</div>
              <div style="color:var(--color-danger);"><code>${escapeHtml(f.got || '')}</code></div>
            </div>
          </div>
          <div style="color:#fca5a5; font-size:0.75rem; margin-top:0.25rem;">
            <strong>Root Cause:</strong> ${escapeHtml(f.note || f.explanation || 'Output mismatch')}
          </div>
        </div>
      `).join('');
    } else {
      failuresCard.style.display = 'none';
    }
  }

  // 6. Suggestions
  const suggCard = document.getElementById('suggestions-card');
  const suggList = document.getElementById('suggestions-list');
  const suggestions = [];

  (report.metrics || []).forEach(m => {
    if (m.score < 1.0 && m.feedback) {
      if (m.name === 'correctness') suggestions.push('Handle boundary overflow using wider 64-bit types (e.g. <code>long long</code>).');
      else if (m.name === 'modularity') suggestions.push('Extract helper function(s) like <code>long long add(long long a, long long b)</code> from <code>main()</code>.');
      else if (m.name === 'readability') suggestions.push('Use meaningful variable names (e.g. <code>num1, num2</code>) and add brief comments.');
      else if (m.name === 'structure') suggestions.push('Add function prototypes and keep cyclomatic complexity low.');
    }
  });

  if (suggCard && suggList) {
    if (suggestions.length > 0) {
      suggCard.style.display = 'block';
      suggList.innerHTML = suggestions.map(s => `<li>${s}</li>`).join('');
    } else {
      suggCard.style.display = 'none';
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Rules Tab — Load & Populate
// ═══════════════════════════════════════════════════════════════════════════

function initRulesTabEvents() {
  const loadBtn = document.getElementById('load-rules-btn');
  if (loadBtn) loadBtn.addEventListener('click', () => {
    const sel = document.getElementById('rules-file-select');
    if (sel && sel.value) loadRuleFile(sel.value);
  });

  const newBtn = document.getElementById('new-rules-btn');
  if (newBtn) newBtn.addEventListener('click', createBlankRuleSet);

  const saveBtn = document.getElementById('save-rules-btn');
  if (saveBtn) saveBtn.addEventListener('click', saveRules);
}

async function loadRulesList() {
  try {
    const res = await fetch('/api/rules');
    const data = await res.json();
    const files = data.rules || [];

    // Populate the Rules Tab selector
    const rulesSel = document.getElementById('rules-file-select');
    if (rulesSel) {
      rulesSel.innerHTML = files.map(f => `<option value="${escapeHtml(f.filename)}">${escapeHtml(f.filename)} — ${escapeHtml(f.problem || '')}</option>`).join('');
    }

    // Populate the Grade Tab rules selector
    const gradeRulesSel = document.getElementById('grade-rules-select');
    if (gradeRulesSel) {
      gradeRulesSel.innerHTML = files.map(f => `<option value="${escapeHtml(f.filename)}">${escapeHtml(f.filename)}</option>`).join('');
    }

    // Auto-load the first rules file (usually add_rules.json)
    if (files.length > 0) {
      await loadRuleFile(files[0].filename);
    }
  } catch (e) {
    console.error('Failed to load rules list:', e);
  }
}

async function loadRuleFile(filename) {
  try {
    const res = await fetch(`/api/rules/${filename}`);
    if (!res.ok) { showToast(`Could not load ${filename}`); return; }
    const data = await res.json();
    activeRulesData = data;
    activeRulesFile = filename;

    // Sync dropdown selections
    const gradeRulesSel = document.getElementById('grade-rules-select');
    if (gradeRulesSel && gradeRulesSel.value !== filename) {
      gradeRulesSel.value = filename;
    }
    const rulesSel = document.getElementById('rules-file-select');
    if (rulesSel && rulesSel.value !== filename) {
      rulesSel.value = filename;
    }

    // Update problem banner (Code Tab)
    updateBanner(data, filename);

    // Update rubric overview card (Code Tab)
    updateRubricOverview(data);

    // Populate Rules Tab form fields
    populateRulesForm(data, filename);

  } catch (e) {
    console.error('Failed to load rule file:', e);
    showToast('Error loading rule file');
  }
}

function updateBanner(rules, filename) {
  const titleEl = document.getElementById('banner-problem-title');
  const descEl = document.getElementById('banner-problem-desc');
  const timeEl = document.getElementById('banner-time-limit');
  const memEl = document.getElementById('banner-mem-limit');
  const fileEl = document.getElementById('banner-rules-file');
  const stdinEl = document.getElementById('stdin-input');

  if (titleEl) titleEl.textContent = (rules.problem || filename).replace(/_/g, ' ');
  if (descEl)  descEl.textContent  = rules.problem_description || 'No description provided.';
  if (timeEl)  timeEl.textContent  = `${rules.time_limit_s || 1}s`;
  if (memEl)   memEl.textContent   = `${rules.memory_limit_mb || 64} MB`;
  if (fileEl)  fileEl.textContent  = filename;

  if (stdinEl && rules.sample_input) {
    stdinEl.value = rules.sample_input.trim();
  }
}

function updateRubricOverview(rules) {
  const rubricList = document.getElementById('rubric-list');
  const badge = document.getElementById('rubric-status-badge');
  if (badge) badge.textContent = `${(rules.metrics || []).length} Criteria`;

  if (rubricList) {
    rubricList.innerHTML = (rules.metrics || []).map((m, i) => `
      <div class="rubric-item">
        <div class="rubric-meta">
          <span class="rubric-name">${i + 1}. ${capitalize(m.name)}</span>
          <span class="rubric-weight">${Math.round((m.weight || 0) * 100)}% Weight</span>
        </div>
        <div class="rubric-desc">${analyzerDescription(m.analyzer)}</div>
      </div>
    `).join('');
  }
}

function analyzerDescription(analyzer) {
  const map = {
    io_tests:            'Standard I/O test cases including boundary & edge inputs.',
    compiler_warnings:   'Strict compilation diagnostics with -Wall -Wextra -Werror.',
    static_analysis:     'Function length and Cyclomatic Complexity checks.',
    function_split:      'Verifies extraction of modular helper functions.',
    edge_case_runner:    'Adversarial corner cases with reality-check defense loop.',
    complexity_estimator:'Empirical timing confirms O(1) constant time requirement.',
    sanitizer_run:       'AddressSanitizer and UndefinedBehaviorSanitizer inspection.',
    llm_review:          'LLM code readability, naming, and style review.',
    similarity_flag:     'Plagiarism and token similarity screening.'
  };
  return map[analyzer] || `Analyzer: ${analyzer}`;
}

function populateRulesForm(rules, filename) {
  // Problem config fields
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
  setVal('rule-problem-name',  rules.problem);
  setVal('rule-problem-desc',  rules.problem_description);
  setVal('rule-time-limit',    rules.time_limit_s);
  setVal('rule-mem-limit',     rules.memory_limit_mb);
  setVal('rule-sample-input',  rules.sample_input);
  setVal('rule-sample-output', rules.sample_output);
  setVal('rule-llm-model',     rules.llm_config?.model || 'llama3.1');
  setVal('rule-llm-temp',      rules.llm_config?.temperature ?? 0);
  setVal('save-rules-filename', filename);

  // Time & Space Complexity Big-O
  const compMetric = (rules.metrics || []).find(m => m.analyzer === 'complexity_estimator');
  const reqTime = compMetric?.params?.required || 'O(1)';
  const reqSpace = compMetric?.params?.required_space || 'O(1)';
  const compSel = document.getElementById('rule-required-complexity');
  if (compSel) compSel.value = reqTime;
  const spaceSel = document.getElementById('rule-required-space');
  if (spaceSel) spaceSel.value = reqSpace;

  // Sync the file selector to show the loaded file
  const rulesSel = document.getElementById('rules-file-select');
  if (rulesSel) rulesSel.value = filename;

  // Render manual weight inputs
  renderWeightInputs(rules.metrics || []);
}

function renderWeightInputs(metrics) {
  const container = document.getElementById('metrics-weight-editor');
  if (!container) return;

  container.innerHTML = metrics.map((m, i) => {
    const pct = Math.round((m.weight || 0) * 100);
    return `
      <div class="metric-weight-row">
        <div>
          <div class="metric-label">${capitalize(m.name)}</div>
          <div class="metric-analyzer-tag">${m.analyzer}</div>
        </div>
        <div class="metric-manual-input-group">
          <input
            type="number"
            class="text-control metric-weight-input"
            id="weight-input-${i}"
            data-index="${i}"
            min="0"
            max="100"
            step="1"
            value="${pct}"
            oninput="onWeightChange(${i})"
            onchange="onWeightChange(${i})"
          >
          <span class="metric-unit">%</span>
        </div>
      </div>
    `;
  }).join('');

  updateWeightSum();
}

function onWeightChange(index) {
  const input = document.getElementById(`weight-input-${index}`);
  if (input) {
    let val = parseInt(input.value, 10);
    if (isNaN(val)) val = 0;
    if (val < 0) val = 0;
    if (val > 100) val = 100;
    input.value = val;
  }
  updateWeightSum();
}

function updateWeightSum() {
  let total = 0;
  document.querySelectorAll('.metric-weight-input').forEach(s => {
    const val = parseInt(s.value, 10);
    total += isNaN(val) ? 0 : val;
  });

  const badge = document.getElementById('weight-sum-badge');
  if (badge) {
    badge.textContent = `Total: ${total}%`;
    if (total === 100) {
      badge.classList.remove('invalid');
    } else {
      badge.classList.add('invalid');
    }
  }
  return total;
}

function createBlankRuleSet() {
  const blank = {
    problem: 'new_problem',
    problem_description: 'Describe the problem here so Ollama can generate test cases.',
    time_limit_s: 1,
    memory_limit_mb: 64,
    sample_input: '',
    sample_output: '',
    llm_config: { model: 'llama3.1', temperature: 0, seed: 42 },
    metrics: [
      { name: 'correctness',   analyzer: 'io_tests',             weight: 0.30, params: { testset_dir: 'tests/new_problem/', auto_generate: true, num_tests: 10 } },
      { name: 'syntax',        analyzer: 'compiler_warnings',    weight: 0.15, params: { flags: '-Wall -Wextra -Werror -std=c11' } },
      { name: 'structure',     analyzer: 'static_analysis',      weight: 0.10, params: { max_cyclomatic: 8, max_function_length: 40 } },
      { name: 'modularity',    analyzer: 'function_split',       weight: 0.10, params: { expect_helpers: true, min_functions: 2 } },
      { name: 'logical',       analyzer: 'edge_case_runner',     weight: 0.10, params: { auto_generate: true, cases: ['negatives', 'zero'] } },
      { name: 'complexity',    analyzer: 'complexity_estimator', weight: 0.10, params: { required: 'O(1)', sizes: [1, 10, 100] } },
      { name: 'memory_safety', analyzer: 'sanitizer_run',        weight: 0.05, params: { flags: '-fsanitize=address,undefined' } },
      { name: 'readability',   analyzer: 'llm_review',          weight: 0.05, params: { model: 'llama3.1', temperature: 0, seed: 42 } },
      { name: 'originality',   analyzer: 'similarity_flag',     weight: 0.05, params: { corpus_dir: 'corpus/', flag_threshold: 0.85 } }
    ]
  };
  activeRulesData = blank;
  populateRulesForm(blank, 'new_rules.json');
  showToast('Blank rule set created — set problem name & description, then save.');
}

async function saveRules() {
  if (!activeRulesData) { showToast('No rules loaded to save.'); return; }

  // Gather form values back into the rules object
  const getVal = id => { const el = document.getElementById(id); return el ? el.value : ''; };

  const problemName = getVal('rule-problem-name').trim() || 'custom';
  // Sanitize problem name to a safe directory name (lowercase, underscores)
  const safeName = problemName.toLowerCase().replace(/[^a-z0-9_]/g, '_');

  const updatedRules = {
    ...activeRulesData,
    problem: problemName,
    problem_description: getVal('rule-problem-desc'),
    time_limit_s: parseFloat(getVal('rule-time-limit')) || 1,
    memory_limit_mb: parseInt(getVal('rule-mem-limit'), 10) || 64,
    sample_input: getVal('rule-sample-input'),
    sample_output: getVal('rule-sample-output'),
    llm_config: {
      ...(activeRulesData.llm_config || {}),
      model: getVal('rule-llm-model') || 'llama3.1',
      temperature: parseFloat(getVal('rule-llm-temp')) || 0
    }
  };

  // Collect manual weights
  const total = updateWeightSum();
  if (total !== 100) {
    showToast(`Weights sum to ${total}% — must be exactly 100%`);
    return;
  }

  const reqTime = getVal('rule-required-complexity') || 'O(1)';
  const reqSpace = getVal('rule-required-space') || 'O(1)';

  updatedRules.metrics = (activeRulesData.metrics || []).map((m, i) => {
    const input = document.getElementById(`weight-input-${i}`);
    const newWeight = input ? (parseInt(input.value, 10) || 0) / 100 : m.weight;
    // Auto-update testset_dir for io_tests to use problem-specific folder
    let params = { ...m.params };
    if (m.analyzer === 'io_tests' && params.testset_dir) {
      params.testset_dir = `tests/${safeName}/`;
    }
    if (m.analyzer === 'complexity_estimator') {
      params.required = reqTime;
      params.required_space = reqSpace;
    }
    if (m.analyzer === 'similarity_flag') {
      if (!params.corpus_dir || params.corpus_dir === 'submissions/' || params.corpus_dir === 'submissions') {
        params.corpus_dir = 'corpus/';
      }
    }
    return { ...m, weight: newWeight, params };
  });

  const filename = getVal('save-rules-filename') || 'custom_rules.json';
  const saveBtn = document.getElementById('save-rules-btn');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

  try {
    const res = await fetch('/api/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, rules: updatedRules })
    });

    const result = await res.json();
    if (res.ok && result.success) {
      activeRulesData = updatedRules;
      activeRulesFile = result.filename;
      showToast(`✓ Saved: ${result.filename}`);

      // Refresh the dropdowns and banner
      await loadRulesList();

      // Re-select saved file in grade dropdown
      const gradeRulesSel = document.getElementById('grade-rules-select');
      if (gradeRulesSel) gradeRulesSel.value = result.filename;

      updateBanner(updatedRules, result.filename);
      updateRubricOverview(updatedRules);
    } else {
      showToast(`Error: ${result.error || 'Save failed'}`);
    }
  } catch (e) {
    showToast(`Save failed: ${e.message}`);
  } finally {
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '💾 Save Rules'; }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Reports Tab
// ═══════════════════════════════════════════════════════════════════════════

function initReportsTabEvents() {
  const refreshBtn = document.getElementById('refresh-reports-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadReports);
}

async function loadReports() {
  const tbody = document.getElementById('reports-table-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:1.5rem;">Loading...</td></tr>';

  try {
    const res = await fetch('/api/reports');
    const data = await res.json();
    const reports = data.reports || [];

    if (reports.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:1.5rem;">No reports yet. Grade a submission first.</td></tr>';
      return;
    }

    tbody.innerHTML = reports.map(r => {
      const grade = Number(r.grade || 0);
      let pillClass = grade >= 75 ? 'pass' : grade >= 50 ? 'warn' : 'fail';
      return `
        <tr>
          <td><strong>${escapeHtml(r.submission || r.filename)}</strong></td>
          <td><span class="score-pill ${pillClass}">${grade.toFixed(1)}</span></td>
          <td style="color:${r.compiled ? 'var(--color-success)' : 'var(--color-danger)'}">
            ${r.compiled ? '✓ Yes' : '✕ No'}
          </td>
          <td style="color:var(--text-muted);">${r.total_time_s ? r.total_time_s + 's' : '—'}</td>
          <td style="color:var(--text-muted); font-size:0.78rem;">${r.graded_at || '—'}</td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--color-danger);">Failed to load reports: ${e.message}</td></tr>`;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Report Downloads
// ═══════════════════════════════════════════════════════════════════════════

function downloadTextReport() {
  if (!lastReportData?.text_report) { showToast('No report text available.'); return; }
  const blob = new Blob([lastReportData.text_report], { type: 'text/plain;charset=utf-8' });
  triggerDownload(blob, `grade_${lastReportData.submission || 'report'}.txt`);
}

function downloadJsonReport() {
  if (!lastReportData) { showToast('No report available.'); return; }
  const blob = new Blob([JSON.stringify(lastReportData, null, 2)], { type: 'application/json' });
  triggerDownload(blob, `grade_${lastReportData.submission || 'report'}.json`);
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ═══════════════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════════════

function showToast(msg) {
  const toast = document.getElementById('toast-message');
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.add('active');
  setTimeout(() => toast.classList.remove('active'), 3200);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// Expose global functions called from HTML onclick attributes
window.downloadTextReport = downloadTextReport;
window.downloadJsonReport = downloadJsonReport;
window.onWeightChange = onWeightChange;
