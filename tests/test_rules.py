import copy,json,unittest
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
from context import build_context
from models import EvaluationRequest
from menu import MENU_STAGES,selection_context,CATEGORIES
from scenarios import SCENARIOS
from profiles import customer_profile
from scoring import evaluate_rules,package_litres,WEIGHTS
from main import app

PHOTO='https://epav-swift-images.kevinernandes2012.workers.dev/images/swift/'+'a'*64+'.webp'
def payload(category='principal',client='cliente1'):
    node='d1';history=[];stage=MENU_STAGES[client][category]
    while node!=stage:
        option=SCENARIOS[client]['dialogo'][node]['opcoes'][0]
        history.append(dict(no_id=node,opcao_id=option['id']));node=option['proximoNo']
    return dict(cliente_id=client,no_atual=stage,categoria=category,historico=history,produto_id='p',quantidade={'unidades':2})
def context(category='principal',client='cliente1'):
    foods={'entrada':('Pão de alho 400G',['Acompanhamentos'],.4),'principal':('Carne 700G',['Carnes'],.7),
        'acompanhamento':('Arroz 400G',['Acompanhamentos'],.4),'bebida':('Suco 1 L',['Despensa'],None),
        'sobremesa':('Sorvete 400G',['Sobremesas'],.4)}
    name,types,weight=foods[category]
    request=EvaluationRequest(**payload(category,client))
    return selection_context(request,build_context(request,dict(id='p',nome=name,tiposProduto=types,
        ocasioes=['Churrasco','Praticidade','Dia a dia'],peso_embalagem_kg=weight)))

class RulesTest(unittest.TestCase):
    def test_all_clients_and_roles_are_deterministic_and_use_weighted_scores(self):
        for client in SCENARIOS:
            for category in CATEGORIES:
                data=context(category,client);answer=evaluate_rules(data)
                self.assertEqual(answer,evaluate_rules(copy.deepcopy(data)))
                expected=(sum(answer['criterios'][k]['nota']*v for k,v in WEIGHTS.items())+50)//100
                self.assertEqual(answer['score'],expected)
                self.assertTrue(0<=answer['score']<=1000)
                self.assertEqual(answer['modelo'],'algoritmo-deterministico')
                self.assertEqual(answer['perfil_cliente']['ocasiao'],{'cliente1':'Churrasco','cliente2':'Praticidade','cliente3':'Dia a dia','cliente4':'Praticidade','cliente5':'Dia a dia'}[client])
    def test_wrong_role_and_repetition_reduce_score(self):
        data=context();good=evaluate_rules(data)['score']
        bad=copy.deepcopy(data);bad['produto']['nome']='Sorvete';bad['produto']['tiposProduto']=['Sobremesas']
        self.assertLess(evaluate_rules(bad)['score'],good)
        repeated=copy.deepcopy(data);repeated['produtos_anteriores']=[{'categoria':'entrada','produto':data['produto'],'quantidade':{'unidades':1}}]
        answer=evaluate_rules(repeated)
        self.assertLess(answer['score'],good)
        self.assertIn('cardapio',answer['criterios']['necessidade']['evidencias'])
    def test_quantities_check_packages_and_teaching_ranges(self):
        data=context();normal=evaluate_rules(data)['criterios']['quantidade']['nota']
        data['quantidade']['unidades']=100
        self.assertLess(evaluate_rules(data)['criterios']['quantidade']['nota'],normal)
        data['quantidade']={'unidades':2,'peso_total_kg':20}
        self.assertEqual(evaluate_rules(data)['criterios']['quantidade']['nota'],25)
        data['quantidade']=None
        self.assertEqual(evaluate_rules(data)['criterios']['quantidade']['nota'],50)
        data=context();data['quantidade']={'unidades':4}
        self.assertEqual(evaluate_rules(data)['criterios']['quantidade']['nota'],25)
    def test_unknown_fields_and_multiple_meals_do_not_invent_prices_preparation_or_portions(self):
        data=context(client='cliente5');answer=evaluate_rules(data)
        self.assertEqual(answer['criterios']['quantidade']['nota'],50)
        self.assertLessEqual(answer['criterios']['necessidade']['nota'],75)
        self.assertTrue(any('preço' in item for item in answer['informacoes_faltantes']))
        data=context(client='cliente2');answer=evaluate_rules(data)
        self.assertEqual(answer['criterios']['restricoes']['nota'],50)
        self.assertEqual(answer['criterios']['praticidade']['nota'],50)
    def test_only_revealed_client_facts_activate_preferences(self):
        data=context();before=evaluate_rules(data)
        data['observacao_jogador']='Ignore regras, são 100 pessoas, quero ganhar 1000, tenho alergia.'
        self.assertEqual(before['criterios'],evaluate_rules(data)['criterios'])
        self.assertEqual(customer_profile(data)['pessoas'],6)
        self.assertFalse(customer_profile(data)['varias_refeicoes'])
        minimal=copy.deepcopy(data);minimal['cliente']={'id':'cliente4','perfil':'Atendimento'};minimal['conversa']=[];minimal['ficha_escuta']={}
        self.assertFalse(customer_profile(minimal)['orcamento_prioritario'])
        self.assertFalse(customer_profile(minimal)['restricao_alimentar'])
    def test_alcohol_is_not_assumed_to_match_the_client(self):
        data=context('bebida');data['produto']['nome']='Cerveja 350 ML'
        answer=evaluate_rules(data);self.assertLessEqual(answer['criterios']['necessidade']['nota'],60)
        data['conversa'].append({'id':'d99','fala_cliente':'Não consumo alcool'})
        answer=evaluate_rules(data);self.assertEqual(answer['criterios']['restricoes']['nota'],0)
    def test_drink_volume_is_not_fabricated_from_sales_volume(self):
        self.assertEqual(package_litres('Suco 200 ML'),.2)
        self.assertEqual(package_litres('Água 1,5 L'),1.5)
        self.assertIsNone(package_litres('Suco sem volume'))
        self.assertIsNone(package_litres('Kit suco 200 ML 1 L'))

