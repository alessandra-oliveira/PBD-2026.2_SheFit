from django.urls import path
from . import views

urlpatterns = [
    path('entrada/', views.tela_entrada_recepcao, name='tela_entrada_recepcao'),
    path('entrada/liberar-excepcional/', views.liberar_excepcional, name='liberar_excepcional_recepcao'),
    path('liberacoes/', views.historico_liberacoes, name='historico_liberacoes'),
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

    path('matriculas/<int:matricula_id>/trancar/', views.trancar_matricula_view, name='trancar_matricula'),
    path('matriculas/<int:matricula_id>/trancamentos/', views.historico_trancamentos, name='historico_trancamentos'),
    path('trancamentos/', views.historico_geral_trancamentos, name='historico_geral_trancamentos'),
]