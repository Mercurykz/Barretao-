# Barretão HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar o webapp do Barretão em um painel de controle estilo Jarvis com status bar, navegação por abas (HUD / Chat / Memória), anel animado com estados, widgets de briefing/sistema, grid de atalhos e waveform de voz.

**Architecture:** A `<header>` atual é substituída por uma status bar permanente + tab bar. O conteúdo existente (`#messages` + `#input-area`) vira o painel da aba Chat. Dois novos painéis são adicionados: `#hud-panel` (aba HUD) e `#memory-panel` (aba Memória). Um novo endpoint `GET /status` no hub fornece CPU, RAM, modelo e uptime.

**Tech Stack:** HTML/CSS/JS vanilla (inline no index.html), Python + FastAPI (barretao_hub.py), psutil para métricas de sistema

---

## Arquivos Modificados

| Arquivo | Mudança |
|---|---|
| `barretao_hub.py` | Adicionar endpoint `GET /status` (linhas ~540) |
| `webapp/index.html` | (1) CSS novo — status bar, tab bar, HUD, waveform, chips; (2) HTML — substituir `<header>` por statusbar+tabbar, adicionar painéis HUD e Memória; (3) JS — tab switching, polling, ring state machine, waveform trigger |

---

## Task 1: Endpoint `/status` no backend

**Files:**
- Modify: `barretao_hub.py:1-10` (import psutil)
- Modify: `barretao_hub.py:538-541` (inserir após `/health`)

- [ ] **Step 1: Instalar psutil se necessário**

```bash
.\.venv311\Scripts\pip.exe install psutil
```

Esperado: `Successfully installed psutil-X.X.X` ou `already satisfied`.

- [ ] **Step 2: Adicionar import psutil em barretao_hub.py**

No topo do arquivo, após a linha `import shutil` (linha ~11), adicionar:

```python
try:
    import psutil as _psutil
    _PSUTIL_OK = True
except ImportError:
    _psutil = None
    _PSUTIL_OK = False
```

- [ ] **Step 3: Registrar start_time no lifespan**

Procure a função `lifespan` (ou o bloco `@asynccontextmanager` / `startup`). Se não existir, adicione logo após a criação do `app = FastAPI(...)`:

```python
import time as _time
_APP_START = _time.time()
```

Se já houver um `_APP_START` ou `start_time`, use o nome existente.

- [ ] **Step 4: Adicionar endpoint `/status` após o endpoint `/health` (linha ~540)**

```python
@app.get("/status")
def api_status(authorization: Optional[str] = Header(default=None)) -> dict:
    require_auth(authorization)
    cpu = round(_psutil.cpu_percent(interval=0.1), 1) if _PSUTIL_OK else 0.0
    mem = _psutil.virtual_memory() if _PSUTIL_OK else None
    ram_used = round(mem.used / 1024**3, 1) if mem else 0.0
    ram_total = round(mem.total / 1024**3, 1) if mem else 0.0
    uptime = int(_time.time() - _APP_START)
    provider = getattr(agent, "llm_provider", "ollama")
    model = getattr(agent, "model", getattr(agent, "ollama_model", "—"))
    discord_on = bool(getattr(agent, "discord_enabled", False))
    return {
        "ok": True,
        "cpu_percent": cpu,
        "ram_used_gb": ram_used,
        "ram_total_gb": ram_total,
        "uptime_seconds": uptime,
        "model": model,
        "provider": provider,
        "discord_enabled": discord_on,
    }
```

- [ ] **Step 5: Testar o endpoint manualmente**

Com o hub rodando:
```bash
curl -H "Authorization: Bearer SEU_TOKEN" http://localhost:8787/status
```

Esperado:
```json
{"ok": true, "cpu_percent": 8.2, "ram_used_gb": 4.1, "ram_total_gb": 16.0, ...}
```

- [ ] **Step 6: Commit**

```bash
git add barretao_hub.py
git commit -m "feat: add /status endpoint with CPU, RAM, uptime, model info"
```

---

## Task 2: CSS — Status Bar + Tab Bar

**Files:**
- Modify: `webapp/index.html` (bloco `<style>` existente — adicionar no final, antes do `</style>`)

- [ ] **Step 1: Localizar o fechamento do bloco `<style>`**

Busque a string `</style>` no arquivo. Ela está por volta da linha 1065. Insira o CSS abaixo imediatamente **antes** desse `</style>`.

- [ ] **Step 2: Adicionar CSS da status bar e tab bar**

