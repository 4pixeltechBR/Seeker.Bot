import unittest
import sys
import os

# Adiciona o diretório raiz ao path para podermos importar src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.channels.telegram.formatter import strip_reasoning_tags, md_to_telegram_html


class TestThinkScrubber(unittest.TestCase):
    def test_strip_closed_think_tag(self):
        text = "<think>raciocínio secreto</think>Resposta final para o usuário."
        expected = "Resposta final para o usuário."
        self.assertEqual(strip_reasoning_tags(text), expected)

    def test_strip_unclosed_think_tag(self):
        text = "<think>raciocínio que foi cortado antes de terminar"
        expected = ""
        self.assertEqual(strip_reasoning_tags(text), expected)

    def test_strip_closed_thought_tag(self):
        text = "<thought>raciocínio de gemma</thought>Aqui está a resposta."
        expected = "Aqui está a resposta."
        self.assertEqual(strip_reasoning_tags(text), expected)

    def test_strip_unclosed_thought_tag(self):
        text = "<thought>raciocínio truncado"
        expected = ""
        self.assertEqual(strip_reasoning_tags(text), expected)

    def test_strip_tool_calls_xml(self):
        text = "<tool_call>{\"name\": \"web_search\"}</tool_call>Resposta após a ferramenta."
        expected = "Resposta após a ferramenta."
        self.assertEqual(strip_reasoning_tags(text), expected)

    def test_strip_function_definition_xml(self):
        text = "<function name=\"web_search\">query</function>Texto real."
        expected = "Texto real."
        self.assertEqual(strip_reasoning_tags(text), expected)

    def test_mixed_tags_and_markdown(self):
        text = "<think>\nThinking step...\n</think>**Negrito** fora da tag."
        expected = "<b>Negrito</b> fora da tag."
        self.assertEqual(md_to_telegram_html(text), expected)

    def test_stray_close_tags(self):
        text = "</think>Algum texto avulso."
        expected = "Algum texto avulso."
        self.assertEqual(strip_reasoning_tags(text), expected)


if __name__ == "__main__":
    unittest.main()