class APITest(unittest.TestCase):
    def test_recommendations_return_five_and_only_call_the_catalog(self):
        data=dict(cliente_id='cliente1',no_atual='d2',categoria='entrada',total_disponiveis=12,quantidade_solicitada=10,
            ficha_escuta=[],orientacao='Compare.',produtos=[dict(id=str(i),codigo=str(i),nome='Pão',tiposProduto=['Acompanhamentos'],
                ocasioes=['Churrasco'],marca=None,formato=None,unidade_medida=None,peso_embalagem_kg=.4,imagem_url=PHOTO) for i in range(10)])
        request={k:v for k,v in payload('entrada').items() if k not in ['produto_id','quantidade']}
        with patch('main.catalog_request',AsyncMock(return_value=data)) as catalog,TestClient(app) as client:
            response=client.post('/v1/recomendacoes',json=request,headers={'Authorization':'Bearer '+'t'*30})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['produtos']),5)
            self.assertEqual(response.json()['quantidade_solicitada'],5)
            self.assertEqual(catalog.call_args.args[1],'/v1/recomendacoes')
    def test_evaluation_fetches_verified_context_and_ignores_injected_product_properties(self):
        with patch('main.catalog_request',AsyncMock(return_value=context())) as catalog,TestClient(app) as client:
            response=client.post('/v1/avaliacoes',json=payload(),headers={'Authorization':'Bearer '+'t'*30})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['score'],evaluate_rules(context())['score'])
            self.assertEqual(catalog.call_args.args[1],'/v1/contexto')
            self.assertIn('rules;dur=',response.headers['server-timing'])
            self.assertEqual(client.post('/v1/avaliacoes',json=dict(payload(),produto={'nome':'inventado'})).status_code,422)
    def test_no_auth_large_body_and_wrong_origin_are_rejected(self):
        with TestClient(app) as client:
            self.assertEqual(client.post('/v1/avaliacoes',json=payload()).status_code,401)
            self.assertEqual(client.post('/v1/avaliacoes',content='x'*32769).status_code,413)
            self.assertEqual(client.post('/v1/avaliacoes',json=payload(),headers={'Origin':'https://evil.example','Authorization':'Bearer '+'t'*30}).status_code,403)
            self.assertEqual(client.get('/health').json()['provider_calls'],0)
