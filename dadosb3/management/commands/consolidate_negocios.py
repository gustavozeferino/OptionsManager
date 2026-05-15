from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from dadosb3.models import CotacaoHistorica, BoletimNegocioDiario, NegocioDiario, Instrumento

def safe_div(a, b):
    if a is not None and b is not None and b > 0:
        return Decimal(a) / Decimal(b)
    return None

def normalize_segmento(codbdi, tpmerc):
    codbdi = str(codbdi).strip() if codbdi else ""
    tpmerc = str(tpmerc).strip() if tpmerc else ""

    if codbdi == "78" or tpmerc == "070":
        return "EQUITY CALL"
    if codbdi == "82" or tpmerc == "080":
        return "EQUITY PUT"
    if codbdi in ["02", "12"] or tpmerc == "010":
        return "CASH"
    if codbdi == "96" or tpmerc == "020":
        return "MERCADO FRACIONARIO"
    return "OUTROS"

class Command(BaseCommand):
    help = 'Consolida dados de CotacaoHistorica e BoletimNegocioDiario em NegocioDiario (Golden Source)'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Data para consolidacao (YYYY-MM-DD)', required=False)
        parser.add_argument('--all', action='store_true', help='Consolidar todo o historico', required=False)

    def handle(self, *args, **options):
        target_date_str = options['date']
        do_all = options['all']

        if not target_date_str and not do_all:
            self.stdout.write(self.style.ERROR('Forneca --date YYYY-MM-DD ou --all'))
            return

        dates_to_process = []
        if target_date_str:
            dates_to_process.append(datetime.strptime(target_date_str, '%Y-%m-%d').date())
        else:
            dates_cothist = set(CotacaoHistorica.objects.values_list('dtpreg', flat=True).distinct())
            dates_boletim = set(BoletimNegocioDiario.objects.values_list('data_pregao', flat=True).distinct())
            dates_to_process = sorted(list(dates_cothist | dates_boletim))

        # Pre-carrega o mapa de ticker -> isin da tabela Instrumento (fora do loop de datas para performance)
        mapa_isin_por_ticker = dict(Instrumento.objects.values_list('ticker', 'isin'))
        self.stdout.write(f'Mapa Instrumento carregado: {len(mapa_isin_por_ticker)} entradas.')

        for dt in dates_to_process:
            self.stdout.write(f'Consolidando data {dt}...')

            # Carrega registros ja existentes na Golden Source indexados por isin
            golden_map = {}
            for e in NegocioDiario.objects.filter(data_pregao=dt):
                golden_map[e.isin] = e

            # Passo 1: CotacaoHistorica
            # O ISIN e obtido via tabela Instrumento (match CODNEG <-> ticker).
            # Fallback: usa o codisi da propria linha caso o ticker nao esteja no Instrumento.
            for c in CotacaoHistorica.objects.filter(dtpreg=dt):
                isin = mapa_isin_por_ticker.get(c.codneg) or c.codisi
                if not isin:
                    continue

                if isin not in golden_map:
                    golden_map[isin] = NegocioDiario(
                        data_pregao=c.dtpreg,
                        ticker=c.codneg,
                        isin=isin,
                        preco_abertura=c.preabe,
                        preco_minimo=c.premin,
                        preco_maximo=c.premax,
                        preco_fechamento=c.preult,
                        preco_vwap=safe_div(c.voltot, c.quatot),
                        qtd_negocios=c.totneg,
                        qtd_contratos=c.quatot,
                        volume_financeiro=c.voltot,
                        segmento=normalize_segmento(c.codbdi, c.tpmerc)
                    )
                else:
                    g = golden_map[isin]
                    if not g.preco_abertura:    g.preco_abertura    = c.preabe
                    if not g.preco_minimo:      g.preco_minimo      = c.premin
                    if not g.preco_maximo:      g.preco_maximo      = c.premax
                    if not g.preco_fechamento:  g.preco_fechamento  = c.preult
                    if not g.preco_vwap:        g.preco_vwap        = safe_div(c.voltot, c.quatot)
                    if not g.qtd_negocios:      g.qtd_negocios      = c.totneg
                    if not g.qtd_contratos:     g.qtd_contratos     = c.quatot
                    if not g.volume_financeiro: g.volume_financeiro = c.voltot
                    if not g.segmento or g.segmento == "OUTROS":
                        g.segmento = normalize_segmento(c.codbdi, c.tpmerc)

            # Passo 2: BoletimNegocioDiario
            # O isin ja esta disponivel diretamente no Boletim.
            for b in BoletimNegocioDiario.objects.filter(data_pregao=dt):
                if b.isin not in golden_map:
                    golden_map[b.isin] = NegocioDiario(
                        data_pregao=b.data_pregao,
                        ticker=b.ticker,
                        isin=b.isin,
                        preco_abertura=b.preco_abertura,
                        preco_minimo=b.preco_minimo,
                        preco_maximo=b.preco_maximo,
                        preco_fechamento=b.preco_fechamento,
                        preco_vwap=safe_div(b.volume_financeiro, b.qtd_contratos),
                        qtd_negocios=b.qtd_negocios,
                        qtd_contratos=b.qtd_contratos,
                        volume_financeiro=b.volume_financeiro,
                        segmento=b.segmento if b.segmento else "OUTROS"
                    )
                else:
                    g = golden_map[b.isin]
                    if not g.preco_abertura:    g.preco_abertura    = b.preco_abertura
                    if not g.preco_minimo:      g.preco_minimo      = b.preco_minimo
                    if not g.preco_maximo:      g.preco_maximo      = b.preco_maximo
                    if not g.preco_fechamento:  g.preco_fechamento  = b.preco_fechamento
                    if not g.preco_vwap:        g.preco_vwap        = safe_div(b.volume_financeiro, b.qtd_contratos)
                    if not g.qtd_negocios:      g.qtd_negocios      = b.qtd_negocios
                    if not g.qtd_contratos:     g.qtd_contratos     = b.qtd_contratos
                    if not g.volume_financeiro: g.volume_financeiro = b.volume_financeiro
                    if not g.segmento or g.segmento == "OUTROS":
                        g.segmento = b.segmento if b.segmento else "OUTROS"

            # Salvar em lote
            to_create = [v for v in golden_map.values() if not v.pk]
            to_update = [v for v in golden_map.values() if v.pk]

            if to_create:
                NegocioDiario.objects.bulk_create(to_create, ignore_conflicts=True)
            if to_update:
                NegocioDiario.objects.bulk_update(to_update, [
                    'preco_abertura', 'preco_minimo', 'preco_maximo', 'preco_fechamento',
                    'preco_vwap', 'qtd_negocios', 'qtd_contratos', 'volume_financeiro', 'segmento'
                ])

            self.stdout.write(self.style.SUCCESS(
                f'Data {dt}: {len(to_create)} inseridos, {len(to_update)} atualizados.'
            ))

        self.stdout.write(self.style.SUCCESS('Consolidacao concluida!'))