```css
/* ══════════════════════════════════════════════════════
   BARRETÃO HUD — Status Bar + Tab Bar
   ══════════════════════════════════════════════════════ */

/* ── Status Bar ── */
#hud-statusbar {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 14px;
  background: rgba(0,8,24,.96);
  border-bottom: 1px solid var(--border);
  font-size: 10px; font-family: 'Courier New', monospace;
  flex-shrink: 0; position: relative; overflow: hidden;
  z-index: 10;
}
#hud-statusbar::after {
  content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: .35;
}
.sb-pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--green);
  box-shadow: 0 0 6px var(--green); flex-shrink: 0; animation: sb-blink 2.5s infinite; }
@keyframes sb-blink { 0%,100%{opacity:1} 50%{opacity:.3} }
.sb-val { color: var(--accent); }
.sb-lbl { color: var(--text2); margin-right: 2px; }
.sb-sep { color: var(--border); }
#sb-time { color: var(--accent); font-weight: 700; letter-spacing: 1px; margin-left: auto; }
#sb-model { color: var(--accent-2); font-size: 9px; opacity: .65; }

/* ── Tab Bar ── */
#hud-tabbar {
  display: flex; background: rgba(0,5,16,.96);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.hud-tab {
  flex: 1; padding: 10px 6px; text-align: center; font-size: 12px; color: var(--text2);
  cursor: pointer; border-bottom: 2px solid transparent; transition: .2s;
  display: flex; align-items: center; justify-content: center; gap: 5px;
  user-select: none; -webkit-user-select: none;
}
.hud-tab.active { color: var(--accent); border-bottom-color: var(--accent); background: rgba(0,207,255,.04); }
.hud-tab:hover:not(.active) { color: var(--text); background: rgba(255,255,255,.02); }

/* ── Tab Panels ── */
.hud-panel { display: none; flex: 1; overflow-y: auto; flex-direction: column; }
.hud-panel.active { display: flex; }

/* ── HUD Panel Content ── */
#hud-panel { padding: 14px; gap: 12px; }

.hud-arc-header {
  display: flex; align-items: center; gap: 16px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; position: relative; overflow: hidden; flex-shrink: 0;
}
.hud-arc-header::before {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(0,207,255,.03), rgba(136,0,255,.03));
}
.arc-corner { position: absolute; width: 12px; height: 12px; border-color: rgba(0,207,255,.25); border-style: solid; }
.arc-corner.tl { top: 7px; left: 7px; border-width: 1px 0 0 1px; }
.arc-corner.tr { top: 7px; right: 7px; border-width: 1px 1px 0 0; }
.arc-corner.bl { bottom: 7px; left: 7px; border-width: 0 0 1px 1px; }
.arc-corner.br { bottom: 7px; right: 7px; border-width: 0 1px 1px 0; }

#arc-ring {
  width: 52px; height: 52px; border-radius: 50%;
  border: 2px solid var(--accent); display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 900; font-family: 'Courier New', monospace; color: var(--accent);
  box-shadow: 0 0 20px rgba(0,207,255,.3), inset 0 0 10px rgba(0,207,255,.08);
  position: relative; flex-shrink: 0;
  transition: border-color .5s, box-shadow .5s, color .5s;
}
#arc-ring::before {
  content: ''; position: absolute; width: 42px; height: 42px; border-radius: 50%;
  border: 1px dashed rgba(0,207,255,.22);
  animation: arc-spin 6s linear infinite;
}
@keyframes arc-spin { to { transform: rotate(360deg); } }
#arc-ring.thinking { border-color: var(--accent-2); color: var(--accent-2);
  box-shadow: 0 0 20px rgba(136,0,255,.4), inset 0 0 10px rgba(136,0,255,.1); }
#arc-ring.thinking::before { animation-duration: 1.5s; border-color: rgba(136,0,255,.3); }
#arc-ring.speaking { border-color: var(--green); color: var(--green);
  box-shadow: 0 0 20px rgba(0,255,153,.4), inset 0 0 10px rgba(0,255,153,.1); }
#arc-ring.speaking::before { animation-duration: 0.8s; border-color: rgba(0,255,153,.3); }
#arc-ring.error { border-color: var(--accent2); color: var(--accent2); }
@keyframes arc-idle-pulse {
  0%,100% { box-shadow: 0 0 12px rgba(0,207,255,.25), inset 0 0 6px rgba(0,207,255,.06); }
  50% { box-shadow: 0 0 28px rgba(0,207,255,.55), inset 0 0 14px rgba(0,207,255,.13); }
}
#arc-ring:not(.thinking):not(.speaking):not(.error) { animation: arc-idle-pulse 3s ease-in-out infinite; }

.arc-info .arc-name { font-size: 16px; font-weight: 700; color: var(--accent); letter-spacing: 1px; }
.arc-info .arc-status { font-size: 11px; color: var(--text2); margin-top: 3px; }
.arc-info .arc-status span { color: var(--green); }

/* Widget Grid */
.hud-widget-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.hud-widget {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px;
}
.hud-widget-title { font-size: 9px; letter-spacing: 1.5px; color: var(--text2); text-transform: uppercase; margin-bottom: 8px; }
.hud-widget-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid rgba(0,180,255,.06); font-size: 12px; }
.hud-widget-row:last-child { border: none; }
.hud-widget-row .wr-lbl { color: var(--text2); font-size: 11px; }
.hud-widget-row .wr-val { color: var(--accent); font-weight: 600; }
.hud-widget-row .wr-val.ok { color: var(--green); }
.hud-widget-row .wr-val.warn { color: var(--accent2); }

/* Shortcuts Grid */
.hud-shortcuts-title { font-size: 9px; letter-spacing: 1.5px; color: var(--text2); text-transform: uppercase; margin-bottom: 10px; }
.hud-shortcuts-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.sc-btn {
  background: rgba(0,180,255,.04); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 6px; text-align: center; cursor: pointer; transition: .15s;
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.sc-btn:hover { background: rgba(0,180,255,.12); border-color: rgba(0,207,255,.3); transform: translateY(-1px); }
.sc-btn:active { transform: scale(.96); }
.sc-btn .sc-icon { font-size: 18px; line-height: 1; }
.sc-btn .sc-name { font-size: 9px; color: var(--text2); }
.sc-btn.sc-add { border-style: dashed; opacity: .5; }
.sc-btn.sc-add:hover { opacity: .8; }

/* ── Waveform (Chat tab) ── */
.waveform-bubble {
  display: flex; align-items: center; gap: 3px;
  padding: 11px 14px; border-radius: 18px; border-bottom-left-radius: 5px;
  background: var(--bubble-agent); border: 1px solid var(--border);
  box-shadow: var(--shadow); align-self: flex-start; min-width: 80px;
}
.wv-bar {
  width: 3px; background: var(--accent); border-radius: 2px;
  animation: wv-wave 1s ease-in-out infinite;
}
.wv-bar:nth-child(1){height:5px;animation-delay:0s}
.wv-bar:nth-child(2){height:10px;animation-delay:.1s}
.wv-bar:nth-child(3){height:18px;animation-delay:.2s}
.wv-bar:nth-child(4){height:24px;animation-delay:.3s}
.wv-bar:nth-child(5){height:18px;animation-delay:.4s}
.wv-bar:nth-child(6){height:10px;animation-delay:.5s}
.wv-bar:nth-child(7){height:5px;animation-delay:.6s}
@keyframes wv-wave { 0%,100%{transform:scaleY(.35);opacity:.4} 50%{transform:scaleY(1);opacity:1} }

/* ── Shortcut Chips (Chat tab) ── */
#chat-chips {
  display: flex; gap: 6px; overflow-x: auto; padding: 6px 12px 2px; flex-shrink: 0;
  scrollbar-width: none;
}
#chat-chips::-webkit-scrollbar { display: none; }
.chat-chip {
  white-space: nowrap; border: 1px solid var(--border); border-radius: 20px;
  padding: 5px 13px; font-size: 11px; color: var(--accent); cursor: pointer; flex-shrink: 0;
  background: rgba(0,180,255,.04); transition: .15s;
}
.chat-chip:hover { background: rgba(0,180,255,.14); border-color: rgba(0,207,255,.35); }
.chat-chip:active { transform: scale(.96); }

/* ── Memory Panel ── */
#memory-panel { padding: 14px; gap: 10px; }
.mem-section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.mem-section-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; cursor: pointer; user-select: none;
  border-bottom: 1px solid var(--border);
}
.mem-section-header span { font-size: 12px; font-weight: 700; color: var(--text); }
.mem-section-header .mem-count { font-size: 10px; color: var(--text2); }
.mem-item {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 9px 14px; border-bottom: 1px solid rgba(0,180,255,.05); gap: 8px;
  font-size: 12px; color: var(--text);
}
.mem-item:last-child { border: none; }
.mem-item .mem-tag { color: var(--accent-2); font-size: 10px; font-family: 'Courier New', monospace; flex-shrink: 0; }
.mem-item .mem-text { flex: 1; line-height: 1.4; }
.mem-del { background: none; border: none; color: rgba(255,255,255,.2); cursor: pointer; font-size: 13px; padding: 0; transition: .15s; flex-shrink: 0; }
.mem-del:hover { color: var(--accent2); }
.mem-empty { padding: 16px 14px; font-size: 12px; color: var(--text2); text-align: center; }
```

