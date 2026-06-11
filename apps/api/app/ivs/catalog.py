"""Catálogo de dimensões e indicadores IVS (IVCAD v1.0.5) para painéis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicadorMeta:
    col: str
    codigo: str
    titulo: str


@dataclass(frozen=True)
class DimensaoMeta:
    sigla: str
    nome: str
    idx_col: str
    indicadores: tuple[IndicadorMeta, ...]


DIMENSOES: tuple[DimensaoMeta, ...] = (
    DimensaoMeta(
        "NC",
        "Necessidade de Cuidados",
        "idx_nc",
        (
            IndicadorMeta("nc1", "NC1", "Criança 0–3 anos"),
            IndicadorMeta("nc2", "NC2", "Criança 0–6 anos"),
            IndicadorMeta("nc3", "NC3", "Criança 0–12 anos"),
            IndicadorMeta("nc4", "NC4", "Pessoa com deficiência"),
            IndicadorMeta("nc5", "NC5", "Pessoa 60 anos ou mais"),
            IndicadorMeta("nc6", "NC6", "Poucos adultos na família"),
            IndicadorMeta("nc7", "NC7", "Dependente e poucas mulheres adultas"),
        ),
    ),
    DimensaoMeta(
        "DPI",
        "Desenvolvimento na Primeira Infância",
        "idx_dpi",
        (
            IndicadorMeta("dpi1", "DPI1", "4–6 anos fora da escola"),
            IndicadorMeta("dpi2", "DPI2", "0–6 anos fora da escola"),
            IndicadorMeta("dpi3", "DPI3", "0–6 anos — parentesco fora filho/enteado"),
        ),
    ),
    DimensaoMeta(
        "DCA",
        "Desenvolvimento de Crianças e Adolescentes",
        "idx_dca",
        (
            IndicadorMeta("dca1", "DCA1", "Trabalho infantil"),
            IndicadorMeta("dca2", "DCA2", "15–17 anos fora da escola"),
            IndicadorMeta("dca3", "DCA3", "7–17 anos fora da escola"),
            IndicadorMeta("dca4", "DCA4", "10–17 anos — analfabeto"),
            IndicadorMeta("dca5", "DCA5", "10–17 anos — defasagem escolar"),
        ),
    ),
    DimensaoMeta(
        "TQA",
        "Trabalho e Qualificação de Adultos",
        "idx_tqa",
        (
            IndicadorMeta("tqa1", "TQA1", "Adulto analfabeto ou ≤ 3 anos estudo"),
            IndicadorMeta("tqa2", "TQA2", "Adulto com menos de 8 anos estudo"),
            IndicadorMeta("tqa3", "TQA3", "Adulto com menos de 11 anos estudo"),
            IndicadorMeta("tqa4", "TQA4", "Nenhum adulto ocupado"),
            IndicadorMeta("tqa5", "TQA5", "Nenhum adulto ocupado formal"),
            IndicadorMeta("tqa6", "TQA6", "Nenhum ocupado com renda ≥ 1 SM"),
            IndicadorMeta("tqa7", "TQA7", "Nenhum ocupado com renda ≥ 2 SM"),
        ),
    ),
    DimensaoMeta(
        "DR",
        "Disponibilidade de Recursos",
        "idx_dr",
        (
            IndicadorMeta("dr1", "DR1", "Família sem renda"),
            IndicadorMeta("dr2", "DR2", "Pobreza incluindo PBF"),
            IndicadorMeta("dr3", "DR3", "Pobreza extrema (CADU)"),
            IndicadorMeta("dr4", "DR4", "Pobreza extrema descontando BPC"),
        ),
    ),
    DimensaoMeta(
        "CH",
        "Condições Habitacionais",
        "idx_ch",
        (
            IndicadorMeta("ch1", "CH1", "Moradia improvisada ou situação de rua"),
            IndicadorMeta("ch2", "CH2", "Densidade > 3 pessoas/dormitório"),
            IndicadorMeta("ch3", "CH3", "Aluguel > 30% da renda"),
            IndicadorMeta("ch4", "CH4", "Despesa com aluguel"),
            IndicadorMeta("ch5", "CH5", "Sem parede e piso permanentes"),
            IndicadorMeta("ch6", "CH6", "Sem parede ou piso permanente"),
            IndicadorMeta("ch7", "CH7", "Sem água de rede geral"),
            IndicadorMeta("ch8", "CH8", "Sem acesso adequado à água"),
            IndicadorMeta("ch9", "CH9", "Sem banheiro"),
            IndicadorMeta("ch10", "CH10", "Esgotamento inadequado"),
            IndicadorMeta("ch11", "CH11", "Lixo não coletado diretamente"),
            IndicadorMeta("ch12", "CH12", "Lixo não coletado direta/indireta"),
            IndicadorMeta("ch13", "CH13", "Sem eletricidade com medidor"),
            IndicadorMeta("ch14", "CH14", "Sem eletricidade"),
        ),
    ),
)

DIM_POR_SIGLA = {d.sigla: d for d in DIMENSOES}
