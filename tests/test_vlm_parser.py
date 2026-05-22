import unittest
from src.skills.vision.vlm_client import _parse_bbox_response

class TestVLMParser(unittest.TestCase):
    def test_json_point_2d(self):
        raw = '{"point_2d": [500, 600]}'
        res = _parse_bbox_response(raw, width=1920, height=1080)
        # 500/1000 * 1920 = 960
        # 600/1000 * 1080 = 648
        self.assertAlmostEqual(res["x"], 960)
        self.assertAlmostEqual(res["y"], 648)

    def test_json_bbox_2d(self):
        raw = '{"bbox_2d": [100, 200, 300, 400]}'
        res = _parse_bbox_response(raw, width=1000, height=1000)
        # center x = (100+300)/2 = 200
        # center y = (200+400)/2 = 300
        self.assertAlmostEqual(res["x"], 200)
        self.assertAlmostEqual(res["y"], 300)

    def test_qwen_point_tag(self):
        raw = "<|point_start|>(300,700)<|point_end|>"
        res = _parse_bbox_response(raw, width=1920, height=1080)
        # Qwen tag is (y, x) -> (300, 700) -> x=700, y=300
        # x = 700/1000 * 1920 = 1344
        # y = 300/1000 * 1080 = 324
        self.assertAlmostEqual(res["x"], 1344)
        self.assertAlmostEqual(res["y"], 324)

    def test_qwen_box_tag(self):
        raw = "<|box_start|>(100,200,300,400)<|box_end|>"
        res = _parse_bbox_response(raw, width=1000, height=1000)
        # Qwen box is (y1, x1, y2, x2) -> y_center=200, x_center=300
        self.assertAlmostEqual(res["x"], 300)
        self.assertAlmostEqual(res["y"], 200)

    def test_uitars_generic(self):
        raw = "click (250, 750)"
        res = _parse_bbox_response(raw, width=1920, height=1080, model_name="ui-tars")
        # UI-TARS uses (x, y)
        # x = 250/1000 * 1920 = 480
        # y = 750/1000 * 1080 = 810
        self.assertAlmostEqual(res["x"], 480)
        self.assertAlmostEqual(res["y"], 810)

    def test_absolute_coords(self):
        raw = "(1200, 800)"
        res = _parse_bbox_response(raw, width=1920, height=1080)
        # values > 1000 -> absolute pixels
        self.assertEqual(res["x"], 1200)
        self.assertEqual(res["y"], 800)

if __name__ == "__main__":
    unittest.main()