- [ ] **Step 3: Verificar no browser**

Abra `http://localhost:8787/app/` — não deve haver mudança visual ainda (CSS adicionado mas HTML ainda não atualizado).

---

## Task 3: HTML — Substituir `<header>` por Status Bar + Tab Bar

**Files:**
- Modify: `webapp/index.html:1091-1107` (bloco `<header>...</header>`)

- [ ] **Step 1: Localizar e substituir o bloco `<header>`**

Substituir o bloco inteiro (linhas 1091–1107):
```html
  <header>
    <div class="avatar">AIV<span style="color:#ff8800">4</span></div>
    ...
  </header>
```

Pelo seguinte HTML:

```html
  <!-- ── Status Bar ── -->
  <div id="hud-statusbar">
    <div class="sb-pulse"></div>
    <span><span class="sb-lbl">SP</span><span class="sb-val" id="sb-weather">—</span></span>
    <span class="sb-sep">·</span>
    <span><span class="sb-lbl">CPU</span><span class="sb-val" id="sb-cpu">—</span></span>
    <span><span class="sb-lbl">RAM</span><span class="sb-val" id="sb-ram">—</span></span>
    <span id="sb-model">—</span>
    <span id="sb-time">00:00</span>
  </div>

  <!-- ── Tab Bar ── -->
  <div id="hud-tabbar">
    <div class="hud-tab active" data-tab="chat" onclick="switchTab('chat')">💬 Chat</div>
    <div class="hud-tab" data-tab="hud" onclick="switchTab('hud')">🏠 HUD</div>
    <div class="hud-tab" data-tab="memory" onclick="switchTab('memory')">🧠 Memória</div>
    <div class="hud-tab" data-tab="settings" onclick="openSettings()">⚙️</div>
  </div>
```

