# Agente IA para uso pessoal (local)

Projeto em Python para usar no seu PC com:
- LLM local via Ollama
- conversa contínua
- memória curta em SQLite (anotações)
- voz (fala + escuta)
- automação básica do Windows
- integração opcional com Discord

## 1) Pré-requisitos
- Python 3.10+
- Ollama instalado e rodando

### Voz (microfone) no Windows
- Recomendado: Python 3.11
- Em Python 3.14, `PyAudio` e `pocketsphinx` podem falhar na instalação
- Sem microfone, o agente continua funcionando em modo texto (`/wake` com fallback)

## 2) Preparar o modelo local
1. Instale o Ollama
2. Baixe um modelo (exemplo):

```bash
ollama pull llama3.1:8b
```

## 3) Instalação do projeto
1. Crie e ative um ambiente virtual
2. Instale dependências:

```bash
pip install -r requirements.txt
```

## 4) Configuração
1. Copie `.env.example` para `.env`
2. Escolha o provider de LLM e modelo
	- Local (padrão): `LLM_PROVIDER=ollama` + `OLLAMA_BASE_URL` + `OLLAMA_MODEL`
	- OpenAI compatível: `LLM_PROVIDER=openai` + `LLM_BASE_URL` + `LLM_MODEL` + `LLM_API_KEY`
	- Gemini: `LLM_PROVIDER=gemini` + `LLM_MODEL` + `GEMINI_API_KEY`
	- Multi-modelo opcional: `MULTI_MODEL_ENABLED=true`, `OLLAMA_MODEL_SECONDARY=<modelo>`, `MULTI_MODEL_MODE=primary_fallback|smart_router|round_robin`
	- Usar todos os modelos locais disponíveis: `AUTO_USE_ALL_MODELS=true`
	- Wake-on-LAN opcional: `WOL_DEFAULT_MAC`, `WOL_BROADCAST`, `WOL_PORT`
3. Ajuste voz em `AUTO_SPEAK`, `VOICE_LANGUAGE`, `STT_ENGINE`
	- Voz mais humana: `TTS_RATE`, `TTS_VOLUME`, `TTS_VOICE_HINT`, `TTS_HUMANIZED`
4. Aprendizado de rotina: `ROUTINE_LEARNING=true`
5. Execução proativa: `PROACTIVE_MODE=true` e `PROACTIVE_MIN_COUNT=2`
6. Nome de chamada por voz: `WAKE_NAME=barretão`
7. Discord opcional: `DISCORD_ENABLED`, `DISCORD_BOT_TOKEN`, `DISCORD_TRIGGER`
8. Briefing diário: `USER_CITY` e `USER_COUNTRY`
9. Cidade automática por IP (opcional): `AUTO_CITY_BY_IP=true`
10. Forçar abertura no Chrome: `FORCE_CHROME=true`
11. Persona de resposta: `PERSONA_MODE` e `PERSONA_HUMOR`

Exemplo para estilo parecido com Grok (mais direto/irreverente):

```text
PERSONA_MODE=grok
PERSONA_HUMOR=medio
```

Exemplo Wake-on-LAN no `.env`:

```text
WOL_DEFAULT_MAC=AA:BB:CC:DD:EE:FF
WOL_BROADCAST=192.168.1.255
WOL_PORT=9
```

## 5) Execução
```bash
python personal_ai_agent.py
```

## Deploy no Railway (rápido)
Arquivos de deploy já incluídos:
- [Procfile](Procfile)
- [railway.json](railway.json)

Passo a passo:
1. Suba o projeto no GitHub.
2. No Railway: **New Project** → **Deploy from GitHub Repo**.
3. Em **Variables**, configure no mínimo:

```text
HUB_API_TOKEN=seu_token_forte
PUBLIC_TUNNEL=false
AGENT_DB_PATH=/data/agent_memory.db
```

4. Se você usar LLM remoto, configure também (escolha um):

```text
# OpenAI/OpenRouter/Groq (compatível /v1/chat/completions)
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=seu_token

# ou Gemini
LLM_PROVIDER=gemini
LLM_MODEL=gemini-1.5-flash
GEMINI_API_KEY=seu_token

# ou endpoint Ollama remoto
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://SEU_ENDPOINT_OLLAMA
OLLAMA_MODEL=llama3.1:8b
```

5. Deploy automático: o Railway vai iniciar com `uvicorn barretao_hub:app`.
6. Abra a URL pública do Railway com `/app/` no final.
7. Em **Volumes** do Railway, crie e monte um volume em `/data` (para não perder `agent_memory.db` em redeploy).

Observação:
- Railway não é ideal para rodar Ollama local no plano grátis. O recomendado é usar endpoint de LLM externo.

## Hub para Alexa, carro, PC e celular
Agora você também pode rodar um hub HTTP para integrar vários dispositivos.

