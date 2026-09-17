import json
import unittest
from unittest.mock import patch

from weather import fetch_weather, weather_text


class Response:
    status = 200

    def __init__(self, value):
        self.value = json.dumps(value, ensure_ascii=False).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _):
        return self.value


class WeatherTests(unittest.TestCase):
    def test_wmo_text_groups(self):
        self.assertEqual(weather_text(0), "晴")
        self.assertEqual(weather_text(63), "中雨")
        self.assertEqual(weather_text(95), "雷雨")
        self.assertEqual(weather_text(None), "--")

    def test_city_geocoding_then_current_weather(self):
        replies = [
            Response({"results": [{"name": "上海", "admin1": "上海",
                                   "latitude": 31.22, "longitude": 121.46,
                                   "timezone": "Asia/Shanghai"}]}),
            Response({"timezone": "Asia/Shanghai", "current": {
                "time": "2026-09-14T21:00", "temperature_2m": 26.4,
                "weather_code": 2, "is_day": 0}}),
        ]
        with patch("weather.urllib.request.urlopen", side_effect=replies) as request:
            result = fetch_weather("上海")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["city"], "上海")
        self.assertEqual(result["weather_text"], "多云")
        self.assertEqual(result["temperature_c"], 26.4)
        self.assertFalse(result["is_day"])

    def test_unknown_city_stops_before_forecast(self):
        with patch("weather.urllib.request.urlopen",
                   return_value=Response({"results": []})) as request:
            with self.assertRaisesRegex(ValueError, "没有找到城市"):
                fetch_weather("不存在的测试城市")
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