- [ ] **Step 2: Envolver conteúdo do Chat em painel**

Localizar a div `<div id="messages">` (linha ~1109) e envolvê-la junto com `#input-area` em um painel. Para isso, adicionar `<div id="chat-panel" class="hud-panel active">` logo **antes** de `<div id="messages">` e fechar `</div>` logo **depois** do fechamento de `</div>` do `#input-area`.

O resultado deve ficar:
```html
  <div id="chat-panel" class="hud-panel active">
    <div id="messages">
      ...conteúdo existente...
    </div>

    <div id="input-area">
      ...conteúdo existente...
    </div>
  </div>
```

- [ ] **Step 3: Verificar estrutura no browser**

Recarregue `http://localhost:8787/app/`. Deve aparecer a tab bar no topo e o chat abaixo. A tab "💬 Chat" deve estar ativa.

---

## Task 4: HTML — Painel HUD

**Files:**
- Modify: `webapp/index.html` (adicionar após o fechamento de `#chat-panel`, antes do fechamento de `#app`)

- [ ] **Step 1: Localizar o fechamento de `#app`**

Procure a linha `</div>` que fecha `<div id="app">`. Adicione os novos painéis imediatamente **antes** dela.

- [ ] **Step 2: Inserir painel HUD**

```html
  <!-- ── HUD Panel ── -->
  <div id="hud-panel" class="hud-panel">

    <!-- Arc Reactor Header -->
    <div class="hud-arc-header">
      <div class="arc-corner tl"></div><div class="arc-corner tr"></div>
      <div class="arc-corner bl"></div><div class="arc-corner br"></div>
      <div id="arc-ring">AI</div>
      <div class="arc-info">
        <div class="arc-name">BARRETÃO</div>
        <div class="arc-status">Status: <span id="arc-status-text">ONLINE · AGUARDANDO</span></div>
        <div class="arc-status" style="margin-top:2px">Uptime: <span id="arc-uptime">—</span></div>
      </div>
    </div>

    <!-- Widget Grid -->
    <div class="hud-widget-grid">
      <!-- Briefing Widget -->
      <div class="hud-widget">
        <div class="hud-widget-title">📋 Briefing</div>
        <div class="hud-widget-row"><span class="wr-lbl">Gmail</span><span class="wr-val" id="hw-gmail">—</span></div>
        <div class="hud-widget-row"><span class="wr-lbl">Agenda</span><span class="wr-val ok" id="hw-agenda">—</span></div>
        <div class="hud-widget-row"><span class="wr-lbl">Clima</span><span class="wr-val" id="hw-clima">—</span></div>
      </div>
      <!-- System Widget -->
      <div class="hud-widget">
        <div class="hud-widget-title">🖥️ Sistema</div>
        <div class="hud-widget-row"><span class="wr-lbl">CPU</span><span class="wr-val ok" id="hw-cpu">—</span></div>
        <div class="hud-widget-row"><span class="wr-lbl">RAM</span><span class="wr-val" id="hw-ram">—</span></div>
        <div class="hud-widget-row"><span class="wr-lbl">Modelo</span><span class="wr-val" id="hw-model">—</span></div>
        <div class="hud-widget-row"><span class="wr-lbl">Discord</span><span class="wr-val" id="hw-discord">—</span></div>
      </div>
    </div>

    <!-- Shortcuts -->
    <div class="hud-widget">
      <div class="hud-shortcuts-title">⚡ Atalhos Rápidos</div>
      <div class="hud-shortcuts-grid" id="hud-shortcuts-grid">
        <!-- Preenchido via JS com dados de /memory -->
        <div class="sc-btn sc-add" onclick="sendMsg('/shortcut add')">
          <span class="sc-icon">＋</span>
          <span class="sc-name">Novo</span>
        </div>
      </div>
    </div>

  </div><!-- /#hud-panel -->
```

