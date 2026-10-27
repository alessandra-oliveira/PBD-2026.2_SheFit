from django.db import models
from alunos.models import Aluno

class Frequencia(models.Model):
    aluno = models.ForeignKey(
        Aluno, 
        on_delete=models.CASCADE, 
        related_name='frequencias', 
        verbose_name="Aluno"
    )
    data_hora = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Data e Hora da Entrada"
    )
    liberado = models.BooleanField(
        default=True, 
        verbose_name="Acesso Liberado?"
    )
    observacao = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name="Observação / Aviso"
    )

    class Meta:
        verbose_name = "Frequência"
        verbose_name_plural = "Frequências"
        ordering = ['-data_hora']

    def __str__(self):
        status = "Liberado" if self.liberado else "Bloqueado"
        return f"{self.aluno.nome} - {self.data_hora.strftime('%d/%m/%Y %H:%M')} ({status})"