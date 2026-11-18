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
    
    path('cancelamento/', views.buscar_matricula_cancelamento, name='buscar_matricula_cancelamento'),
    path('cancelamento/<int:matricula_id>/', views.cancelar_matricula, name='cancelar_matricula'),

    path('renovacoes/', views.listar_renovacoes, name='listar_renovacoes'),
    path('renovacoes/<int:matricula_id>/confirmar/', views.confirmar_renovacao, name='confirmar_renovacao'),
]