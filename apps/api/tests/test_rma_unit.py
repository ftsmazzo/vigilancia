"""Testes unitários RMA (sem banco)."""

from __future__ import annotations

import unittest

from app.vigilance.rma_catalogo import is_psr_indicador_creas
from app.vigilance.rma_equipamento import (
    CENTRO_POP_ID_OFICIAL,
    infer_tipo_equipamento,
    parse_cras_num_territorial,
    resolve_cras_num_territorial,
)


class TestRmaEquipamento(unittest.TestCase):
    def test_cras_bonfim_id_override(self):
        self.assertEqual(
            resolve_cras_num_territorial(
                id_equipamento="35434039977",
                nome_unidade="CRAS Bonfim - Centro de referência",
            ),
            9,
        )

    def test_cras_num_from_nome(self):
        self.assertEqual(parse_cras_num_territorial("CRAS 3 - Centro"), 3)

    def test_centro_pop_tipo(self):
        self.assertEqual(
            infer_tipo_equipamento(
                id_equipamento=CENTRO_POP_ID_OFICIAL,
                tipo_formulario="CREAS",
                nome_unidade="CREAS POP",
            ),
            "CENTRO_POP",
        )

    def test_psr_indicadores_creas(self):
        self.assertTrue(is_psr_indicador_creas("k1"))
        self.assertTrue(is_psr_indicador_creas("k1a"))
        self.assertTrue(is_psr_indicador_creas("l1"))
        self.assertFalse(is_psr_indicador_creas("m1"))
        self.assertFalse(is_psr_indicador_creas("a1"))


if __name__ == "__main__":
    unittest.main()
