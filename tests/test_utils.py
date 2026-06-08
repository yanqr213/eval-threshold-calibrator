import unittest

from eval_threshold_calibrator.utils import clamp, fmt_float, parse_bool, safe_div, to_float


class UtilsTests(unittest.TestCase):
    def test_parse_bool_true_values(self):
        for value in [True, 1, "1", "true", "YES", "pass", "passed", "ok", "accepted"]:
            self.assertIs(parse_bool(value), True)

    def test_parse_bool_false_values(self):
        for value in [False, 0, "0", "false", "NO", "fail", "failed", "rejected"]:
            self.assertIs(parse_bool(value), False)

    def test_parse_bool_unknown(self):
        self.assertIsNone(parse_bool("maybe"))

    def test_to_float_numbers(self):
        self.assertEqual(to_float(3), 3.0)
        self.assertEqual(to_float("4.5"), 4.5)

    def test_to_float_rejects_bool_and_blank(self):
        self.assertIsNone(to_float(True))
        self.assertIsNone(to_float(""))

    def test_to_float_rejects_nan(self):
        self.assertIsNone(to_float("nan"))

    def test_safe_div_default(self):
        self.assertEqual(safe_div(1, 0, 7), 7)

    def test_safe_div_regular(self):
        self.assertEqual(safe_div(6, 3), 2)

    def test_clamp(self):
        self.assertEqual(clamp(5, 1, 3), 3)
        self.assertEqual(clamp(-1, 1, 3), 1)

    def test_fmt_float(self):
        self.assertEqual(fmt_float(1.2300), "1.23")
        self.assertEqual(fmt_float(2.0), "2")


if __name__ == "__main__":
    unittest.main()