- [ ] **Step 3: Inserir painel Memória**

Logo após o fechamento do `#hud-panel`:

```html
  <!-- ── Memory Panel ── -->
  <div id="memory-panel" class="hud-panel">
    <div id="mem-facts-section" class="mem-section">
      <div class="mem-section-header" onclick="toggleMemSection('facts')">
        <span>🧠 Fatos Aprendidos</span>
        <span class="mem-count" id="mem-facts-count">0</span>
      </div>
      <div id="mem-facts-list"></div>
    </div>
    <div id="mem-notes-section" class="mem-section">
      <div class="mem-section-header" onclick="toggleMemSection('notes')">
        <span>📝 Notas</span>
        <span class="mem-count" id="mem-notes-count">0</span>
      </div>
      <div id="mem-notes-list"></div>
    </div>
    <div id="mem-routines-section" class="mem-section">
      <div class="mem-section-header" onclick="toggleMemSection('routines')">
        <span>🔄 Rotinas Semanais</span>
        <span class="mem-count" id="mem-routines-count">0</span>
      </div>
      <div id="mem-routines-list"></div>
    </div>
  </div><!-- /#memory-panel -->
```

- [ ] **Step 4: Verificar no browser**

Recarregue. A tab "🏠 HUD" deve aparecer na tab bar. Clicar nela (sem JS ainda) não fará nada — isso é esperado.

---

## Task 5: HTML — Shortcut Chips no Chat

**Files:**
- Modify: `webapp/index.html` — dentro de `#chat-panel`, imediatamente antes de `<div id="input-area">`

- [ ] **Step 1: Localizar `<div id="input-area">` dentro do chat-panel**

Adicionar a div de chips imediatamente **antes** da linha `<div id="input-area">`:

```html
  <!-- ── Shortcut Chips ── -->
  <div id="chat-chips">
    <!-- Preenchido via JS -->
  </div>
```

- [ ] **Step 2: Verificar no browser**

A faixa de chips vai aparecer como espaço vazio abaixo do chat (sem JS ainda). Esperado.

---

## Task 6: JavaScript — Tab Switching + Ring State Machine

**Files:**
- Modify: `webapp/index.html` — bloco `<script>` existente (localizado perto do final do arquivo, antes de `</body>`)

- [ ] **Step 1: Localizar o início do bloco `<script>`**

Procure `<script>` no arquivo (~linha 1550). Adicione as funções abaixo no início desse bloco (antes de qualquer `const` ou `function` existente):

