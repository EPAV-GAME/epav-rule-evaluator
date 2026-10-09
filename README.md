# EPAV — API de avaliação sem IA

FastAPI no Cloudflare Workers. Seleciona **cinco produtos com foto por categoria** (entrada, principal, acompanhamento, bebidas e sobremesas) e calcula adequação de 0 a 1000 com regras determinísticas. Não usa Groq, modelos, prompts nem chamadas de IA.

- [Jogo sem IA](https://epav-game.github.io/epav-game-sem-ia/)
- [API publicada](https://epav-rule-evaluator.kevinernandes2012.workers.dev/docs)
- [Versão com IA](https://epav-game.github.io/epav-game/)
- [Catálogo compartilhado](https://github.com/EPAV-GAME/epav-product-evaluator)

## Como funciona

1. O jogo envia ID do cliente, etapa, decisões do diálogo, categoria e ID do produto escolhido.
2. Um service binding consulta o serviço de catálogo já existente. Ele verifica o ID token Firebase, limites de requisição, sequência do roteiro e ordem das categorias. Busca as fichas atuais e anteriores no catálogo público compartilhado no Redis.
3. Esta API calcula o score localmente. As propriedades enviadas pelo jogador não são aceitas como ficha de produto. Observações e respostas do vendedor não comprovam preferências do cliente.
4. O jogador recebe as notas, justificativas, perguntas pendentes e o perfil estruturado considerado.

Não há credencial Firebase privilegiada nem senha Redis neste Worker. O acesso ao catálogo é autenticado; o serviço central conserva suas credenciais existentes. Compartilhar o catálogo não chama a parte de avaliação com IA. O binding usa exclusivamente `/v1/recomendacoes`, `/v1/contexto` e `/v1/ranking`.

## Rubrica `epav-regras-v1`

| Critério | Peso em 1000 | Regras principais |
|---|---:|---|
| Necessidade | 350 | Categoria e tipos do perfil: 90; conflito: 20. Preparo, orçamento ou restrição sem comprovação limitam a 75. Produto repetido perde 20. Álcool sem preferência confirmada limita a 60. |
| Ocasião | 250 | Ocasião cadastrada compatível: 90. Principal com ocasião diferente: 25. Outras categorias compatíveis com ocasião não comprovada: 65. Ausente: 50. Categoria errada: 20. |
| Praticidade | 150 | Prioridade de preparo sem método/tempo no catálogo: 50. Sem essa prioridade declarada: 75. Pressa na compra não significa preparo rápido. |
| Restrições | 150 | Sem restrição declarada: 100. Restrição sem composição: 50. Álcool quando o cliente declarou evitá-lo: 0. |
| Quantidade | 100 | Peso inconsistente com embalagens: 25. Peso/volume ou pessoas desconhecidos: 50. Compra para várias refeições sem número confirmado: 50. Faixa didática de uma refeição: 75; desvio moderado: 50; grande desvio: 25. |

`score = (soma(nota × peso) + 50) // 100`. Classificações: excelente ≥850, boa ≥650, parcial ≥400, inadequada <400. Mesma entrada e mesma ficha resultam sempre na mesma avaliação. O hash inclui o contexto completo; a nota não muda por uma observação arbitrária do jogador.

As faixas de quantidade são **referências de treino para uma refeição**, não porções nutricionais nem garantias de consumo: entrada 50–150 g/pessoa; principal 150–350 g; acompanhamento 80–250 g; sobremesa 60–180 g; bebida 150–500 mL. Compare somente peso/volume real identificado no nome da embalagem e quantidade de pessoas revelada. Volume de vendas da planilha nunca vira peso de embalagem. Para compras da semana, não se inventa número de refeições. Se o cliente pede para evitar sobras, quantidade acima da faixa didática limita esse critério a 25.

## Perfis estruturados

`src/profiles.py` deriva do perfil oficial e das falas já reveladas:

- Pessoas atendidas, quando informadas (Lucas: 6; Marina: 1; André: 4).
- Ocasião e tipos de principal definidos pelo cenário.
- Prioridade de preparo, orçamento, restrições, evitar sobras e mais de uma refeição.
- Preferência explícita por evitar álcool.

As necessidades descobertas nas falas futuras não são antecipadas. Preço, composição, alergênicos e tempo de preparo permanecem desconhecidos quando não constam do catálogo; a regra não trata essas lacunas como erro comprovado do jogador.

## Redis e Firebase

Os dois jogos e suas APIs compartilham **o mesmo catálogo compactado**, a mesma geração de invalidação e o ranking público. Catálogo: até 15 minutos; ranking: até 30 segundos; memória da instância: até 30 segundos, respeitando o TTL e consultando invalidação a cada 5 segundos. Os produtos atuais e anteriores saem desse catálogo; não há uma consulta Firestore para cada indicação. Admin e bot continuam invalidando o serviço central.

Token, autenticação, permissões, gravações, informações comerciais e resultados do jogador não são armazenados no Redis. Se o Redis falhar, o serviço de catálogo consulta o Firebase com circuito e memória curta; se o Firebase falhar, responde erro em vez de inventar produtos. A pontuação lógica é barata e calculada localmente a cada pedido.

## Contrato

`POST /v1/recomendacoes` e `POST /v1/avaliacoes` exigem `Authorization: Bearer <ID_TOKEN_FIREBASE>`. Mesmas etapas e formato da versão com IA; `categoria` é obrigatória. A resposta de recomendações contém até cinco produtos reais, `quantidade_solicitada=5` e a contagem de candidatos. Não preenche com produtos sem foto ou da categoria errada.

Avaliação inclui `criterios`, `score`, `modelo=algoritmo-deterministico`, `versao_rubrica=epav-regras-v1`, `perfil_cliente` e `Server-Timing` com catálogo/regras. `GET /v1/ranking` mantém o ranking público das respostas do diálogo. `GET /health` identifica o modo sem IA e cinco opções por categoria.

## Desenvolvimento e publicação

```powershell
uv sync --locked
$env:PYTHONPATH='src'
uv run python -m unittest discover -s tests -v
npm ci
uv run pywrangler deploy --dry-run
uv run pywrangler deploy --profile epav
```

O workflow verifica testes e bundle a cada push. A publicação no Cloudflare é executada pela conta autorizada, sem colocar token do Wrangler no repositório. O Worker de catálogo deve estar publicado antes deste. [Documentação dos service bindings HTTP](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/http/).

As duas rubricas medem adequação pedagógica, não probabilidade estatística, e suas notas não são diretamente comparáveis.
