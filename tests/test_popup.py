import unittest
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
from popup_data import POPUP_SCRIPTS
from popup import validate_popup,fixed_cards,PopupError
from models import PopupRequest
from main import app

def payload(client='cliente1',index=4):
    stages=POPUP_SCRIPTS[client]['etapas']
    return dict(roteiro='popup-v1',cliente_id=client,no_atual=stages[index]['id'],categoria=stages[index]['popup_produtos_ref'],
        historico=[dict(no_id=s['id'],opcao_id=s['alternativas_cadastradas'][0]['id']) for s in stages[:index]])

class PopupTest(unittest.TestCase):
    def test_all_fixed_groups_have_five_different_codes_and_accept_their_official_history(self):
        for client in POPUP_SCRIPTS:
            for i,stage in enumerate(POPUP_SCRIPTS[client]['etapas']):
                if not stage.get('popup_produtos_ref'):continue
                popup=validate_popup(PopupRequest(**payload(client,i)))
                cards=fixed_cards(popup,{'produtos':[]})
                self.assertEqual(len(cards),5)
                self.assertEqual(len({p['codigo'] for p in cards}),5)
                self.assertTrue(all(p['imagem_url'] is None for p in cards))
                self.assertTrue(all('pontuacao' not in p and 'classificacao' not in p for p in cards))
    def test_fake_options_and_wrong_stage_are_rejected_before_catalog_requests(self):
        bad=payload();bad['historico'][0]['opcao_id']='fake'
        with self.assertRaises(PopupError):validate_popup(PopupRequest(**bad))
        with patch('main.catalog_request',AsyncMock()) as upstream,TestClient(app) as client:
            response=client.post('/v2/recomendacoes',json=bad)
            self.assertEqual(response.status_code,422);upstream.assert_not_called()
    def test_only_exact_sku_photo_is_used_and_product_scores_are_never_revealed_by_catalog(self):
        request=payload();popup=validate_popup(PopupRequest(**request))
        code=str(popup['opcoes'][0]['codigo'])
        card={'codigo':code,'tiposProduto':['Acompanhamentos'],'ocasioes':['Churrasco'],'marca':'Swift',
            'formato':None,'unidade_medida':'UN','imagem_url':'photo'}
        with patch('main.catalog_request',AsyncMock(return_value={'produtos':[card]})) as upstream,TestClient(app) as client:
            response=client.post('/v2/recomendacoes',json=request,headers={'Authorization':'Bearer '+'t'*30})
            self.assertEqual(response.status_code,200,response.text)
            products=response.json()['produtos'];self.assertEqual(products[0]['imagem_url'],'photo')
            self.assertTrue(all(p['imagem_url'] is None for p in products[1:]))
            self.assertNotIn('pontuacao',response.text)
            self.assertEqual(upstream.call_args.args[1],'/v1/catalogo/itens')
            self.assertEqual(upstream.call_args.args[2],{'codigos':[str(o['codigo']) for o in popup['opcoes']]})
    def test_public_fixed_catalog_still_requires_firebase_session(self):
        with TestClient(app) as client:
            self.assertEqual(client.post('/v2/recomendacoes',json=payload()).status_code,401)
            bad=payload();bad['categoria']=None
            self.assertEqual(client.post('/v2/recomendacoes',json=bad).status_code,422)