```javascript
// ── HUD: Tab Switching ────────────────────────────────────────────────────
function switchTab(tabName) {
  document.querySelectorAll('.hud-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.hud-panel').forEach(p => p.classList.remove('active'));
  const tab = document.querySelector(`.hud-tab[data-tab="${tabName}"]`);
  const panel = document.getElementById(`${tabName}-panel`);
  if (tab) tab.classList.add('active');
  if (panel) panel.classList.add('active');
  if (tabName === 'memory') loadMemoryPanel();
}

// ── HUD: Ring State Machine ────────────────────────────────────────────────
const _ring = document.getElementById('arc-ring');
const _ringStatus = document.getElementById('arc-status-text');
function setRingState(state) {
  // state: 'idle' | 'thinking' | 'speaking' | 'error'
  if (!_ring) return;
  _ring.classList.remove('thinking', 'speaking', 'error');
  if (state !== 'idle') _ring.classList.add(state);
  const labels = { idle: 'ONLINE · AGUARDANDO', thinking: 'PROCESSANDO...', speaking: 'RESPONDENDO', error: 'ERRO' };
  if (_ringStatus) _ringStatus.textContent = labels[state] || labels.idle;
}

// ── HUD: Waveform ─────────────────────────────────────────────────────────
function createWaveformBubble() {
  const div = document.createElement('div');
  div.id = 'waveform-bubble';
  div.className = 'msg agent';
  div.innerHTML = `<div class="waveform-bubble">${'<div class="wv-bar"></div>'.repeat(7)}</div>`;
  return div;
}
function showWaveform() {
  removeWaveform();
  const msgs = document.getElementById('messages');
  if (!msgs) return;
  msgs.appendChild(createWaveformBubble());
  msgs.scrollTop = msgs.scrollHeight;
  setRingState('speaking');
}
function removeWaveform() {
  const w = document.getElementById('waveform-bubble');
  if (w) w.remove();
  setRingState('idle');
}

// ── HUD: Uptime formatter ──────────────────────────────────────────────────
function fmtUptime(s) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s/60)}min`;
  return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}min`;
}
```

- [ ] **Step 2: Verificar no console do browser**

Abra DevTools → Console. Digite `switchTab('hud')`. O painel HUD deve aparecer. `switchTab('chat')` deve voltar ao chat.

---

## Task 7: JavaScript — Clock + Polling de /status

**Files:**
- Modify: `webapp/index.html` — mesmo bloco `<script>`, adicionar após as funções do Task 6

- [ ] **Step 1: Adicionar clock e polling**

```javascript
// ── HUD: Clock ────────────────────────────────────────────────────────────
function hudClock() {
  const el = document.getElementById('sb-time');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
}
setInterval(hudClock, 1000);
hudClock();

// ── HUD: Poll /status (a cada 10s) ────────────────────────────────────────
async function pollStatus() {
  const token = localStorage.getItem('barretao_token');
  if (!token) return;
  try {
    const r = await fetch('/status', { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const d = await r.json();
    // Status bar
    const cpu = `${d.cpu_percent}%`;
    const ram = `${d.ram_used_gb}/${d.ram_total_gb}GB`;
    const model = d.model || '—';
    document.getElementById('sb-cpu').textContent = cpu;
    document.getElementById('sb-ram').textContent = ram;
    document.getElementById('sb-model').textContent = model;
    // HUD widgets
    const cpuEl = document.getElementById('hw-cpu');
    if (cpuEl) {
      cpuEl.textContent = cpu;
      cpuEl.className = 'wr-val ' + (d.cpu_percent > 80 ? 'warn' : 'ok');
    }
    const ramEl = document.getElementById('hw-ram');
    if (ramEl) ramEl.textContent = ram;
    const modelEl = document.getElementById('hw-model');
    if (modelEl) modelEl.textContent = model;
    const discordEl = document.getElementById('hw-discord');
    if (discordEl) {
      discordEl.textContent = d.discord_enabled ? '● ON' : '● OFF';
      discordEl.className = 'wr-val ' + (d.discord_enabled ? 'ok' : '');
    }
    const uptimeEl = document.getElementById('arc-uptime');
    if (uptimeEl) uptimeEl.textContent = fmtUptime(d.uptime_seconds);
  } catch(e) { /* silencioso */ }
}
pollStatus();
setInterval(pollStatus, 10000);

// ── HUD: Poll /briefing para widgets (a cada 5min) ────────────────────────
async function pollBriefing() {
  const token = localStorage.getItem('barretao_token');
  if (!token) return;
  try {
    const r = await fetch('/briefing', { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const d = await r.json();
    const text = (d.answer || d.text || '').toLowerCase();
    // Extrair temperatura do briefing text
    const tempMatch = text.match(/(\d+)°c/);
    const weatherEl = document.getElementById('sb-weather');
    if (weatherEl && tempMatch) weatherEl.textContent = `${tempMatch[1]}°C`;
    // Clima widget
    const climaEl = document.getElementById('hw-clima');
    if (climaEl && tempMatch) climaEl.textContent = `${tempMatch[1]}°C`;
    // Gmail
    const gmailMatch = text.match(/(\d+)\s*(email|mensagem|não\s*lid)/i);
    const gmailEl = document.getElementById('hw-gmail');
    if (gmailEl) {
      const n = gmailMatch ? parseInt(gmailMatch[1]) : 0;
      gmailEl.textContent = n > 0 ? `${n} novos` : 'Nenhum';
      gmailEl.className = 'wr-val ' + (n > 0 ? 'warn' : 'ok');
    }
  } catch(e) { /* silencioso */ }
}
pollBriefing();
setInterval(pollBriefing, 300000);
```

