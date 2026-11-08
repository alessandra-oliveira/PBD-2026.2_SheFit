from django.db import models


class Agendamento(models.Model):
    """Uma reserva de vaga, ou um lugar na lista de espera, de um aluno numa turma (T11).
    este model só deve ser alterado pelas funções de
    agendamentos/servicos.py. São elas que travam a turma no banco para que
    duas pessoas nunca ocupem a mesma última vaga.
    """

    class Status(models.TextChoices):
        RESERVADO = 'reservado', 'Reservado'
        ESPERA = 'espera', 'Lista de espera'
        CANCELADO = 'cancelado', 'Cancelado'

    turma = models.ForeignKey('turmas.Turma', on_delete=models.PROTECT, related_name='agendamentos')
    aluno = models.ForeignKey('alunos.Aluno', on_delete=models.PROTECT, related_name='agendamentos')
    status = models.CharField(max_length=10, choices=Status.choices)

    # a ordem de entrada na fila é a ordem do id (as gravações acontecem com a turma travada)
    criado_em = models.DateTimeField(auto_now_add=True)
    promovido_em = models.DateTimeField(null=True, blank=True)
    cancelado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Agendamento'
        verbose_name_plural = 'Agendamentos'
        ordering = ['id']
        constraints = [
            # Garantia do banco: um aluno não pode ter dois agendamentos ATIVOS na mesma turma.
            models.UniqueConstraint(
                fields=['turma', 'aluno'],
                condition=models.Q(status__in=['reservado', 'espera']),
                name='um_agendamento_ativo_por_aluno_e_turma',
            ),
        ]
        indexes = [
            models.Index(fields=['turma', 'status'], name='agend_turma_status_idx'),
        ]

    def posicao_na_fila(self):
        """1 = o próximo a ganhar vaga. None se não está na lista de espera."""
        if self.status != self.Status.ESPERA:
            return None
        na_frente = Agendamento.objects.filter(
            turma_id=self.turma_id, status=self.Status.ESPERA, id__lt=self.id,
        ).count()
        return na_frente + 1

    def __str__(self):
        return f'{self.aluno} em {self.turma} ({self.get_status_display()})'