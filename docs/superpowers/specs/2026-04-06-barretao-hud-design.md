# Barretão HUD — Design Spec
**Data:** 2026-04-06  
**Escopo:** Reformulação da interface web (webapp/index.html) para layout Dashboard + Chat com elementos de HUD estilo Jarvis

---

## Objetivo

Evoluir o webapp atual (chat simples) em um painel de controle estilo Jarvis com navegação por abas, mantendo o estilo visual existente (dark navy, cyan #00cfff, roxo #8800ff, glassmorphism).

---

## Arquitetura

### Navegação por Abas (Tab Bar)

Quatro abas fixas abaixo da status bar:

| Aba | Ícone | Conteúdo |
|-----|-------|----------|
| HUD | 🏠 | Dashboard com widgets |
| Chat | 💬 | Conversa + waveform |
| Memória | 🧠 | Fatos, notas, rotinas |
| Config | ⚙️ | Configurações |

A tab bar substitui o header atual. A status bar permanece acima de todas as abas.

### Status Bar (sempre visível)

Barra horizontal no topo, sempre presente independente da aba ativa:

- `● ONLINE` — dot verde animado com pulse
- Clima da cidade (ex: `SP 28°C ☀️`) — buscado do `/briefing`
- CPU % — via novo endpoint `/status`
- RAM usada — via `/status`
- Modelo LLM ativo (ex: `llama3.1:8b`) — via `/status`
- Hora atual — atualizada via `setInterval` JS a cada segundo
- Linha de scan no bottom com gradient cyan → transparent

---

## Aba 🏠 HUD

### Arc Reactor Header

Componente de destaque no topo da aba HUD:

- **Anel animado** (52px): bordas cyan, rotação do anel interno pontilhado, pulse de glow
- **Estados do anel por cor:**
  - Idle → cyan `#00cfff`
  - Pensando → roxo `#8800ff` + spin acelerado
  - Falando → verde `#00ff99` + pulse rápido
  - Erro → vermelho `#ff2d55`
- **Texto lateral:** nome "BARRETÃO", status atual, uptime da sessão

### Widget Grid (2 colunas)

**Widget Briefing** (esquerda):
- Gmail: N não lidos (vermelho se > 0)
- Agenda: "Livre hoje" ou próximo compromisso
- Tarefas: N pendentes
- Clima: temperatura + ícone
- Dados via `GET /briefing` (já existe)

**Widget Sistema** (direita):
- CPU %
- RAM usada / total
- Modelo LLM ativo
- Discord: ON/OFF
- Dados via novo `GET /status`

### Grid de Atalhos (4 colunas)

- Botões configuráveis com ícone emoji + nome curto
- Clicar executa o shortcut correspondente via `POST /command`
- Último botão é sempre "＋ Novo" → abre modal para adicionar
- Atalhos lidos via `GET /memory` (já retorna shortcuts)
- Máximo 7 atalhos fixos + 1 botão de adicionar

---

## Aba 💬 Chat

### Mudanças em relação ao atual

1. **Waveform animado**: quando o Barretão está respondendo (TTS ativo), o balão "digitando..." é substituído por 7 barras animadas em cyan com alturas variadas e `animation-delay` escalonado.

2. **Chips de atalho** acima do input: faixa horizontal com scroll, mostrando os shortcuts do usuário como chips clicáveis. Clicar envia o comando diretamente.

3. **Input sem mudança estrutural** — mantém microfone, campo de texto, botão enviar.

4. **Estado do anel** sincronizado: quando chat está ativo e Barretão está pensando, o anel na aba HUD muda para roxo (mesmo sem estar na aba).

---

## Aba 🧠 Memória

Lista paginada com três seções colapsáveis:

- **Fatos aprendidos** (`learned_facts` da DB)
- **Notas salvas** (`notes` da DB)
- **Rotinas semanais** (`weekly_routines` da DB)

Cada item tem botão de deletar (ícone lixeira). Dados via `GET /memory` (já existe).

---

## Backend: Novo Endpoint `/status`

Adicionar em `barretao_hub.py`:

```
GET /status
Authorization: Bearer <token>

Response:
{
  "cpu_percent": 8.2,
  "ram_used_gb": 4.1,
  "ram_total_gb": 16.0,
  "model": "llama3.1:8b",
  "provider": "ollama",
  "discord_enabled": true,
  "uptime_seconds": 15780
}
```

Usa `psutil` (já deve estar disponível) para CPU e RAM. Uptime calculado desde `app.state.start_time`.

---

## Atualização de Dados (Polling)

| Dado | Frequência | Endpoint |
|------|-----------|----------|
| Hora | 1s | JS local |
| CPU/RAM | 10s | `/status` |
| Briefing (clima, gmail, agenda) | 5min | `/briefing` |
| Estado do anel (idle/thinking) | Evento | JS interno |

Sem WebSocket — polling simples com `setInterval` é suficiente.

---

## Estado do Anel — Lógica JS

```
idle      → cyan, pulse lento (3s)
thinking  → roxo, spin 2x mais rápido, pulse médio
speaking  → verde, pulse rápido (0.8s)
error     → vermelho, sem pulse
```

Disparado por:
- `thinking`: imediatamente ao enviar mensagem
- `speaking`: quando TTS começa (evento de áudio ou flag no response)
- `idle`: quando resposta chega e TTS termina

---

## Escopo Fora deste Spec

Os itens abaixo são fases futuras, **não incluídos** nesta implementação:

- Wake word contínuo (Fase 2 — Voz)
- Integrações de casa inteligente (Fase 3)
- Personalidade e memória avançada (Fase 4)
- Aba de configurações completa (pode ser stub vazio agora)

---

## Arquivos Modificados

| Arquivo | Mudança |
|---------|---------|
| `webapp/index.html` | Refatoração completa da UI (tab bar, HUD, waveform, chips) |
| `barretao_hub.py` | Adicionar endpoint `GET /status` |

Nenhum arquivo novo criado. Nenhuma mudança em banco de dados.
