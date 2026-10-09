"""Fixed, reviewed teaching options. Product scores are revealed locally after selection."""
from popup_data import POPUP_SCRIPTS
import re

class PopupError(ValueError):
    pass

def validate_popup(choice):
    script=POPUP_SCRIPTS.get(choice.cliente_id)
    if script is None:raise PopupError('Cliente desconhecido.')
    stages=script['etapas']
    for index,decision in enumerate(choice.historico):
        if index>=len(stages):raise PopupError('Histórico longo demais.')
        stage=stages[index]
        if decision.no_id!=stage['id'] or not any(o['id']==decision.opcao_id for o in stage['alternativas_cadastradas']):
            raise PopupError('Histórico incompatível com o roteiro de produtos.')
    index=len(choice.historico)
    if index>=len(stages):raise PopupError('Atendimento encerrado.')
    stage=stages[index]
    if stage['id']!=choice.no_atual or stage.get('popup_produtos_ref')!=choice.categoria:
        raise PopupError('Categoria incompatível com a etapa atual.')
    return script['popups'][choice.categoria]

def fixed_cards(popup,catalog):
    by_code={p['codigo']:p for p in catalog['produtos']}
    result=[]
    for option in popup['opcoes']:
        code=str(option['codigo']);card=by_code.get(code)
        # Do not use a similar SKU's photo or replace a scored teaching option.
        result.append(dict(id=code,codigo=code,nome=option['nome'],
            tiposProduto=card['tiposProduto'] if card else [],ocasioes=card['ocasioes'] if card else [],
            marca=card['marca'] if card else 'Swift',formato=card['formato'] if card else None,
            unidade_medida=card['unidade_medida'] if card else None,
            peso_embalagem_kg=package_weight(option['nome']),imagem_url=card['imagem_url'] if card else None))
    return result

def package_weight(name):
    matches=re.findall(r'(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(KG|G)\b',str(name).upper())
    if len(matches)!=1:return None
    number,unit=matches[0]
    weight=float(number.replace(',','.'))/(1000 if unit=='G' else 1)
    return weight if 0<weight<=30 else None
