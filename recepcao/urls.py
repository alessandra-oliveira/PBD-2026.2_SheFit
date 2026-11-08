from django.urls import path
from . import views

urlpatterns = [
    path('entrada/', views.tela_entrada_recepcao, name='tela_entrada_recepcao'),
    path('pagamentos/', views.listar_cobrancas_pagamento, name='listar_cobrancas_pagamento'),
    path(
        'pagamentos/cobranca/<int:cobranca_id>/',
        views.registrar_pagamento,
        name='registrar_pagamento',
    ),
    path(
        'pagamentos/<int:pagamento_id>/estorno/',
        views.registrar_estorno,
        name='registrar_estorno',
    ),
]