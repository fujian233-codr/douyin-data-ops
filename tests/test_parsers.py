import unittest

from douyin_data_ops.parsers import (
    extract_video_id,
    parse_count,
    parse_datetime,
    parse_duration_seconds,
    parse_rate,
)


class ParserTests(unittest.TestCase):
    def test_parse_count_supports_chinese_units_and_thousands(self):
        self.assertEqual(parse_count("1.2万"), 12000)
        self.assertEqual(parse_count("1.2亿"), 120000000)
        self.assertEqual(parse_count("1,200"), 1200)
        self.assertEqual(parse_count(" - "), None)

    def test_parse_rate_converts_percent_and_decimal(self):
        self.assertEqual(parse_rate("36.84%"), 0.3684)
        self.assertEqual(parse_rate("0.3684"), 0.3684)
        self.assertEqual(parse_rate(""), None)
        with self.assertRaises(ValueError):
            parse_rate("120%")

    def test_parse_duration_supports_text_and_clock(self):
        self.assertEqual(parse_duration_seconds("1分03秒"), 63)
        self.assertEqual(parse_duration_seconds("02:41"), 161)
        self.assertEqual(parse_duration_seconds("63"), 63)
        self.assertEqual(parse_duration_seconds("--"), None)

    def test_parse_datetime_normalizes_common_formats(self):
        self.assertEqual(
            parse_datetime("2026-11-07 21:30"),
            "2026-11-07T21:30:00",
        )
        self.assertEqual(parse_datetime("2026/11/07"), "2026-11-07T00:00:00")
        self.assertEqual(parse_datetime("无效"), None)

    def test_extract_video_id_prefers_explicit_id_and_parses_url(self):
        self.assertEqual(
            extract_video_id(
                "7704505313186597775",
                "https://www.douyin.com/video/7704363037147053288",
            ),
            "7704505313186597775",
        )
        self.assertEqual(
            extract_video_id("", "https://www.douyin.com/video/7704363037147053288"),
            "7704363037147053288",
        )
        self.assertEqual(extract_video_id("", ""), None)


if __name__ == "__main__":
    unittest.main()

