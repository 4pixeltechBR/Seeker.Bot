"""Tests for custom_extension module (Phase 5.4)."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


    EmailValidator,
    has_mx_or_a,
    is_valid_email_format,
)
    EmailCandidate,
    EnrichmentReport,
    SECRETARIAS_KEYWORDS,
    ValidatedEmail,
)
    CITY_SHORT_SLUG,
    suggest_all_emails,
    suggest_domains,
    suggest_emails_for_secretaria,
    suggest_prefeito_email,
)


class TestEmailValidator(unittest.TestCase):
    def test_is_valid_email_format(self):
        self.assertTrue(is_valid_email_format("cultura@goiania.go.gov.br"))
        self.assertTrue(is_valid_email_format("user.name@subdomain.example.com"))
        self.assertFalse(is_valid_email_format("UPPERCASE@test.com"))
        self.assertFalse(is_valid_email_format("invalid"))
        self.assertFalse(is_valid_email_format("@nodomain.com"))
        self.assertFalse(is_valid_email_format("nodot@domain"))
        self.assertFalse(is_valid_email_format("test@mailinator.com"))  # disposable

    def test_has_mx_or_a_real_domain(self):
        async def run():
            ok, _ = await has_mx_or_a("google.com")
            self.assertTrue(ok)
        asyncio.run(run())

    def test_has_mx_or_a_nonexistent(self):
        async def run():
            ok, _ = await has_mx_or_a("this-domain-truly-does-not-exist-xyzabc.com")
            self.assertFalse(ok)
        asyncio.run(run())


class TestPatternMatcher(unittest.TestCase):
    def test_normalize_short_slug_present(self):
        """Short slugs devem estar disponíveis para cidades grandes."""
        self.assertIn("riodejaneiro", CITY_SHORT_SLUG)
        self.assertIn("saopaulo", CITY_SHORT_SLUG)

    def test_suggest_domains_goiania(self):
        domains = suggest_domains("Goiânia", "GO")
        self.assertIn("goiania.go.gov.br", domains)

    def test_suggest_domains_rio(self):
        domains = suggest_domains("Rio de Janeiro", "RJ")
        self.assertIn("rio.rj.gov.br", domains)
        self.assertIn("riodejaneiro.rj.gov.br", domains)

    def test_suggest_domains_sao_paulo(self):
        domains = suggest_domains("São Paulo", "SP")
        self.assertIn("saopaulo.sp.gov.br", domains)
        self.assertIn("prefeitura.sp.gov.br", domains)

    def test_suggest_emails_for_secretaria(self):
        emails = suggest_emails_for_secretaria("cultura", "goiania.go.gov.br")
        self.assertIn("cultura@goiania.go.gov.br", emails)
        self.assertIn("secretaria.cultura@goiania.go.gov.br", emails)

    def test_suggest_all_emails_keys(self):
        result = suggest_all_emails("Petrolina", "PE")
        for key in ["domain_candidates", "cultura", "turismo", "licitacao", "gabinete"]:
            self.assertIn(key, result)

    def test_suggest_prefeito_email(self):
        emails = suggest_prefeito_email("MABEL CORREA FERREIRA", "goiania.go.gov.br")
        self.assertIn("mabel.ferreira@goiania.go.gov.br", emails)
        self.assertIn("prefeito@goiania.go.gov.br", emails)


class TestFitScorer(unittest.TestCase):
    def test_min_score_threshold_returns_30(self):
        # Threshold documentado: 30
        self.assertGreaterEqual(get_min_score_threshold(), 30)

    def test_capital_full_signals_high_score(self):
        """São Paulo score deve ser alto."""
        score, signals = calculate_fit_score(
            populacao=11451999,
            pib_per_capita=72000,
            tem_secretaria_cultura=True,
            tem_secretaria_turismo=True,
            tem_licitacao_email=True,
            tem_portal_transparencia=True,
            eventos_recentes=5,
            tem_prefeito_email=False,
        )
        self.assertGreaterEqual(score, 80)

    def test_tiny_city_low_score(self):
        """Município 10k habitantes sem cultura deve ter score baixo."""
        score, signals = calculate_fit_score(
            populacao=10000,
            pib_per_capita=15000,
            tem_secretaria_cultura=False,
            tem_secretaria_turismo=False,
            tem_licitacao_email=False,
            tem_portal_transparencia=False,
            eventos_recentes=0,
            tem_prefeito_email=False,
        )
        self.assertLess(score, 30)

    def test_just_population_signal(self):
        """População sozinha deve dar 30 (para >500k)."""
        score, signals = calculate_fit_score(populacao=600000)
        self.assertGreaterEqual(score, 30)
        self.assertIn("populacao_gt_500k", signals)

    def test_score_capped_at_100(self):
        """Mesmo com todos os sinais, score não deve passar 100."""
        score, _ = calculate_fit_score(
            populacao=2000000,
            pib_per_capita=100000,
            tem_secretaria_cultura=True,
            tem_secretaria_turismo=True,
            tem_licitacao_email=True,
            tem_portal_transparencia=True,
            eventos_recentes=10,
            tem_prefeito_email=True,
        )
        self.assertLessEqual(score, 100)


class TestEnrichmentReport(unittest.TestCase):
    def test_report_init(self):
        report = EnrichmentReport(cidade="X", estado="Y")
        self.assertEqual(report.cidade, "X")
        self.assertEqual(report.validated_count, 0)
        self.assertFalse(report.has_cultura)

    def test_has_cultura_true(self):
        report = EnrichmentReport(cidade="X", estado="Y")
        report.validated_emails.append(
            ValidatedEmail(email="cultura@x.gov.br", secretaria="cultura", source="pattern", confidence=0.7)
        )
        self.assertTrue(report.has_cultura)

    def test_best_email_for(self):
        report = EnrichmentReport(cidade="X", estado="Y")
        report.validated_emails.append(
            ValidatedEmail(email="cultura@x.gov.br", secretaria="cultura", source="pattern", confidence=0.5)
        )
        report.validated_emails.append(
            ValidatedEmail(email="secretaria.cultura@x.gov.br", secretaria="cultura", source="pattern", confidence=0.7)
        )
        best = report.best_email_for("cultura")
        self.assertEqual(best.confidence, 0.7)


class TestEmailValidatorBatch(unittest.TestCase):
    def test_validate_batch(self):
        async def run():
            v = EmailValidator(do_smtp_verify=False)
            emails = ["valid@gmail.com", "invalid_format", "@invalid.com"]
            results = await v.validate_batch(emails)
            self.assertEqual(len(results), 3)
            # gmail tem MX, os outros não
            self.assertEqual(results[0][1], True)  # formato ok
            self.assertEqual(results[0][2], True)  # mx ok
        asyncio.run(run())


class TestSecretariasKeywords(unittest.TestCase):
    def test_all_secretarias_present(self):
        expected = ["cultura", "turismo", "educacao", "esporte", "saude",
                    "licitacao", "gabinete", "comunicacao"]
        for s in expected:
            self.assertIn(s, SECRETARIAS_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
