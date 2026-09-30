from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User


class GrupoValor(models.Model):
    """
    Grupo de valores: base + bônus cheio (100%) + especialidades associadas.
    """
    nome = models.CharField(max_length=120, unique=True)
    valor_base = models.DecimalField(max_digits=10, decimal_places=2, default=100)
    bonus = models.DecimalField(max_digits=10, decimal_places=2, default=40)
    ordem = models.IntegerField(default=0)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ordem', 'nome']
        verbose_name = 'Grupo de Valor'
        verbose_name_plural = 'Grupos de Valores'

    def __str__(self):
        return self.nome

    @property
    def valor_hora_0(self):
        return self.valor_base

    @property
    def valor_hora_50(self):
        return self.valor_base + self.bonus * Decimal('0.5')

    @property
    def valor_hora_100(self):
        return self.valor_base + self.bonus

    @property
    def e_padrao(self):
        return self.nome.strip().upper() in ('PADRÃO', 'PADRAO')


class EspecialidadeGrupo(models.Model):
    grupo = models.ForeignKey(
        GrupoValor,
        on_delete=models.CASCADE,
        related_name='especialidades',
    )
    nome = models.CharField(max_length=200)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Especialidade do Grupo'
        verbose_name_plural = 'Especialidades dos Grupos'
        unique_together = [('grupo', 'nome')]

    def __str__(self):
        return self.nome


class EspecialidadeConhecida(models.Model):
    nome = models.CharField(max_length=200, unique=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Especialidade Conhecida'
        verbose_name_plural = 'Especialidades Conhecidas'

    def __str__(self):
        return self.nome


class EquipeMedica(models.Model):
    """
    Equipe médica: os repasses dos profissionais da equipe saem em conjunto
    no relatório (faturados em nome de uma empresa).
    """
    nome = models.CharField(max_length=200, unique=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Equipe Médica'
        verbose_name_plural = 'Equipes Médicas'

    def __str__(self):
        return self.nome


class Profissional(models.Model):
    """
    Base de profissionais médicos. Alimentada pela importação da planilha
    de agendas (e manualmente), usada para saber quem já teve repasse no mês.
    """
    nome = models.CharField(max_length=200)
    nome_norm = models.CharField(max_length=200, unique=True, db_index=True)
    ativo = models.BooleanField(default=True)
    equipe = models.ForeignKey(
        EquipeMedica, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='membros',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome_norm']
        verbose_name = 'Profissional'
        verbose_name_plural = 'Profissionais'

    def __str__(self):
        return self.nome


class ConfiguracaoLogin(models.Model):
    usuario_web = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='config_siresp',
        null=True,
        blank=True,
    )
    usuario = models.CharField(max_length=100, blank=True)
    senha = models.CharField(max_length=100, blank=True)
    cpf_primeiros = models.CharField(max_length=10, blank=True)
    cpf_ultimos = models.CharField(max_length=10, blank=True)
    rg_primeiros = models.CharField(max_length=10, blank=True)
    rg_ultimos = models.CharField(max_length=10, blank=True)
    origem = models.CharField(max_length=10, blank=True, default='CRM')

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração de Login SIRESP'
        verbose_name_plural = 'Configurações de Login SIRESP'

    def __str__(self):
        return f"Login SIRESP de {self.usuario_web.username if self.usuario_web else '?'}"

    @classmethod
    def get_para(cls, user):
        obj, _ = cls.objects.get_or_create(usuario_web=user)
        return obj


class RegraMinuto(models.Model):
    """
    Mapeia (profissional, especialidade) → lista de minutos.
    Agora suporta override de valor_base e bonus (opcionais).
    """
    profissional_norm = models.CharField(max_length=200, db_index=True)
    especialidade_norm = models.CharField(max_length=200, db_index=True)
    minutos = models.JSONField(default=list)

    # Overrides opcionais (se null, usa o valor do grupo padrão)
    valor_base_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    bonus_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['profissional_norm', 'especialidade_norm']
        verbose_name = 'Regra de Minuto'
        verbose_name_plural = 'Regras de Minutos'
        unique_together = [('profissional_norm', 'especialidade_norm')]

    def __str__(self):
        return f"{self.profissional_norm} | {self.especialidade_norm} → {self.minutos}"

    @property
    def minutos_formatados(self):
        return ", ".join(str(m) for m in self.minutos)

    @property
    def tem_override(self):
        return self.valor_base_override is not None or self.bonus_override is not None


class SessaoSiresp(models.Model):
    STATUS_CHOICES = [
        ('aguardando', 'Aguardando login'),
        ('logado', 'Logado'),
        ('erro', 'Erro'),
        ('fechada', 'Fechada'),
    ]

    usuario_web = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='sessao_siresp',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='aguardando')
    mensagem = models.TextField(blank=True)
    titulo_janela = models.CharField(max_length=200, blank=True)

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Sessão SIRESP'
        verbose_name_plural = 'Sessões SIRESP'

    def __str__(self):
        return f"Sessão de {self.usuario_web.username} [{self.status}]"

    @property
    def logada(self):
        return self.status == 'logado'


class Extracao(models.Model):
    usuario_web = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='extracoes',
    )
    medico_nome = models.CharField(max_length=200)
    medico_crm = models.CharField(max_length=50, blank=True)
    medico_codigo = models.CharField(max_length=50, blank=True)

    data_ini = models.CharField(max_length=10)
    data_fim = models.CharField(max_length=10)

    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criada_em']
        verbose_name = 'Extração'
        verbose_name_plural = 'Extrações'

    def __str__(self):
        return f"{self.medico_nome} ({self.data_ini} a {self.data_fim})"

    @property
    def total_itens(self):
        return self.itens.count()


