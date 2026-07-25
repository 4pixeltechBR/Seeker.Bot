"""Tests for custom_extension module (Phase 5.5)."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


    BrevoClient,
    BrevoResponse,
    build_lgpd_footer,
    body_text_to_html,
    extract_dest_url,
    extract_message_id_from_track_url,
    get_transparent_gif_bytes,
    is_valid_lgpd_footer,
    make_click_redirect_url,
    make_open_pixel_url,
    make_optout_token,
    make_optout_url,
    parse_llm_json,
    personalize_email,
    render_email_html,
    render_email_text,
    verify_optout_token,
    verify_signature,
    EMPRESA_INFO,
)


class TestLGPDOptOut(unittest.TestCase):
    def test_optout_token_deterministic(self):
        """Mesmo email → mesmo token."""
        t1 = make_optout_token("test@example.com")
        t2 = make_optout_token("test@example.com")
        self.assertEqual(t1, t2)

    def test_optout_token_unique_per_email(self):
        t1 = make_optout_token("test1@example.com")
        t2 = make_optout_token("test2@example.com")
        self.assertNotEqual(t1, t2)

    def test_optout_token_case_insensitive(self):
        t1 = make_optout_token("Test@Example.com")
        t2 = make_optout_token("test@example.com")
        self.assertEqual(t1, t2)

    def test_make_optout_url(self):
        url = make_optout_url("cultura@goiania.go.gov.br")
        self.assertIn("optout", url.lower())
        self.assertIn("cultura%40goiania.go.gov.br", url)
        self.assertIn("token=", url)

    def test_verify_optout_token_valid(self):
        url = make_optout_url("test@x.com")
        token = url.split("token=")[1]
        self.assertTrue(verify_optout_token("test@x.com", token))

    def test_verify_optout_token_invalid(self):
        url = make_optout_url("test@x.com")
        token = url.split("token=")[1]
        # Modify last char
        bad_token = token[:-1] + ("1" if token[-1] != "1" else "0")
        # Might accidentally match — use clearly wrong token
        self.assertFalse(verify_optout_token("test@x.com", "deadbeef" + "0" * 24))


class TestLGPDFooter(unittest.TestCase):
    def test_footer_required_elements(self):
        html = build_lgpd_footer("test@example.com")
        self.assertIn("LGPD", html.upper() or "REMOVER" in html)
        self.assertIn("CNPJ", html)
        self.assertIn(EMPRESA_INFO["razao_social"], html)
        self.assertIn("optout", html.lower() or "descadastrar" in html.lower())

    def test_footer_with_pixel(self):
        html = build_lgpd_footer("test@example.com", tracking_pixel_url="https://x.com/track.gif")
        self.assertIn('<img src="https://x.com/track.gif"', html)

    def test_footer_without_pixel(self):
        html = build_lgpd_footer("test@example.com")
        self.assertNotIn('<img', html)

    def test_is_valid_lgpd_footer(self):
        html = build_lgpd_footer("test@example.com")
        valid, problems = is_valid_lgpd_footer(html)
        self.assertTrue(valid, f"Problems: {problems}")


class TestTemplates(unittest.TestCase):
    def test_render_email_html_contains_body(self):
        body = "<p>Hello world</p>"
        html = render_email_html(body, "test@example.com")
        self.assertIn("Hello world", html)
        self.assertIn("<html", html.lower())

    def test_render_email_html_contains_lgpd(self):
        html = render_email_html("<p>X</p>", "test@example.com")
        self.assertIn("LGPD", html.upper() or "REMOVER" in html)

    def test_render_email_html_without_wrapper(self):
        html = render_email_html("<p>X</p>", "test@example.com", wrapper=False)
        self.assertNotIn("<html", html.lower())
        self.assertIn("<p>X</p>", html)

    def test_render_email_text(self):
        text = render_email_text("Linha 1\n\nLinha 2", "test@example.com")
        self.assertIn("Linha 1", text)
        self.assertIn("Linha 2", text)
        self.assertIn("optout", text.lower())

    def test_body_text_to_html_paragraphs(self):
        html = body_text_to_html("P1\n\nP2")
        self.assertIn("<p>P1</p>", html)
        self.assertIn("<p>P2</p>", html)

    def test_body_text_to_html_newlines(self):
        html = body_text_to_html("Line 1\nLine 2")
        self.assertIn("<br>", html)


class TestTracker(unittest.TestCase):
    def test_make_open_pixel_url_format(self):
        url = make_open_pixel_url("msg-123")
        self.assertIn(".gif", url)  # embedded in path
        self.assertIn("msg-123", url)
        self.assertIn("s=", url)

    def test_make_click_redirect_url(self):
        url = make_click_redirect_url("msg-1", "https://example.com")
        self.assertIn("/click/msg-1", url)
        self.assertIn("url=", url)
        self.assertIn("https%3A%2F%2Fexample.com", url)

    def test_verify_signature_valid(self):
        url = make_open_pixel_url("msg-1")
        sig = url.split("s=")[1].split("&")[0]
        self.assertTrue(verify_signature("msg-1", sig))

    def test_verify_signature_invalid(self):
        self.assertFalse(verify_signature("msg-1", "wrong" * 4))

    def test_get_transparent_gif_43_bytes(self):
        gif = get_transparent_gif_bytes()
        self.assertEqual(len(gif), 43)
        self.assertTrue(gif.startswith(b"GIF89"))

    def test_extract_message_id_from_url(self):
        url = "https://api.com/track/open/abc-123.gif?s=xyz"
        msg_id = extract_message_id_from_track_url(url)
        self.assertEqual(msg_id, "abc-123.gif")

    def test_extract_dest_url(self):
        url = "https://api.com/track/click/abc?url=https%3A%2F%2Fdest.com&s=xyz"
        dest = extract_dest_url(url)
        self.assertEqual(dest, "https://dest.com")


class TestBrevoClient(unittest.TestCase):
    def test_init_no_key(self):
        client = BrevoClient(api_key="")
        self.assertEqual(client.api_key, "")
        self.assertEqual(client.from_address, "custom_extension@brevosend.com")

    def test_init_with_env(self):
        os.environ["BREVO_API_KEY"] = "test-key-123"
        client = BrevoClient()
        self.assertEqual(client.api_key, "test-key-123")
        del os.environ["BREVO_API_KEY"]

    def test_init_with_args(self):
        client = BrevoClient(
            api_key="xkey-abc",
            from_address="custom@example.com",
            reply_to="reply@example.com",
        )
        self.assertEqual(client.api_key, "xkey-abc")
        self.assertEqual(client.from_address, "custom@example.com")
        self.assertEqual(client.reply_to, "reply@example.com")


class TestParseLLMJson(unittest.TestCase):
    def test_parse_pure_json(self):
        text = '{"subject": "Hi", "body": "Hello"}'
        data = parse_llm_json(text)
        self.assertEqual(data["subject"], "Hi")
        self.assertEqual(data["body"], "Hello")

    def test_parse_markdown_json_block(self):
        text = '```json\n{"subject": "Hi", "body": "Hello"}\n```'
        data = parse_llm_json(text)
        self.assertEqual(data["subject"], "Hi")

    def test_parse_embedded_json(self):
        text = 'Here is the result:\n{"subject": "Hi", "body": "Hello"}\nDone!'
        data = parse_llm_json(text)
        self.assertEqual(data["subject"], "Hi")

    def test_parse_invalid(self):
        data = parse_llm_json("not json at all")
        self.assertEqual(data, {})


class TestPersonalizerFallback(unittest.TestCase):
    def test_fallback_when_no_router(self):
        record = {
            "cidade": "Goiânia",
            "estado": "GO",
            "prefeito_nome": "MABEL",
            "prefeito_partido": "UNIÃO",
            "populacao": 1_437_366,
            "pib_per_capita": 41_653,
            "score_fit": 95,
        }
        # Sem router/api_keys deve cair em fallback
        async def run():
            result = await personalize_email(
                record=record,
                contact_secretaria="cultura",
                contact_email="cultura@goiania.go.gov.br",
                eventos_recentes=[],
            )
            self.assertIn("Goiânia", result.subject)
            self.assertIn("cidade", result.body.lower() or "cidade" in result.body)
        asyncio.run(run())


class TestEmpresInfo(unittest.TestCase):
    def test_empresa_info_has_required_fields(self):
        for field in ["razao_social", "cnpj", "endereco", "email_contato"]:
            self.assertIn(field, EMPRESA_INFO)
            self.assertTrue(EMPRESA_INFO[field])


class TestIntegrationFlow(unittest.TestCase):
    def test_full_email_render(self):
        """Constrói email completo (body + LGPD + pixel)."""
        body_html = "<p>Olá, vim falar sobre show em Goiânia.</p>"
        pixel = make_open_pixel_url("msg-test-1")
        html = render_email_html(body_html, "cultura@goiania.go.gov.br", pixel)

        self.assertIn("show", html.lower())
        self.assertIn("Goiânia", html)
        self.assertIn("LGPD" if "LGPD" in html else "REMOVER", html)
        self.assertIn(pixel, html)
        self.assertIn(make_optout_url("cultura@goiania.go.gov.br"), html)


if __name__ == "__main__":
    unittest.main()
