import tempfile
import unittest
import sys
import os
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.skills.event_radar.goal import report_state_names


class TestReportStateNames(unittest.TestCase):
    def test_detects_mapped_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Radar_Eventos_Goiás.csv").touch()
            (d / "Radar_Eventos_Rio_Grande_do_Sul.csv").touch()
            (d / "outro.csv").touch()  # ruído — não deve aparecer
            result = report_state_names(d)
        self.assertEqual(result, ["Goiás", "Rio Grande do Sul"])

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = report_state_names(Path(tmp))
        self.assertEqual(result, [])

    def test_underscores_converted_to_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Radar_Eventos_Mato_Grosso_do_Sul.csv").touch()
            result = report_state_names(d)
        self.assertEqual(result, ["Mato Grosso do Sul"])

    def test_sorted_alphabetically(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Radar_Eventos_São_Paulo.csv").touch()
            (d / "Radar_Eventos_Acre.csv").touch()
            (d / "Radar_Eventos_Bahia.csv").touch()
            result = report_state_names(d)
        self.assertEqual(result, ["Acre", "Bahia", "São Paulo"])


if __name__ == "__main__":
    unittest.main()
