"""Only revealed script facts can activate a customer requirement."""
import re
from recommendations import normalize,PRODUCT_PARAMETERS

def customer_profile(context):
    text=normalize(' '.join([context['cliente']['perfil'],*context['ficha_escuta'].values(),
        *(turn['fala_cliente'] for turn in context['conversa'])]))
    facts=context['ficha_escuta']
    # No player observation or seller response can activate a claimed client need.
    people=None
    if 'mora sozinha' in text or 'moro sozinha' in text:people=1
    match=re.search(r'\b(seis|quatro|6|4) pessoas\b',text)
    if match:people={'seis':6,'quatro':4,'6':6,'4':4}[match[1]]
    profile=dict(
        pessoas=people,
        ocasiao=PRODUCT_PARAMETERS[context['cliente']['id']]['ocasiao'],
        tipos_principal=list(PRODUCT_PARAMETERS[context['cliente']['id']]['tipos']),
        preparo_prioritario=bool(set(facts)&{'praticidade','tempo','preparo'} or any(s in text for s in ('pratic','prepar','cozinha'))),
        orcamento_prioritario=bool('orcamento' in facts or any(s in text for s in ('orcamento','economiz','preco','gastar'))),
        restricao_alimentar=bool('restricoes' in facts or any(s in text for s in ('restric','alerg','ingrediente'))),
        evitar_sobras=any(s in text for s in ('desperdic','sobras','sobrar')),
        varias_refeicoes=any(s in re.sub(r'\b(?:fim|final) de semana\b','',text) for s in ('semana','todos os dias')),
        evita_alcool=bool(re.search(r'\b(sem alcool|nao (?:bebo|quero|consumo) (?:alcool|bebida alcoolica))\b',text)),
    )
    tags=[profile['ocasiao']]
    if people:tags.append(f'{people} pessoa(s)')
    for key,label in [('preparo_prioritario','Preparo prático'),('orcamento_prioritario','Controle de gastos'),
        ('restricao_alimentar','Restrições a confirmar'),('evitar_sobras','Evitar sobras'),('varias_refeicoes','Mais de uma refeição')]:
        if profile[key]:tags.append(label)
    profile['descricao']=' · '.join(tags)
    return profile