- [ ] **Step 2: Verificar no browser**

Após login, abra o HUD (aba 🏠). Em até 10 segundos, CPU e RAM devem aparecer nos widgets e na status bar.

---

## Task 8: JavaScript — Shortcuts (HUD + Chat Chips)

**Files:**
- Modify: `webapp/index.html` — mesmo bloco `<script>`

- [ ] **Step 1: Adicionar loadShortcuts e loadMemoryPanel**

```javascript
// ── HUD: Carregar shortcuts de /memory ────────────────────────────────────
const SHORTCUT_ICONS = {
  spotify: '🎵', gmail: '📧', chrome: '🌐', agenda: '📅',
  explorer: '📁', discord: '💬', notepad: '📝', youtube: '▶️',
  default: '⚡',
};
function shortcutIcon(name) {
  const key = name.toLowerCase();
  for (const [k, v] of Object.entries(SHORTCUT_ICONS)) {
    if (key.includes(k)) return v;
  }
  return SHORTCUT_ICONS.default;
}

async function loadShortcuts() {
  const token = localStorage.getItem('barretao_token');
  if (!token) return;
  try {
    const r = await fetch('/memory', { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const d = await r.json();
    const tags = d.tags || [];
    const shortcuts = tags.filter(t => t.type === 'shortcut' || t.category === 'shortcut');

    // HUD grid
    const grid = document.getElementById('hud-shortcuts-grid');
    if (grid) {
      grid.innerHTML = '';
      shortcuts.slice(0, 7).forEach(sc => {
        const name = sc.name || sc.key || '';
        const btn = document.createElement('div');
        btn.className = 'sc-btn';
        btn.innerHTML = `<span class="sc-icon">${shortcutIcon(name)}</span><span class="sc-name">${name}</span>`;
        btn.onclick = () => sendMsg(`/shortcut run ${name}`);
        grid.appendChild(btn);
      });
      // Add button
      const addBtn = document.createElement('div');
      addBtn.className = 'sc-btn sc-add';
      addBtn.innerHTML = `<span class="sc-icon">＋</span><span class="sc-name">Novo</span>`;
      addBtn.onclick = () => { switchTab('chat'); sendMsg('/shortcut add'); };
      grid.appendChild(addBtn);
    }

    // Chat chips
    const chips = document.getElementById('chat-chips');
    if (chips) {
      chips.innerHTML = '';
      shortcuts.slice(0, 6).forEach(sc => {
        const name = sc.name || sc.key || '';
        const chip = document.createElement('div');
        chip.className = 'chat-chip';
        chip.textContent = `${shortcutIcon(name)} ${name}`;
        chip.onclick = () => sendMsg(`/shortcut run ${name}`);
        chips.appendChild(chip);
      });
      // Chip briefing sempre presente
      const briefChip = document.createElement('div');
      briefChip.className = 'chat-chip';
      briefChip.textContent = '📋 Briefing';
      briefChip.onclick = () => sendMsg('briefing do dia');
      chips.prepend(briefChip);
    }
  } catch(e) { /* silencioso */ }
}

// ── HUD: Memory Panel ─────────────────────────────────────────────────────
async function loadMemoryPanel() {
  const token = localStorage.getItem('barretao_token');
  if (!token) return;
  try {
    const r = await fetch('/memory', { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const d = await r.json();
    const tags = d.tags || [];

    function renderList(listId, countId, items, tagLabel) {
      const list = document.getElementById(listId);
      const count = document.getElementById(countId);
      if (!list) return;
      if (count) count.textContent = items.length;
      list.innerHTML = items.length === 0
        ? `<div class="mem-empty">Nenhum registro ainda.</div>`
        : items.map(item => {
            const text = item.value || item.text || item.name || JSON.stringify(item);
            return `<div class="mem-item">
              <span class="mem-tag">[${tagLabel}]</span>
              <span class="mem-text">${text}</span>
              <button class="mem-del" title="Remover">✕</button>
            </div>`;
          }).join('');
    }

    renderList('mem-facts-list', 'mem-facts-count',
      tags.filter(t => t.type === 'fact' || t.category === 'fact'), 'fato');
    renderList('mem-notes-list', 'mem-notes-count',
      tags.filter(t => t.type === 'note' || t.category === 'note'), 'nota');
    renderList('mem-routines-list', 'mem-routines-count',
      tags.filter(t => t.type === 'routine' || t.category === 'routine'), 'rotina');
  } catch(e) { /* silencioso */ }
}

function toggleMemSection(section) {
  const list = document.getElementById(`mem-${section}-list`);
  if (list) list.style.display = list.style.display === 'none' ? '' : 'none';
}
```

