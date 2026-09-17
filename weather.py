"""Small key-free Open-Meteo client used by the optional screen sidebar."""
import json
import urllib.parse
import urllib.request


WMO_TEXT = {
    0: "晴", 1: "晴间云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷雨", 96: "雷雨", 99: "强雷雨",
}


def weather_text(code):
    return WMO_TEXT.get(int(code), "未知") if code is not None else "--"


def _json_get(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "InkCompanion/1.5"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return json.loads(response.read(512 * 1024).decode("utf-8"))


def fetch_weather(city, timeout=8):
    city = city.strip()
    if len(city) < 2 or len(city) > 80:
        raise ValueError("城市名需为 2–80 个字符")
    query = urllib.parse.urlencode({"name": city, "count": 1, "language": "zh", "format": "json"})
    places = _json_get(f"https://geocoding-api.open-meteo.com/v1/search?{query}", timeout)
    results = places.get("results") or []
    if not results:
        raise ValueError(f"没有找到城市：{city}")
    place = results[0]
    query = urllib.parse.urlencode({
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,weather_code,is_day", "timezone": "auto",
    })
    forecast = _json_get(f"https://api.open-meteo.com/v1/forecast?{query}", timeout)
    current = forecast.get("current") or {}
    if "temperature_2m" not in current or "weather_code" not in current:
        raise RuntimeError("天气服务没有返回当前天气")
    code = int(current["weather_code"])
    return {
        "city": place.get("name") or city,
        "admin1": place.get("admin1") or "",
        "latitude": float(place["latitude"]),
        "longitude": float(place["longitude"]),
        "temperature_c": float(current["temperature_2m"]),
        "weather_code": code,
        "weather_text": weather_text(code),
        "is_day": bool(current.get("is_day", 1)),
        "observed_at": current.get("time") or "",
        "timezone": forecast.get("timezone") or place.get("timezone") or "",
    }
