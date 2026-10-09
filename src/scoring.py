"""Deterministic educational rubric. No model, provider or generative fallback."""
import hashlib,json,math,re
from models import EvaluationResponse,Criterion
from menu import roles
from profiles import customer_profile
from recommendations import normalize

WEIGHTS=dict(necessidade=350,ocasiao=250,praticidade=150,restricoes=150,quantidade=100)
VERSION='epav-regras-v1'
# Teaching ranges for ONE meal, not nutritional requirements or verified portions.
MASS_RANGES={'entrada':(.05,.15),'principal':(.15,.35),'acompanhamento':(.08,.25),'sobremesa':(.06,.18)}
DRINK_RANGE=(.15,.50)

def package_litres(name):
    values=re.findall(r'(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(ML|L)\b',str(name).upper())
    if len(values)!=1:return None
    number,unit=values[0];amount=float(number.replace(',','.'))/(1000 if unit=='ML' else 1)
    return amount if 0<amount<=30 else None

def evaluate_rules(context):
    profile=customer_profile(context)
    product=context['produto'];category=context['categoria_refeicao'];quantity=context.get('quantidade')
    previous=context.get('produtos_anteriores',[])
    criteria={};missing=[]
    def criterion(key,note,text,refs):criteria[key]=Criterion(nota=note,justificativa=text,evidencias=refs)
    role_matches=category in roles(product)
    types_match=category!='principal' or bool(set(product.get('tiposProduto',[]))&set(profile['tipos_principal']))
    repeated=any(entry['produto']['id']==product['id'] for entry in previous)
    necessary=90 if role_matches and types_match else 20
    reasons=[]
    if role_matches and types_match:reasons.append('O alimento corresponde à etapa da refeição e aos tipos do perfil.')
    else:reasons.append('O tipo do alimento não corresponde à categoria ou aos tipos solicitados pelo cliente.')
    if profile['preparo_prioritario'] or profile['orcamento_prioritario'] or profile['restricao_alimentar']:
        necessary=min(necessary,75);reasons.append('Ainda faltam dados para confirmar as prioridades do cliente.')
    name=normalize(product['nome'])
    alcohol=category=='bebida' and bool(re.search(r'\b(cerveja|vinho|espumante)\b',name))
    if alcohol:
        necessary=min(necessary,0 if profile['evita_alcool'] else 60)
        reasons.append('A preferência por bebida alcoólica precisa ser confirmada.' if not profile['evita_alcool'] else 'O cliente declarou que evita álcool.')
        if not profile['evita_alcool']:missing.append('O cliente aceita bebida alcoólica?')
    if repeated:
        necessary=max(0,necessary-20);reasons.append('Este mesmo produto já foi indicado em outra etapa.')
    criterion('necessidade',necessary,' '.join(reasons),['perfil','produto']+(['cardapio'] if repeated else []))
    occasions=product.get('ocasioes',[])
    if not role_matches:occasion=20;reason='O alimento não cumpre o papel pedido para esta parte da refeição.'
    elif profile['ocasiao'] in occasions:occasion=90;reason='A ocasião cadastrada corresponde ao uso do cliente.'
    elif not occasions:occasion=50;reason='A ocasião não está informada na ficha do produto.'
    elif category=='principal':occasion=25;reason='A ocasião cadastrada do principal difere do uso solicitado.'
    else:occasion=65;reason='A categoria corresponde à etapa, mas a ficha não confirma a ocasião do cliente.'
    if previous and role_matches and not repeated:
        reason+=' A indicação ocupa outra categoria, complementando as anteriores.'
    criterion('ocasiao',occasion,reason,['perfil','produto']+(['cardapio'] if previous else []))
    criterion('praticidade',50 if profile['preparo_prioritario'] else 75,
        'O catálogo não confirma método nem tempo de preparo; é preciso conferir essa prioridade.' if profile['preparo_prioritario']
        else 'Não há exigência de rapidez de preparo declarada; a pressa na compra não comprova pressa para cozinhar.', ['perfil','produto'])
    if profile['preparo_prioritario']:missing.append('Qual é o método e o tempo de preparo deste produto?')
    criterion('restricoes',0 if alcohol and profile['evita_alcool'] else 50 if profile['restricao_alimentar'] else 100,
        'A bebida conflita com a preferência declarada por evitar álcool.' if alcohol and profile['evita_alcool'] else
        'Faltam a restrição específica e a composição; a categoria não comprova ingredientes ou alergênicos.' if profile['restricao_alimentar'] else
        'Não foi declarada uma restrição alimentar no contexto revelado.', ['perfil','produto'])
    if profile['restricao_alimentar']:missing.append('Quais são as restrições e qual é a composição do produto?')
    if profile['orcamento_prioritario']:missing.append('Qual é o preço total e o limite de gasto do cliente?')
    amount=None;expected=None;unit='kg'
    package=product.get('peso_embalagem_kg')
    if quantity and isinstance(package,(int,float)) and math.isfinite(package) and package>0:expected=package*quantity['unidades']
    if category=='bebida':
        litres=package_litres(product['nome']);unit='L'
        if litres and quantity:amount=litres*quantity['unidades']
    else:amount=expected
    if not quantity:note=50;reason='A quantidade não foi informada.';missing.append('Quantas embalagens serão indicadas?')
    elif expected and quantity.get('peso_total_kg') and not math.isclose(expected,quantity['peso_total_kg'],rel_tol=.02,abs_tol=.01):
        note=25;reason=f"As embalagens somam {expected:g} kg, diferente do peso total informado."
    elif amount is None or not profile['pessoas']:
        note=50;reason='Faltam peso ou volume da embalagem e número de pessoas para comparar a quantidade.'
        missing.append('Qual é o peso ou volume da embalagem e para quantas pessoas será usada?')
    elif profile['varias_refeicoes']:
        note=50;reason='O cliente compra para mais de uma refeição; o número de refeições ainda precisa ser confirmado.'
        missing.append('Para quantas refeições essa quantidade será usada?')
    else:
        low,high=DRINK_RANGE if category=='bebida' else MASS_RANGES[category]
        per_person=amount/profile['pessoas']
        note=75 if low<=per_person<=high else 50 if low*.5<=per_person<=high*1.75 else 25
        reason=f"A quantidade calculada é {per_person:.2f} {unit} por pessoa para uma refeição; "
        reason+=('fica na faixa didática desta categoria.' if note==75 else 'fica fora da faixa didática desta categoria.')
        if profile['evitar_sobras'] and per_person>high:
            note=min(note,25)
            reason+=' O excesso também conflita com a prioridade declarada de evitar sobras.'
        reason+=' A faixa é uma referência de treino; confirme consumo e sobras.'
        missing.append('A quantidade atende ao consumo real, considerando as outras partes da refeição?')
    criterion('quantidade',note,reason,['perfil','produto','quantidade'])
    score=(sum(criteria[key].nota*weight for key,weight in WEIGHTS.items())+50)//100
    if not role_matches and category=='principal' and profile['ocasiao'] not in occasions:score=min(score,200)
    answer=EvaluationResponse(score=score,percentual_adequacao=score/10,
        classificacao='excelente' if score>=850 else 'boa' if score>=650 else 'parcial' if score>=400 else 'inadequada',
        criterios=criteria,resumo=f"A escolha de {product['nome']} recebeu {score}/1000 pela rubrica de regras.",
        sugestao=('Confira: '+' '.join(missing[:3]))[:500] if missing else 'Confirme a aceitação do cliente e continue montando a refeição.',
        informacoes_faltantes=list(dict.fromkeys(missing))[:8],versao_rubrica=VERSION,modelo='algoritmo-deterministico',
        contexto_hash=hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
        produto_id=product['id'],cliente_id=context['cliente']['id'])
    return dict(answer.model_dump(),perfil_cliente=profile)