- [ ] **Step 2: Chamar `loadShortcuts()` após login**

Procure a função onde o token é salvo após login (provavelmente algo como `localStorage.setItem('barretao_token', ...)`). Imediatamente após essa linha, adicione:

```javascript
loadShortcuts();
```

Se já houver um `checkStatus()` ou `onReady()` que roda após login, adicione `loadShortcuts()` lá também.

- [ ] **Step 3: Verificar no browser**

Após login, o painel HUD deve mostrar atalhos (ou o botão "＋ Novo" se não houver nenhum). A aba Memória deve carregar fatos e notas.

---

## Task 9: JavaScript — Integrar Waveform com o fluxo de resposta existente

**Files:**
- Modify: `webapp/index.html` — bloco `<script>`, modificar função existente de envio de mensagem

- [ ] **Step 1: Localizar onde o "typing indicator" aparece**

Procure `typing-dots` ou `thinking-bar` no JS (deve estar na função `sendMsg` ou similar, próximo de uma chamada `fetch('/command', ...)`). Deve haver algo como:

```javascript
// mostra indicador de digitação
thinkingBar.classList.remove('hidden');
```

- [ ] **Step 2: Substituir o indicador de "pensando" para usar o anel**

Imediatamente antes da chamada `fetch('/command', ...)`, adicione:

```javascript
setRingState('thinking');
```

- [ ] **Step 3: Ao receber resposta, mostrar waveform se AUTO_SPEAK**

Após o `fetch` retornar e o texto da resposta ser adicionado ao chat, adicione:

```javascript
// Se o agente vai falar (TTS ativo), mostrar waveform
if (data.spoken || data.tts) {
  showWaveform();
  // Remover waveform após duração estimada (1 palavra ≈ 300ms + base 1.5s)
  const words = (data.answer || '').split(' ').length;
  const duration = 1500 + words * 280;
  setTimeout(removeWaveform, duration);
} else {
  setRingState('idle');
}
```

Se a API não retornar `spoken` ou `tts`, use duração fixa:

```javascript
showWaveform();
const words = (data.answer || data.text || '').split(' ').length;
setTimeout(removeWaveform, 1500 + words * 280);
```

- [ ] **Step 4: Verificar no browser**

Envie uma mensagem. O anel deve ficar roxo durante o processamento e verde/animado ao responder, voltando ao azul depois.

---

## Task 10: Commit final + verificação

- [ ] **Step 1: Teste completo**

Cheklist de verificação manual:

- [ ] Status bar mostra hora, CPU, RAM e modelo após login
- [ ] Tab Chat abre por padrão
- [ ] Tab HUD mostra anel animado, widgets de briefing e sistema
- [ ] Tab Memória lista fatos/notas/rotinas
- [ ] Anel fica roxo ao enviar mensagem, verde ao responder
- [ ] Chips de atalho aparecem acima do input no Chat
- [ ] Clicar em chip do shortcut envia o comando

- [ ] **Step 2: Commit**

```bash
git add webapp/index.html barretao_hub.py
git commit -m "feat: HUD interface - status bar, tab nav, arc reactor, widgets, waveform"
```

---

## Self-Review

**Spec coverage:**
- ✅ Status bar (hora, clima, CPU, RAM, modelo) → Tasks 2, 7
- ✅ Tab bar (HUD / Chat / Memória / Config) → Tasks 3
- ✅ Arc Reactor com estados por cor → Tasks 2, 6
- ✅ Widget Briefing (Gmail, Agenda, Clima) → Tasks 4, 7
- ✅ Widget Sistema (CPU, RAM, Modelo, Discord) → Tasks 4, 7
- ✅ Grid de Atalhos → Tasks 4, 8
- ✅ Waveform animado no Chat → Tasks 2, 6, 9
- ✅ Chips de atalho no Chat → Tasks 5, 8
- ✅ Painel Memória → Tasks 4, 8
- ✅ Endpoint `/status` → Task 1

**Nomes consistentes:**
- `arc-ring` → usado em Tasks 2, 6, 7, 9 ✅
- `setRingState()` → definido em Task 6, usado em Tasks 6, 9 ✅
- `switchTab()` → definido em Task 6, chamado no HTML do Task 3 ✅
- `loadShortcuts()` → definido em Task 8, chamado após login ✅
- `#hud-shortcuts-grid` → HTML Task 4, JS Task 8 ✅
- `#chat-chips` → HTML Task 5, JS Task 8 ✅