Subir o hub:

```bash
python barretao_hub.py
```

Variáveis no `.env`:

```text
HUB_API_TOKEN=troque_este_token
HUB_HOST=0.0.0.0
HUB_PORT=8787
PUBLIC_TUNNEL=false
```

Dentro e fora de casa (internet):
- Defina `PUBLIC_TUNNEL=true` e rode `python barretao_hub.py`
- Se `cloudflared` estiver instalado, o hub mostrará uma URL pública `https://...trycloudflare.com/app/`
- Abra essa URL no celular e adicione à tela inicial (PWA)

Endpoints:
- `GET /health`
- `POST /command` com JSON `{ "text": "abrir youtube" }`
- `GET /briefing`

Header de segurança:

```text
Authorization: Bearer SEU_TOKEN
```

Exemplo (celular/PC/carro com app HTTP):

```bash
curl -X POST http://SEU_IP:8787/command \
	-H "Authorization: Bearer SEU_TOKEN" \
	-H "Content-Type: application/json" \
	-d '{"text":"bom dia"}'
```

Para Alexa:
- crie uma skill custom
- no backend da skill, envie o texto para `POST /command`
- devolva a resposta do `answer` como fala da Alexa

## Comandos
- `/help` mostra ajuda
- `/save <texto>` salva anotação
- `/event add YYYY-MM-DD <título>` salva evento pessoal
- `/event list` lista eventos
- `/event today` mostra eventos de hoje
- `/event del <id>` remove evento
- `/week add <dia> <tarefa>` salva rotina semanal
- `/week list` lista rotinas semanais
- `/week day <dia>` mostra rotina de um dia
- `/week del <id>` remove rotina semanal
- `/notes` lista anotações
- `/clear` limpa histórico da conversa
- `/open <alvo>` abre site, arquivo, pasta ou app
- `/search <pergunta>` pesquisa na web e responde
- `/alias add <nome> <url|alvo>` salva alias manual
- `/alias fix <nome> <url|alvo>` corrige alias/site aprendido
- `/alias list` lista aliases
- `/alias del <nome>` remove alias
- `/ps <comando>` executa comando PowerShell
- `/pc <acao>` controla o PC (`shutdown`, `restart`, `lock`, `sleep`, `hibernate`, `logout`, `cancel`, `wake`)
- `/wol <MAC> [broadcast] [porta]` envia Wake-on-LAN para ligar/acordar PC na rede
- `/wol set <MAC> [broadcast] [porta]` salva configuração padrão de Wake-on-LAN
- `/wol status` mostra a configuração atual de Wake-on-LAN
- `/listen` escuta sua voz e envia para o agente
- `/wake` escuta contínua e aceita comando direto
- `/voice on|off` liga/desliga fala automática
- `/model status` mostra status dos modelos (primário/secundário)
- `/model refresh` recarrega modelos disponíveis no Ollama
- `/say <texto>` faz o agente falar agora
- `/shortcut add <nome> <acoes>` salva/atualiza atalho
- `/shortcut run <nome>` executa atalho
- `/shortcut list` lista atalhos
- `/shortcut del <nome>` remove atalho
- `/routine status` mostra status do aprendizado
- `/routine patterns` mostra padrões mais frequentes
- `/routine suggest` sugere ações para este horário
- `/routine auto <nome>` cria atalho com padrões atuais
- `/proactive status` mostra status do modo proativo
- `/proactive on|off` liga/desliga modo proativo
- `/proactive check` mostra sugestão pro horário atual
- `/discord status` mostra status da integração Discord
- `/exit` sai

## Discord
O agente pode ficar online no Discord e responder somente quando alguém usar o comando configurado.

Configuração no `.env`:

```text
DISCORD_ENABLED=true
DISCORD_BOT_TOKEN=seu_token_aqui
DISCORD_TRIGGER=!barretao
DISCORD_CHANNEL_IDS=123456789012345678,987654321098765432
```

Observações:
- `DISCORD_TRIGGER` é o comando que ativa o bot no chat
- `DISCORD_CHANNEL_IDS` é opcional; vazio = responde em qualquer canal acessível ao bot
- o bot usa o mesmo Ollama e os mesmos comandos locais do agente
- no Discord Developer Portal, ative `Message Content Intent`

Exemplos no Discord:

```text
!barretao abrir youtube
!barretao abrir discord
!barretao executar atalho manha
!barretao me ajuda a organizar meu dia
!barretao pesquisar quem foi Ayrton Senna
```

## Pesquisa na web
Você pode pedir para o agente pesquisar e te responder.

Exemplos:

```text
/search quem foi Ayrton Senna
pesquisar cotação do dólar hoje
buscar capital da Austrália
```

