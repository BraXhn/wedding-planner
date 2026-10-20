"""Väderprognos för bröllopsdagen från SMHI (öppna data, snow1g). Hämtas i bakgrunden och cachas en timme,
så att en sida aldrig väntar på SMHI. Visas bara de sista tio dagarna – längre fram finns ingen prognos."""
import datetime as dt
import json
import threading
import time
import urllib.request

from .core import flag, get_settings, log, parse_date, today

URL = "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon}/lat/{lat}/data.json"
SYMBOLS = {
    1: ("Klart", "☀️"), 2: ("Nästan klart", "🌤"), 3: ("Växlande molnighet", "⛅"), 4: ("Halvklart", "⛅"),
    5: ("Molnigt", "☁️"), 6: ("Mulet", "☁️"), 7: ("Dimma", "🌫"), 8: ("Lätta regnskurar", "🌦"),
    9: ("Regnskurar", "🌦"), 10: ("Kraftiga regnskurar", "🌧"), 11: ("Åskskurar", "⛈"),
    12: ("Lätta byar av regn och snö", "🌨"), 13: ("Byar av regn och snö", "🌨"), 14: ("Kraftiga byar av regn och snö", "🌨"),
    15: ("Lätta snöbyar", "🌨"), 16: ("Snöbyar", "🌨"), 17: ("Kraftiga snöbyar", "❄️"), 18: ("Lätt regn", "🌦"),
    19: ("Regn", "🌧"), 20: ("Kraftigt regn", "🌧"), 21: ("Åska", "⛈"), 22: ("Lätt snöblandat regn", "🌨"),
    23: ("Snöblandat regn", "🌨"), 24: ("Kraftigt snöblandat regn", "🌨"), 25: ("Lätt snöfall", "🌨"),
    26: ("Snöfall", "❄️"), 27: ("Kraftigt snöfall", "❄️"),
}
MISSING = 9999
_cache: dict = {}  # (lat, lon) → (hämtad, json)
_lock = threading.Lock()


def coords(s: dict) -> tuple[float, float] | None:
    try:
        lat, lon = float(str(s.get("venue_lat", "")).replace(",", ".")), float(str(s.get("venue_lon", "")).replace(",", "."))
    except ValueError:
        return None
    return (round(lat, 4), round(lon, 4)) if 54 <= lat <= 70 and 9 <= lon <= 26 else None  # SMHI:s område


def summarize(data: dict, day: dt.date, start: str = "14:00") -> dict | None:
    """Sammanfattar prognosen för dagen (kl. 10–23 lokal tid): väder vid starttiden, min/max-temperatur,
    nederbörd och vind. Saknade värden (9999) hoppas över."""
    rows = []
    for e in data.get("timeSeries", []):
        try:
            at = dt.datetime.fromisoformat(e["time"].replace("Z", "+00:00")).astimezone()
        except (KeyError, ValueError, AttributeError):
            continue
        if at.date() == day and 10 <= at.hour <= 23:
            d = {k: v for k, v in (e.get("data") or {}).items() if isinstance(v, (int, float)) and v != MISSING}
            rows.append((at, d))
    temps = [d["air_temperature"] for _, d in rows if "air_temperature" in d]
    if not temps:
        return None
    try:
        target = dt.time.fromisoformat(start)
    except ValueError:
        target = dt.time(14)
    near = min(rows, key=lambda r: abs(r[0].hour * 60 + r[0].minute - target.hour * 60 - target.minute))[1]
    text, icon = SYMBOLS.get(int(near.get("symbol_code", 0)), ("", "🌡"))
    return {"text": text, "icon": icon, "temp": round(near.get("air_temperature", temps[0])),
            "min": round(min(temps)), "max": round(max(temps)),
            "rain": round(sum(d.get("precipitation_amount_mean", 0) for _, d in rows), 1),
            "wind": round(max((d.get("wind_speed", 0) for _, d in rows), default=0))}


def _fetch(key: tuple[float, float]) -> None:
    try:
        req = urllib.request.Request(URL.format(lat=key[0], lon=key[1]), headers={"User-Agent": "Brollopsplaneraren"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read(5_000_000))
        with _lock:
            _cache[key] = (time.time(), data)
    except Exception as e:  # noqa: BLE001 – vädret får aldrig störa sidan
        log.warning("weather_failed error=%s: %s", type(e).__name__, e)
        with _lock:
            _cache[key] = (time.time() - 3000, _cache.get(key, (0, None))[1])  # försök igen om 10 minuter


def forecast(s: dict | None = None) -> dict | None:
    """Prognosen för bröllopsdagen om den finns i cachen; startar annars en hämtning i bakgrunden."""
    s = s or get_settings()
    wd, key = parse_date(s.get("wedding_date")), coords(s)
    if not (flag(s, "weather_enabled") and wd and key and 0 <= (wd - today()).days <= 10):
        return None
    with _lock:
        fetched, data = _cache.get(key, (0, None))
        stale = time.time() - fetched > 3600
        if stale:
            _cache[key] = (time.time(), data)  # bara en hämtning åt gången
    if stale:
        threading.Thread(target=_fetch, args=(key,), daemon=True).start()
    if not data:
        return None
    out = summarize(data, wd, s.get("wedding_time") or "14:00")
    if out:
        out["date"] = wd
    return out
