
Run:
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))




class TestMuniRecord(unittest.TestCase):
    """Test MuniRecord dataclass merge + dict serialization."""

    def test_from_dict_ignores_unknown_keys(self):
        record = MuniRecord.from_dict({
            "cidade": "Goiânia",
            "estado": "GO",
            "unknown_field": "ignored",
            "outro_campo": 123,
        })
        self.assertEqual(record.cidade, "Goiânia")
        self.assertEqual(record.estado, "GO")

    def test_to_dict_only_set(self):
        record = MuniRecord(cidade="X", estado="Y")
        d = record.to_dict(only_set=True)
        self.assertEqual(d["cidade"], "X")
        self.assertEqual(d["estado"], "Y")
        self.assertNotIn("prefeito_nome", d)
        self.assertNotIn("populacao", d)

    def test_merge_prefers_existing(self):
        r1 = MuniRecord(cidade="X", estado="Y", prefeito_nome="João")
        r2 = MuniRecord(cidade="X", estado="Y", prefeito_nome="Maria")
        merged = r1.merge(r2)
        # Should keep "João" because r1 had it set
        self.assertEqual(merged.prefeito_nome, "João")

    def test_merge_fills_none(self):
        r1 = MuniRecord(cidade="X", estado="Y")
        r2 = MuniRecord(cidade="X", estado="Y", prefeito_nome="Maria", populacao=100000)
        merged = r1.merge(r2)
        self.assertEqual(merged.prefeito_nome, "Maria")
        self.assertEqual(merged.populacao, 100000)


class TestIBGEFetcher(unittest.TestCase):
    """Test IBGEFetcher (requires network or cache)."""

    def setUp(self):
        self.cache = MuniCache()
        self.fetcher = IBGEFetcher(cache=self.cache)

    def tearDown(self):
        asyncio.run(self.fetcher.close())

    def test_normalize_cidade(self):
        norm = IBGEFetcher._normalize_cidade
        self.assertEqual(norm("Goiânia"), "goiania")
        self.assertEqual(norm("São Paulo"), "sao paulo")
        self.assertEqual(norm("  TRINDADE  "), "trindade")

    def test_get_ibge_code_goiania(self):
        """Goiânia = IBGE 5208707."""
        async def run():
            code = await self.fetcher.get_ibge_code("Goiânia", "GO")
            self.assertEqual(code, 5208707)
        asyncio.run(run())

    def test_enrich_full(self):
        """Enrich MuniRecord for Goiânia — pop and pib should be set."""
        async def run():
            r = MuniRecord(cidade="Goiânia", estado="GO", uf="GO")
            r = await self.fetcher.enrich(r)
            self.assertEqual(r.ibge_code, 5208707)
            self.assertGreater(r.populacao, 1_000_000)  # > 1M
            self.assertGreater(r.pib_per_capita, 30_000)  # > R$30k
        asyncio.run(run())


class TestTSEFetcher(unittest.TestCase):
    """Test TSEFetcher (uses cached ZIP if present)."""

    @classmethod
    def setUpClass(cls):
        cls.zip_path = os.path.join("data", "cache", "tse_raw", "consulta_cand_2024.zip")
        if not os.path.exists(cls.zip_path):
            raise unittest.SkipTest(f"TSE ZIP not cached at {cls.zip_path}; "
                                   f"run test manually after download")

    def setUp(self):
        self.cache = MuniCache()
        self.fetcher = TSEFetcher(cache=self.cache, ano_eleicao=2024)

    def tearDown(self):
        asyncio.run(self.fetcher.close())

    def test_normalize_cidade(self):
        norm = TSEFetcher._normalize_cidade
        self.assertEqual(norm("Goiânia"), "goiania")
        self.assertEqual(norm("São Paulo"), "sao paulo")

    def test_get_prefeitos_eleitos(self):
        async def run():
            prefeitos = await self.fetcher.get_prefeitos_eleitos()
            self.assertGreater(len(prefeitos), 5000)  # Brasil tem ~5570 prefeitos
            # Amostra válida
            p = prefeitos[0]
            self.assertIn("cidade", p)
            self.assertIn("uf", p)
            self.assertIn("nome", p)
        asyncio.run(run())

    def test_find_prefeito_capital(self):
        async def run():
            p = await self.fetcher.find_prefeito("São Paulo", "SP")
            self.assertIsNotNone(p)
            self.assertEqual(p["uf"], "SP")
            self.assertIn("nome", p)
        asyncio.run(run())

    def test_find_prefeito_partial_match(self):
        async def run():
            # "São Paulo" deve matchar com "SÃO PAULO" no TSE
            p = await self.fetcher.find_prefeito("São Paulo", "SP")
            self.assertIsNotNone(p)
        asyncio.run(run())

    def test_enrich_goiania(self):
        async def run():
            r = MuniRecord(cidade="Goiânia", estado="GO", uf="GO")
            r = await self.fetcher.enrich(r)
            self.assertIsNotNone(r.prefeito_nome)
            self.assertEqual(r.prefeito_eleito_ano, 2024)
            self.assertEqual(r.prefeito_fonte, "tse")
        asyncio.run(run())


class TestMuniDiscovery(unittest.TestCase):
    """Test orchestrator end-to-end."""

    def setUp(self):
        self.discovery = MuniDiscovery()

    def tearDown(self):
        asyncio.run(self.discovery.close())

    def test_discover_one_complete(self):
        async def run():
            r = await self.discovery.discover_one("Goiânia", "GO")
            self.assertEqual(r.discovery_status, "complete")
            self.assertEqual(r.ibge_code, 5208707)
            self.assertGreater(r.populacao, 1_000_000)
            self.assertIsNotNone(r.prefeito_nome)
        asyncio.run(run())

    def test_discover_batch_parallel(self):
        async def run():
            cidades = [
                ("Goiânia", "GO"),
                ("São Paulo", "SP"),
                ("Rio de Janeiro", "RJ"),
            ]
            records = await self.discovery.discover_batch(cidades)
            self.assertEqual(len(records), 3)
            for r in records:
                self.assertEqual(r.discovery_status, "complete")
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
