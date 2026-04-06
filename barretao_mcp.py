"""
Barretão MCP Server
====================
Expõe as capacidades do Barretão como ferramentas MCP (Model Context Protocol),
permitindo que Claude, Copilot e outros agentes compatíveis comandem o Barretão
diretamente.

Uso:
  python barretao_mcp.py

Configuração (.env):
  HUB_API_URL=http://localhost:8787
  HUB_API_TOKEN=seu_token_aqui
"""

import os
import sys
import json
import requests
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("Erro: pacote 'mcp' não instalado. Rode: pip install mcp", file=sys.stderr)
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ─────────────────────────────────────────────────────────────────
HUB_URL   = os.getenv("HUB_API_URL", "http://localhost:8787").rstrip("/")
API_TOKEN = os.getenv("HUB_API_TOKEN", "").strip()
TIMEOUT   = int(os.getenv("HUB_TIMEOUT", "60"))

server = Server("barretao")


# ── Helpers ─────────────────────────────────────────────────────────────────
def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    return h


def _post_command(text: str) -> str:
    """Send a text command to Barretão hub and return the answer."""
    try:
        r = requests.post(
            f"{HUB_URL}/command",
            json={"text": text, "source": "mcp"},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("answer", "")
    except requests.exceptions.ConnectionError:
        return f"❌ Barretão hub não está acessível em {HUB_URL}. Inicie com: python barretao_hub.py"
    except Exception as e:
        return f"❌ Erro ao contactar Barretão: {e}"


def _text(content: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=content)]


# ── Tool list ────────────────────────────────────────────────────────────────
@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="barretao_ask",
            description=(
                "Envia uma pergunta ou comando ao Barretão e retorna a resposta. "
                "Use para conversas, perguntas gerais, consultas de clima, câmbio, "
                "notas, lembretes e qualquer interação com o assistente pessoal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Pergunta ou comando para o Barretão"}
                },
                "required": ["text"],
            },
        ),
        types.Tool(
            name="barretao_generate_image",
            description=(
                "Gera uma imagem a partir de uma descrição textual usando Nano Banana "
                "(Google Gemini), DALL-E 3 ou Stable Diffusion. "
                "Use quando o usuário pedir para criar, desenhar ou gerar uma imagem."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Descrição detalhada da imagem a gerar"},
                    "size": {
                        "type": "string",
                        "description": "Tamanho da imagem (ex: 1024x1024)",
                        "default": "1024x1024",
                    },
                },
                "required": ["prompt"],
            },
        ),
        types.Tool(
            name="barretao_generate_code",
            description=(
                "Gera código em qualquer linguagem a partir de uma descrição em linguagem natural. "
                "Suporta Python, JavaScript, TypeScript, Java, Go, Rust, SQL, C#, etc. "
                "Use quando o usuário pedir para programar, criar código ou implementar algo."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "O que o código deve fazer"},
                    "language": {
                        "type": "string",
                        "description": "Linguagem de programação (python, javascript, java, etc.)",
                        "default": "python",
                    },
                    "framework": {
                        "type": "string",
                        "description": "Framework opcional (react, fastapi, django, etc.)",
                    },
                },
                "required": ["description"],
            },
        ),
        types.Tool(
            name="barretao_analyze_code",
            description=(
                "Analisa um trecho de código e fornece feedback sobre qualidade, "
                "segurança, performance e boas práticas. "
                "Use quando quiser revisar ou auditar código existente."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "O código a ser analisado"},
                    "language": {
                        "type": "string",
                        "description": "Linguagem do código (opcional, detectado automaticamente)",
                    },
                },
                "required": ["code"],
            },
        ),
        types.Tool(
            name="barretao_create_app",
            description=(
                "Gera um template completo de aplicação para um framework específico. "
                "Suporta: react, vue, flask, django, fastapi, nextjs. "
                "Retorna estrutura de arquivos, dependências e instruções de setup."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "framework": {
                        "type": "string",
                        "description": "Framework: react, vue, flask, django, fastapi, nextjs",
                    },
                    "description": {
                        "type": "string",
                        "description": "O que o app deve fazer",
                    },
                },
                "required": ["framework", "description"],
            },
        ),
        types.Tool(
            name="barretao_pc_control",
            description=(
                "Controla o PC via Barretão. Ações disponíveis: "
                "shutdown (desligar), restart (reiniciar), lock (bloquear), "
                "sleep (suspender), hibernate (hibernar), cancel (cancelar desligamento), "
                "wake <MAC> (ligar outro PC via Wake-on-LAN)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Ação: shutdown, restart, lock, sleep, hibernate, cancel, wake",
                    },
                    "delay_seconds": {
                        "type": "integer",
                        "description": "Segundos de espera antes de desligar/reiniciar (padrão: 60)",
                        "default": 60,
                    },
                    "mac_address": {
                        "type": "string",
                        "description": "Endereço MAC para Wake-on-LAN (só necessário em action=wake)",
                    },
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="barretao_search_web",
            description=(
                "Faz uma busca na web via Barretão e retorna os resultados. "
                "Use para pesquisar informações atuais que o LLM não tem."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termos de busca"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="barretao_briefing",
            description=(
                "Obtém o briefing diário do Barretão: clima, agenda, rotina e notícias. "
                "Use no início do dia ou quando o usuário pedir um resumo do dia."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="barretao_save_note",
            description="Salva uma nota no banco de dados do Barretão.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título da nota"},
                    "content": {"type": "string", "description": "Conteúdo da nota"},
                },
                "required": ["title", "content"],
            },
        ),
        types.Tool(
            name="barretao_teach",
            description=(
                "Ensina um fato ou informação ao Barretão para que ele memorize. "
                "Ex: nome do usuário, cidade, preferências, etc."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "Informação a memorizar"},
                },
                "required": ["fact"],
            },
        ),
        types.Tool(
            name="barretao_status",
            description="Verifica se o Barretão está online e retorna o status do hub.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="barretao_hass",
            description=(
                "Controla dispositivos do Home Assistant via Barretão. "
                "Pode listar entidades, ligar/desligar luzes, interruptores, "
                "climatização, etc. Requer HASS_URL e HASS_TOKEN no .env."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Ação: list, turn_on, turn_off, toggle, state",
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "ID da entidade (ex: light.sala, switch.ar)",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Domínio do HA (light, switch, climate, etc.) — usado com list",
                    },
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="barretao_calendar",
            description=(
                "Retorna os próximos eventos do Google Calendar via Barretão. "
                "Não requer OAuth — usa o URL secreto iCal configurado em GOOGLE_CALENDAR_ICAL_URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Quantos dias à frente buscar (padrão: 7)",
                        "default": 7,
                    }
                },
                "required": [],
            },
        ),
    ]