## Corrigir site errado
Se ele aprender um link errado ao usar `abrir <site>`, corrija assim:

```text
/alias fix ifood https://www.ifood.com.br
```

Ou por voz/texto:

```text
corrigir site ifood para https://www.ifood.com.br
```

## Forçar abrir no Chrome
No `.env`, configure:

```text
FORCE_CHROME=true
CHROME_PATH=
```

Se `CHROME_PATH` ficar vazio, o agente tenta localizar o Chrome automaticamente nos caminhos padrão do Windows.

## Bom dia / briefing diário
Quando você disser `bom dia`, o agente pode responder com:
- data de hoje
- previsão do tempo
- feriado nacional do dia
- seus eventos pessoais do dia
- rotina do dia da semana

Se `USER_CITY` estiver vazio, ele tenta detectar a cidade pelo IP público (quando `AUTO_CITY_BY_IP=true`).

Exemplos:

```text
bom dia
/event add 2026-04-10 Consulta médica às 14h
/event add 2026-04-10 Pagar boleto
/event today
```

## Rotina por dia da semana
Você pode cadastrar tarefas fixas por dia.

Exemplos:

```text
/week add segunda academia 19h
/week add terça estudar inglês 20h
/week day segunda
/week list
```

Por voz/texto natural:

```text
adicionar na minha rotina segunda academia 19h
minha rotina terça
```

## Voz mais humanizada
Você pode ajustar a voz no `.env`:

```text
TTS_RATE=165
TTS_VOLUME=1.0
TTS_VOICE_HINT=pt-br
TTS_HUMANIZED=true
```

Dicas:
- `TTS_RATE` entre `150` e `175` costuma soar mais natural
- `TTS_VOICE_HINT` pode ser `pt-br`, `portuguese`, `maria`, etc.

Providers suportados em `TTS_PROVIDER`:
- `edge` (padrão, vozes neurais Microsoft via `edge-tts`)
- `pyttsx3` (voz local do sistema)
- `elevenlabs`
- `openai`
- `azure`

Exemplos:

```text
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=sua_chave
ELEVENLABS_VOICE_ID=EXAVITQu4vr4xnSDxMaL
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
```

```text
TTS_PROVIDER=openai
OPENAI_TTS_API_KEY=sua_chave
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=coral
```

```text
TTS_PROVIDER=azure
AZURE_SPEECH_KEY=sua_chave
AZURE_SPEECH_REGION=brazilsouth
AZURE_SPEECH_VOICE=pt-BR-FranciscaNeural
```

Comandos:
- `/voice provider edge|pyttsx3|elevenlabs|openai|azure`
- `/voice set feminina|masculina|profissional|natural|<voice-id>`
- `/voice status`

## Aprendizado da sua rotina
O agente registra suas ações de automação (`/open`, `/ps` e execução de atalhos) e aprende padrões de uso por dia e horário.

Fluxo recomendado:
1. Use normalmente por alguns dias.
2. Rode `/routine suggest` para ver o que ele aprendeu para o horário atual.
3. Se fizer sentido, rode `/routine auto <nome>` para virar um atalho.

Exemplo:

```text
/routine suggest
/routine auto inicio_trabalho
/shortcut run inicio_trabalho
```

## Modo escuta (`/wake`)
1. Rode o agente e use `/wake`
2. Fale o comando direto

Exemplos:
- `abrir youtube`
- `abrir discord`
- `executar atalho manha`

Para sair do modo de chamada:
- pressione `Ctrl+C`, ou
- fale `parar escuta`

## Execução proativa (pergunta automática)
Com o modo proativo ativado, o agente compara os padrões do horário atual com seus atalhos salvos.
Quando houver boa correspondência, ele pergunta automaticamente se deve executar.

Exemplo de uso:

```text
/proactive status
/proactive on
```

## Atalhos pessoais (automação)
Você pode criar rotinas com várias ações em sequência usando `||`.

Prefixos de ação suportados:
- `open:` abre site, arquivo, pasta ou app
- `ps:` executa comando PowerShell
- `say:` fala um texto

Exemplo (abrir WhatsApp, pasta de trabalho e falar bom dia):

```text
/shortcut add manha open:https://web.whatsapp.com || open:C:\Users\Administrador\Desktop || say:Bora começar o dia
```

Executar:

```text
/shortcut run manha
```

## Exemplos rápidos
- `/open https://youtube.com`
- `/open C:\\Users\\Administrador\\Desktop`
- `/ps Get-Date`
- `/ps Get-Process | Select-Object -First 5`
- `/shortcut list`
- `/shortcut del manha`

## Observações
- As anotações ficam em `agent_memory.db`.
- O histórico da conversa fica apenas em memória durante a execução.
- Se a escuta não funcionar, verifique microfone/permissões e teste `STT_ENGINE`.
