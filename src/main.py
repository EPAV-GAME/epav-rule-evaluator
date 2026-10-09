"""FastAPI scoring service without any AI provider or privileged Firebase key."""
import asyncio,json,time,sys
import httpx
from fastapi import FastAPI,Request,Response,HTTPException,Security
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from models import EvaluationRequest,RecommendationRequest,RecommendationResponse,PopupRequest
from scoring import evaluate_rules,VERSION

CATALOG_URL='https://epav-product-evaluator.kevinernandes2012.workers.dev'
ORIGIN='https://epav-game.github.io'
app=FastAPI(title='EPAV — Avaliação sem IA',version='1.0.0',description='Cinco opções por categoria e score por regras pedagógicas auditáveis.')
class BodyLimit:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST':return await self.app(scope,receive,send)
        messages=[];size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            size+=len(message.get('body',b''))
            if size>32768:return await JSONResponse({'detail':'REQUEST_TOO_LARGE'},413)(scope,receive,send)
            messages.append(message)
            if not message.get('more_body'):break
        async def replay():return messages.pop(0) if messages else await receive()
        await self.app(scope,replay,send)
app.add_middleware(BodyLimit)
app.add_middleware(CORSMiddleware,allow_origins=[ORIGIN],allow_methods=['GET','POST'],
    allow_headers=['Authorization','Content-Type'],expose_headers=['Server-Timing'],max_age=3600)
bearer=HTTPBearer(auto_error=False)

async def catalog_request(request,path,payload=None,credentials=None):
    if path not in ['/v1/recomendacoes','/v1/contexto','/v1/ranking','/v1/catalogo/itens']:raise HTTPException(400,'INVALID_CATALOG_PATH')
    if request.headers.get('origin') and request.headers['origin']!=ORIGIN:raise HTTPException(403,'ORIGIN_NOT_ALLOWED')
    headers={};method='GET' if payload is None else 'POST'
    if payload is not None:
        if credentials is None or not 20<=len(credentials.credentials)<=4096:raise HTTPException(401,'FIREBASE_TOKEN_REQUIRED')
        headers={'Authorization':'Bearer '+credentials.credentials,'Content-Type':'application/json'}
    if request.headers.get('cf-connecting-ip'):headers['cf-connecting-ip']=request.headers['cf-connecting-ip']
    # The trusted catalog verifies tokens/rate limits freshly and reuses the shared Redis pool.
    env=request.scope.get('env');binding=getattr(env,'PRODUCT_CATALOG',None) if env is not None else None
    async with asyncio.timeout(40):
        if binding is not None:
            from js import Request as JSRequest,Object
            from pyodide.ffi import to_js
            options={'method':method,'headers':headers}
            if payload is not None:options['body']=json.dumps(payload)
            upstream=await binding.fetch(JSRequest.new(CATALOG_URL+path,to_js(options,dict_converter=Object.fromEntries)))
            status=upstream.status;body=await upstream.text()
        elif env is not None:raise HTTPException(503,'CATALOG_BINDING_NOT_CONFIGURED')
        else:
            # Native development only. This is always the fixed trusted catalog URL.
            async with httpx.AsyncClient(timeout=40,follow_redirects=False) as client:
                upstream=await client.request(method,CATALOG_URL+path,headers=headers,json=payload)
                status=upstream.status_code;body=upstream.text
    if len(body)>256000:raise HTTPException(502,'CATALOG_RESPONSE_TOO_LARGE')
    try:data=json.loads(body)
    except ValueError:raise HTTPException(502,'CATALOG_UNAVAILABLE') from None
    if status!=200:
        code=data.get('detail')
        raise HTTPException(status,code if isinstance(code,str) else 'CATALOG_UNAVAILABLE')
    return data

@app.exception_handler(TimeoutError)
async def timeout_error(request,error):return JSONResponse({'detail':'CATALOG_TIMEOUT'},503)

@app.post('/v2/recomendacoes')
async def fixed_recommendations(choice:PopupRequest,request:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
    from popup import validate_popup,fixed_cards,PopupError
    try:popup=validate_popup(choice)
    except PopupError as error:raise HTTPException(422,str(error)) from None
    catalog=await catalog_request(request,'/v1/catalogo/itens',
        {'codigos':[str(o['codigo']) for o in popup['opcoes']]},credentials)
    return dict(cliente_id=choice.cliente_id,no_atual=choice.no_atual,categoria=choice.categoria,
        produtos=fixed_cards(popup,catalog),quantidade_solicitada=5,total_disponiveis=5,
        ficha_escuta=[],orientacao='Cinco opções do roteiro. Compare uso, preparo e quantidade; a compra não é obrigatória.')

@app.post('/v1/recomendacoes',response_model=RecommendationResponse)
async def recommendations(choice:RecommendationRequest,request:Request,response:Response,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
    if choice.categoria is None:raise HTTPException(422,'MEAL_CATEGORY_REQUIRED')
    start=time.monotonic();result=await catalog_request(request,'/v1/recomendacoes',choice.model_dump(),credentials)
    result['produtos']=result['produtos'][:5];result['quantidade_solicitada']=5
    response.headers['Server-Timing']=f'catalog;dur={(time.monotonic()-start)*1000:.1f}'
    return result

@app.post('/v1/avaliacoes')
async def evaluate(choice:EvaluationRequest,request:Request,response:Response,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
    if choice.categoria is None:raise HTTPException(422,'MEAL_CATEGORY_REQUIRED')
    start=time.monotonic();context=await catalog_request(request,'/v1/contexto',choice.model_dump(),credentials)
    fetched=time.monotonic();result=evaluate_rules(context)
    response.headers['Server-Timing']=f'catalog;dur={(fetched-start)*1000:.1f}, rules;dur={(time.monotonic()-fetched)*1000:.1f}'
    return result

@app.get('/v1/ranking')
async def ranking(request:Request):return await catalog_request(request,'/v1/ranking')

@app.get('/health')
async def health():return dict(service='epav-rule-evaluator',modo='sem_ia',versao_rubrica=VERSION,opcoes_por_categoria=5,
    provider_calls=0,cache='catalogo_e_ranking_compartilhados_no_redis')

if sys.platform=='emscripten':
    from workers import asgi
    Default=asgi.entrypoint(app)