# ── Tool handlers ─────────────────────────────────────────────────────────────
@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:

    # ── barretao_ask ───────────────────────────────────────────────────────
    if name == "barretao_ask":
        text = arguments.get("text", "").strip()
        if not text:
            return _text("Erro: 'text' é obrigatório.")
        return _text(_post_command(text))

    # ── barretao_generate_image ────────────────────────────────────────────
    if name == "barretao_generate_image":
        prompt = arguments.get("prompt", "").strip()
        size   = arguments.get("size", "1024x1024")
        if not prompt:
            return _text("Erro: 'prompt' é obrigatório.")
        cmd = f"gerar imagem {prompt}"
        result = _post_command(cmd)
        return _text(result)

    # ── barretao_generate_code ─────────────────────────────────────────────
    if name == "barretao_generate_code":
        description = arguments.get("description", "").strip()
        language    = arguments.get("language", "python").strip()
        framework   = arguments.get("framework", "").strip()
        if not description:
            return _text("Erro: 'description' é obrigatório.")
        cmd = f"gerar código {language} {description}"
        if framework:
            cmd += f" usando {framework}"
        return _text(_post_command(cmd))

    # ── barretao_analyze_code ──────────────────────────────────────────────
    if name == "barretao_analyze_code":
        code     = arguments.get("code", "").strip()
        language = arguments.get("language", "").strip()
        if not code:
            return _text("Erro: 'code' é obrigatório.")
        prefix = f"analisar código {language} " if language else "analisar código "
        return _text(_post_command(prefix + code))

    # ── barretao_create_app ────────────────────────────────────────────────
    if name == "barretao_create_app":
        framework   = arguments.get("framework", "").strip().lower()
        description = arguments.get("description", "").strip()
        if not framework or not description:
            return _text("Erro: 'framework' e 'description' são obrigatórios.")
        return _text(_post_command(f"criar app {framework} {description}"))

    # ── barretao_pc_control ────────────────────────────────────────────────
    if name == "barretao_pc_control":
        action  = arguments.get("action", "").strip().lower()
        delay   = arguments.get("delay_seconds", 60)
        mac     = arguments.get("mac_address", "").strip()

        action_map = {
            "shutdown": f"desligar pc {delay}",
            "restart":  f"reiniciar pc {delay}",
            "lock":     "bloquear pc",
            "sleep":    "suspender pc",
            "hibernate":"hibernar pc",
            "cancel":   "cancelar desligamento",
            "wake":     f"/wol {mac}" if mac else "/wol",
        }

        cmd = action_map.get(action)
        if not cmd:
            return _text(f"Ação inválida: '{action}'. Use: shutdown, restart, lock, sleep, hibernate, cancel, wake")
        return _text(_post_command(cmd))

    # ── barretao_search_web ────────────────────────────────────────────────
    if name == "barretao_search_web":
        query = arguments.get("query", "").strip()
        if not query:
            return _text("Erro: 'query' é obrigatório.")
        return _text(_post_command(f"pesquisar {query}"))

    # ── barretao_briefing ──────────────────────────────────────────────────
    if name == "barretao_briefing":
        try:
            r = requests.get(f"{HUB_URL}/briefing", headers=_headers(), timeout=TIMEOUT)
            r.raise_for_status()
            return _text(r.json().get("answer", ""))
        except Exception as e:
            return _text(f"❌ Erro ao obter briefing: {e}")

    # ── barretao_save_note ─────────────────────────────────────────────────
    if name == "barretao_save_note":
        title   = arguments.get("title", "").strip()
        content = arguments.get("content", "").strip()
        if not title or not content:
            return _text("Erro: 'title' e 'content' são obrigatórios.")
        return _text(_post_command(f"salvar nota {title}: {content}"))

    # ── barretao_teach ─────────────────────────────────────────────────────
    if name == "barretao_teach":
        fact = arguments.get("fact", "").strip()
        if not fact:
            return _text("Erro: 'fact' é obrigatório.")
        return _text(_post_command(f"lembrar que {fact}"))

    # ── barretao_status ────────────────────────────────────────────────────
    if name == "barretao_status":
        try:
            r = requests.get(f"{HUB_URL}/health", timeout=10)
            r.raise_for_status()
            data = r.json()
            return _text(
                f"✅ Barretão online\n"
                f"  Serviço: {data.get('service', 'barretao-hub')}\n"
                f"  Versão:  {data.get('version', '?')}\n"
                f"  URL:     {HUB_URL}"
            )
        except Exception:
            return _text(f"❌ Barretão offline ou inacessível em {HUB_URL}")
    # ── barretao_hass ───────────────────────────────────────────────────────────
    if name == "barretao_hass":
        action    = arguments.get("action", "").strip().lower()
        entity_id = arguments.get("entity_id", "").strip()
        domain    = arguments.get("domain", "").strip()
        if action == "list":
            try:
                params = f"?domain={domain}" if domain else ""
                r = requests.get(f"{HUB_URL}/hass/entities{params}", headers=_headers(), timeout=TIMEOUT)
                r.raise_for_status()
                data = r.json()
                entities = data.get("entities", [])
                if not entities:
                    return _text("🏠 Nenhuma entidade encontrada.")
                lines = [f"🏠 {len(entities)} entidade(s):"]
                for e in entities[:30]:
                    lines.append(f"  • {e['name']}: {e['state']} ({e['entity_id']})")
                return _text("\n".join(lines))
            except Exception as e:
                return _text(f"❌ Erro ao listar entidades HA: {e}")
        if action in ("turn_on", "turn_off", "toggle"):
            if not entity_id:
                return _text("Erro: 'entity_id' é obrigatório para controlar entidades.")
            eid_domain = entity_id.split(".")[0]
            try:
                r = requests.post(
                    f"{HUB_URL}/hass/{eid_domain}/{action}",
                    params={"entity_id": entity_id},
                    headers=_headers(),
                    timeout=TIMEOUT,
                )
                data = r.json()
                return _text(data.get("result", str(data)))
            except Exception as e:
                return _text(f"❌ Erro ao controlar HA: {e}")
        if action == "state":
            if not entity_id:
                return _text("Erro: 'entity_id' é obrigatório para verificar estado.")
            return _text(_post_command(f"/ha {entity_id}"))
        return _text(f"Ação desconhecida: '{action}'. Use: list, turn_on, turn_off, toggle, state")

    # ── barretao_calendar ─────────────────────────────────────────────────────────
    if name == "barretao_calendar":
        days = arguments.get("days", 7)
        try:
            r = requests.get(f"{HUB_URL}/calendar?days={days}", headers=_headers(), timeout=TIMEOUT)
            r.raise_for_status()
            return _text(r.json().get("text", "Sem dados"))
        except Exception as e:
            return _text(f"❌ Erro ao obter calendário: {e}")
    return _text(f"Ferramenta desconhecida: {name}")


# ── Entry point ───────────────────────────────────────────────────────────────
async def main() -> None:
    async with stdio_server() as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
