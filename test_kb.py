#!/usr/bin/env python3
"""Test Knowledge Base system."""

import sys
sys.path.insert(0, '.')

from personal_ai_agent import PersonalAIAgent

print("Inicializando agente...")
agent = PersonalAIAgent()

print("\n[KB] Teste do Knowledge Base:\n")

# 1. Seed KB
print("[1] Seedando KB com topicos iniciais...")
agent.seed_knowledge_base_auto()
print("OK - Seed completo\n")

# 2. Ver stats
print("[2] Stats do KB:")
stats = agent.get_kb_stats()
print(f"    Total: {stats['total']} entradas")
for cat, count in stats['by_category'].items():
    print(f"    - {cat}: {count}")
print()

# 3. Buscar no KB
print("[3] Buscando 'historia brasil' no KB:")
results = agent.query_knowledge_base("historia brasil", limit=2)
for row_id, topic, content, category in results:
    print(f"    [{category}] {topic}:")
    print(f"    {content[:100]}...")
print()

# 4. Aprender novo topico
print("[4] Aprendendo sobre novo topico (Linguistica)...")
result = agent.learn_topic_interactive("Linguistica e idiomas")
if "Aprendi" in result:
    print("    Novo topico aprendido!")
else:
    print(f"    {result[:80]}...")
print()

# 5. Nova busca
print("[5] Testando ask() COM contexto do KB:")
print("    Pergunta: O que voce sabe sobre historia?")
answer = agent.ask("O que voce sabe sobre historia?")
print(f"    Resposta: {answer[:200]}...\n")

print("OK - Todos os testes completados!")