class ItemProducao(models.Model):
    extracao = models.ForeignKey(
        Extracao,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    especialidade = models.CharField(max_length=300)
    dados = models.JSONField(default=dict)
    ordem = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordem']
        verbose_name = 'Item de Produção'
        verbose_name_plural = 'Itens de Produção'

    def __str__(self):
        return f"{self.especialidade}"

    def get(self, campo, default=""):
        return self.dados.get(campo, default)


class Repasse(models.Model):
    STATUS_CHOICES = [
        ('rascunho', 'Rascunho'),
        ('finalizado', 'Finalizado'),
    ]

    extracao = models.OneToOneField(
        Extracao,
        on_delete=models.CASCADE,
        related_name='repasse',
    )
    usuario_web = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='repasses',
    )

    valor_total_real = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_total_final = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    horas_total_real = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    horas_total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='rascunho')
    finalizado_em = models.DateTimeField(null=True, blank=True)
    # Mês de competência (1º dia): o mês que está sendo pago. O repasse é
    # feito no mês seguinte (pago em setembro = competência agosto).
    competencia = models.DateField(null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Repasse'
        verbose_name_plural = 'Repasses'

    def __str__(self):
        return f"Repasse de {self.extracao}"

    @property
    def finalizado(self):
        return self.status == 'finalizado'

    @property
    def competencia_fmt(self):
        return self.competencia.strftime('%m/%Y') if self.competencia else ''

    def recalcular_totais(self):
        marcados = self.itens.filter(marcado=True)

        total_hr = Decimal('0')
        total_hf = Decimal('0')
        total_rr = Decimal('0')
        total_rf = Decimal('0')

        for item in marcados:
            total_hr += item.horas_real
            total_hf += item.horas_final
            total_rr += item.total_real
            total_rf += item.total_final

        self.horas_total_real = total_hr
        self.horas_total_final = total_hf
        self.valor_total_real = total_rr
        self.valor_total_final = total_rf
        self.save(update_fields=[
            'horas_total_real', 'horas_total_final',
            'valor_total_real', 'valor_total_final',
            'atualizado_em',
        ])


class ItemRepasse(models.Model):
    BONUS_CHOICES = [
        ('0%', '0%'),
        ('50%', '50%'),
        ('100%', '100%'),
    ]

    repasse = models.ForeignKey(
        Repasse,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    ordem = models.IntegerField(default=0)

    especialidade = models.CharField(max_length=300)
    oferta = models.IntegerField(default=0)
    atendimentos = models.IntegerField(default=0)

    minutos = models.DecimalField(max_digits=8, decimal_places=2, default=15)
    valor_base = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bonus_cheio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bonus_percent = models.CharField(max_length=5, choices=BONUS_CHOICES, default='100%')

    valor_hora = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    horas_real = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    horas_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_real = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_final = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    grupo_nome = models.CharField(max_length=200, blank=True)

    marcado = models.BooleanField(default=False)
    faltou_regra = models.BooleanField(default=False)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ordem', 'id']
        verbose_name = 'Item de Repasse'
        verbose_name_plural = 'Itens de Repasse'

    def __str__(self):
        return f"{self.especialidade}"

    @property
    def bonus_aplicado(self):
        from decimal import Decimal as D
        perc = {
            '0%': D('0'),
            '50%': D('0.5'),
            '100%': D('1'),
        }.get(self.bonus_percent, D('0'))
        return (self.bonus_cheio * perc).quantize(D('0.01'))

    def recalcular(self):
        from decimal import Decimal as D

        self.valor_hora = self.valor_base + self.bonus_aplicado

        minutos = self.minutos or D('0')
        self.horas_real = (D(self.oferta) * minutos / D('60')).quantize(D('0.01'))
        self.horas_final = self.horas_real

        self.total_real = (self.horas_real * self.valor_hora).quantize(D('0.01'))
        self.total_final = self.total_real

    def save(self, *args, **kwargs):
        if not kwargs.get('update_fields'):
            self.recalcular()
        super().save(*args, **kwargs)

class LogAuditoria(models.Model):
    """
    Trilha de auditoria: quem fez o quê, quando e o que mudou.
    Registro apenas de inclusão (não há edição nem exclusão pela aplicação).
    """
    usuario = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='logs_auditoria')
    usuario_nome = models.CharField(max_length=150, blank=True)   # mantém o nome se o usuário for apagado
    acao = models.CharField(max_length=40, db_index=True)
    descricao = models.CharField(max_length=500, blank=True)
    repasse_id = models.IntegerField(null=True, blank=True, db_index=True)
    profissional = models.CharField(max_length=200, blank=True, db_index=True)
    # lista de mudanças: [{"campo": "valor_base", "item": "CARDIOLOGIA", "de": "100.00", "para": "120.00"}]
    detalhes = models.JSONField(default=list, blank=True)
    ip = models.CharField(max_length=45, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-criado_em', '-id']
        verbose_name = 'Log de Auditoria'
        verbose_name_plural = 'Logs de Auditoria'

    def __str__(self):
        return f'{self.criado_em:%d/%m/%Y %H:%M} {self.usuario_nome} {self.acao}'


class SemProducao(models.Model):
    """
    Médico consultado no SIRESP que não teve produção no período.
    Evita que ele volte a aparecer como "pendente" na busca em lote.
    """
    usuario_web = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sem_producao')
    medico_nome = models.CharField(max_length=200)
    nome_norm = models.CharField(max_length=200, db_index=True)
    data_ini = models.CharField(max_length=10)
    data_fim = models.CharField(max_length=10)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Consulta sem produção'
        verbose_name_plural = 'Consultas sem produção'
        unique_together = [('usuario_web', 'nome_norm', 'data_ini', 'data_fim')]

    def __str__(self):
        return f'{self.medico_nome} ({self.data_ini} a {self.data_fim})'
