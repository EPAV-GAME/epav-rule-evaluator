"""Scenario parameters and text normalization shared with the catalog contract."""
import unicodedata
PRODUCT_PARAMETERS={
    'cliente1':{'ocasiao':'Churrasco','tipos':('Carnes','Aves')},
    'cliente2':{'ocasiao':'Praticidade','tipos':('Carnes','Aves','Pescados','Acompanhamentos')},
    'cliente3':{'ocasiao':'Dia a dia','tipos':('Carnes',)},
    'cliente4':{'ocasiao':'Praticidade','tipos':('Carnes','Aves','Pescados','Acompanhamentos')},
    'cliente5':{'ocasiao':'Dia a dia','tipos':('Carnes','Aves','Pescados','Acompanhamentos')},
}
def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD',str(text).lower()) if unicodedata.category(c)!='Mn')
