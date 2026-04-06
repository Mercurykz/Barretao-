# Claude Agent Loop — Design Spec
**Data:** 2026-04-06
**Escopo:** Integração do Claude API como provedor de agente autônomo com tool use, roteamento automático e loop contínuo de ferramentas

---

## Objetivo

Adicionar o Claude API (Anthropic SDK) como um segundo modo de execução no Barretão. Quando uma mensagem detecta intenção de ação, ela é roteada para um `ClaudeAgent` que executa um loop autônomo de tool use — pensa, usa ferramentas, pensa novamente, entrega resposta final. O provedor atual (Ollama/OpenAI/etc) permanece intacto para conversas simples.

---

## Arquitetura

### Novos arquivos

| Arquivo | Responsabilidade |
|---|---|
| `barretao_claude_agent.py` | `ClaudeAgent` — loop, tool registry, system prompt builder |

### Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `barretao_hub.py` | Adicionar `AutoRouter` no endpoint `POST /command` |
| `.env.example` | Adicionar variáveis `CLAUDE_API_KEY`, `CLAUDE_AGENT_MODEL`, etc. |

---

## Componentes

### 1. AutoRouter (`barretao_hub.py`)

Inserido no início do handler `POST /command`, antes da chamada ao `agent`.

**Lógica:**
```python
def should_use_claude_agent(message: str) -> bool:
    if not CLAUDE_API_KEY:
        return False
    msg = message.lower()
    ACTION_VERBS = ["abre", "abrir", "executa", "executar", "busca", "buscar",
                    "manda", "mandar", "envia", "enviar", "liga", "ligar",
                    "desliga", "desligar", "verifica", "verificar", "mostra",
                    "mostrar", "toca", "tocar", "fecha", "fechar", "lista", "listar"]
    TOOL_KEYWORDS = ["email", "spotify", "chrome", "arquivo", "pasta", "script",
                     "luz", "clima", "tempo", "agenda", "calendário", "briefing",
                     "atalho", "shortcut", "home", "discord", "gmail"]
    has_verb = any(v in msg for v in ACTION_VERBS)
    has_keyword = any(k in msg for k in TOOL_KEYWORDS)
    return has_verb or has_keyword
```

**Fluxo no `/command`:**
```
mensagem chega
  → should_use_claude_agent(msg)?
      → sim: ClaudeAgent(msg, history) → resposta
      → não: agent.chat(msg) → resposta (comportamento atual)
```

**Graceful degradation:** se `CLAUDE_API_KEY` ausente ou vazio, `should_use_claude_agent` sempre retorna `False`. Sem quebra.

---

### 2. ClaudeAgent (`barretao_claude_agent.py`)

#### Classe e inicialização

```python
class ClaudeAgent:
    def __init__(self, agent: PersonalAIAgent, config: dict):
        self.agent = agent          # referência ao agente existente
        self.client = anthropic.Anthropic(api_key=config["api_key"])
        self.model = config.get("model", "claude-sonnet-4-6")
        self.max_tokens = config.get("max_tokens", 4096)
        self.max_iterations = config.get("max_iterations", 10)
```

#### System Prompt (injetado a cada chamada)

```
Você é o Barretão, assistente pessoal autônomo.
Data/hora: {datetime}
Cidade: {city}, {country}

MEMÓRIA RECENTE:
{ultimos_10_fatos}

PERFIL DO USUÁRIO:
{user_profile}

ATALHOS DISPONÍVEIS:
{lista_shortcuts}

Você tem ferramentas disponíveis. Use quantas precisar em sequência para completar a tarefa.
Responda sempre em português, de forma direta e sem rodapés.
```

#### Loop de execução

```python
def run(self, message: str, history: list[dict]) -> str:
    messages = history + [{"role": "user", "content": message}]
    
    for _ in range(self.max_iterations):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self._build_system_prompt(),
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        
        if response.stop_reason == "end_turn":
            return self._extract_text(response)
        
        if response.stop_reason == "tool_use":
            # Executar todas as tool_use blocks
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            # Adicionar resposta do assistente + resultados ao histórico
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue
        
        break  # stop_reason inesperado
    
    return self._extract_text(response)
```

---

### 3. Tool Registry — 12 ferramentas

Cada ferramenta tem: `name`, `description` (em português), `input_schema`, e um handler em `_execute_tool`.

| Ferramenta | Input | Handler |
|---|---|---|
| `execute_command` | `{"command": str}` | `agent.handle_command(command)` |
| `run_shortcut` | `{"name": str}` | `agent.run_shortcut(name)` |
| `search_web` | `{"query": str}` | `agent.search_web(query)` |
| `get_weather` | `{}` | `agent.get_weather_summary()` |
| `read_emails` | `{"limit": int = 5}` | `agent.fetch_emails_imap(limit=limit)` |
| `get_briefing` | `{}` | `agent.get_briefing_text()` |
| `get_calendar` | `{"days": int = 7}` | `agent.get_calendar_events(days_ahead=days)` |
| `search_memory` | `{"query": str}` | `agent.search_knowledge(query)` |
| `save_note` | `{"text": str}` | `agent.save_note(text)` |
| `list_shortcuts` | `{}` | `agent.get_shortcuts()` |
| `control_home` | `{"domain": str, "service": str, "entity_id": str}` | `agent.run_hass_command(domain, service, entity_id)` |
| `list_home_entities` | `{"domain": str = ""}` | `agent.list_hass_entities(domain_filter=domain)` |

#### Tratamento de erros em ferramentas

Cada `_execute_tool` é envolto em try/except. Em caso de erro, retorna `{"error": str(e)}` como string — Claude recebe o erro e pode tentar outra abordagem ou informar o usuário.

---

## Configuração

### Variáveis de ambiente (`.env`)

```env
# Claude Agent Loop
CLAUDE_API_KEY=sk-ant-...
CLAUDE_AGENT_MODEL=claude-sonnet-4-6
CLAUDE_AGENT_MAX_TOKENS=4096
CLAUDE_AGENT_MAX_ITERATIONS=10
```

### Carregamento em `barretao_hub.py`

```python
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_AGENT_MODEL = os.getenv("CLAUDE_AGENT_MODEL", "claude-sonnet-4-6")
CLAUDE_AGENT_MAX_TOKENS = int(os.getenv("CLAUDE_AGENT_MAX_TOKENS", "4096"))
CLAUDE_AGENT_MAX_ITERATIONS = int(os.getenv("CLAUDE_AGENT_MAX_ITERATIONS", "10"))

# Inicializar ClaudeAgent apenas se chave configurada
_claude_agent = None
if CLAUDE_API_KEY:
    from barretao_claude_agent import ClaudeAgent
    _claude_agent = ClaudeAgent(agent, {
        "api_key": CLAUDE_API_KEY,
        "model": CLAUDE_AGENT_MODEL,
        "max_tokens": CLAUDE_AGENT_MAX_TOKENS,
        "max_iterations": CLAUDE_AGENT_MAX_ITERATIONS,
    })
```

---

## Resposta no `/command`

O endpoint atual retorna `{"answer": str, ...}`. O `ClaudeAgent.run()` retorna uma string — compatível sem mudança de contrato.

---

## Fora do Escopo

- Interface de visualização das tool calls no frontend (fase futura)
- Wake word / voz como trigger (fase futura — Voz & Presença)
- Modo agente contínuo sem input do usuário (fase futura — Proativo)
- Streaming de respostas (fase futura)

---

## Dependências

```bash
pip install anthropic
```

Já disponível no PyPI. Adicionar ao `requirements.txt`.
