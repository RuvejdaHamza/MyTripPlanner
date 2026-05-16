import json
import os
import re

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

try:
    import google.generativeai as genai
except ImportError:
    genai = None


load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")

HTTP_HEADERS = {
    "User-Agent": "MyTripPlanner/1.0 (student-project)"
}


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/trip")
def trip():
    return render_template("trip.html")


@app.get("/chat")
def chat():
    return render_template("chat.html")


@app.post("/api/trip")
def api_trip():
    payload = request.get_json(silent=True) or {}
    destination = clean_text(payload.get("destination")) or "Tirana"
    days = clamp_int(payload.get("days"), 1, 14, 3)
    nights = clamp_int(payload.get("nights"), 1, 30, days)
    budget = clamp_int(payload.get("budget"), 100, 100000, 900)
    interests = clean_text(payload.get("interests")) or "culture, food, walking"

    place = geocode_destination(destination)
    coords = {"lat": place["lat"], "lon": place["lon"]}
    weather = get_weather(place, destination)
    hotels = get_hotels(place, destination, budget, nights)
    itinerary = get_itinerary(destination, days, nights, budget, interests, weather, hotels)

    return jsonify({
        "destination": place.get("display_name") or destination,
        "coords": coords,
        "weather": weather,
        "itinerary": itinerary,
        "hotels": hotels,
    })


@app.post("/api/chat")
def api_chat():
    payload = request.get_json(silent=True) or {}
    message = clean_text(payload.get("message"))
    history = clean_text(payload.get("history"))

    if not message:
        return jsonify({"reply": "Write your travel question and I will help you right away."})

    prompt = (
        "You are a travel assistant. Reply in English, briefly, clearly, and practically.\n"
        f"Conversation history:\n{history[-2000:]}\n\n"
        f"User question: {message}"
    )
    reply = ask_gemini(prompt)

    if not reply:
        reply = (
            "I could not connect to AI right now. Try adding GEMINI_API_KEY to your .env file. "
            "As a practical next step, tell me your destination, dates, budget, and interests so we can build the plan day by day."
        )

    return jsonify({"reply": reply})


def geocode_destination(destination):
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": destination, "format": "json", "limit": 1},
            headers=HTTP_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        if data:
            item = data[0]
            return {
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "display_name": item.get("display_name", destination),
            }
    except requests.RequestException:
        pass

    return {"lat": 41.3275, "lon": 19.8187, "display_name": destination}


def get_weather(place, destination):
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["lat"],
                "longitude": place["lon"],
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "forecast_days": 5,
                "timezone": "auto",
            },
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        current = data.get("current", {})
        daily = data.get("daily", {})

        current_temp = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        condition = weather_label(current.get("weather_code"))

        lines = [
            f"Current weather in {destination}: {condition}, {current_temp}C, humidity {humidity}%, wind {wind} km/h.",
            "5-day forecast:",
        ]

        dates = daily.get("time", [])
        max_t = daily.get("temperature_2m_max", [])
        min_t = daily.get("temperature_2m_min", [])
        rain = daily.get("precipitation_probability_max", [])
        codes = daily.get("weather_code", [])

        for index, day in enumerate(dates[:5]):
            lines.append(
                f"- {day}: {weather_label(codes[index])}, {min_t[index]}C - {max_t[index]}C, precipitation chance {rain[index]}%."
            )

        lines.append("Tip: check the weather again before departure, especially if you plan outdoor activities.")
        return "\n".join(lines)
    except (requests.RequestException, KeyError, TypeError, IndexError):
        return (
            f"I could not fetch live weather for {destination}. "
            "Try again later or check your internet connection."
        )


def get_hotels(place, destination, budget, nights):
    osm_hotels = fetch_osm_hotels(place)
    hotel_budget = max(120, int(budget * 0.4))
    base_price = max(35, int(hotel_budget / max(nights, 1)))

    if osm_hotels:
        hotels = []
        for index, hotel in enumerate(osm_hotels[:6]):
            price = max(30, base_price + ((index % 3) - 1) * 18)
            stars = 3 + (index % 3)
            hotels.append({
                "name": hotel["name"],
                "location": hotel.get("location") or "Near the destination center",
                "stars": stars,
                "price_per_night": price,
                "total": price * nights,
                "why": "Found on OpenStreetMap near the destination; the price is an estimate based on your budget."
            })
        return hotels

    ai_hotels = ask_gemini_json(
        "Return only a JSON array with 4 hotels or accommodation areas for a trip. "
        "Each object must include: name, location, stars, price_per_night, why. "
        f"Destination: {destination}. Total budget: EUR {budget}. Nights: {nights}. "
        "Prices must be realistic estimates in EUR. Write all text in English."
    )
    if isinstance(ai_hotels, list) and ai_hotels:
        return normalize_hotels(ai_hotels, nights, base_price)

    return normalize_hotels([
        {"name": f"{destination} Central Stay", "location": "Center", "stars": 4, "price_per_night": base_price, "why": "Estimated option adjusted to your budget."},
        {"name": f"{destination} Budget Hotel", "location": "Near public transport", "stars": 3, "price_per_night": max(30, base_price - 20), "why": "An economical option to keep the trip affordable."},
        {"name": f"{destination} Comfort Suites", "location": "Quiet area", "stars": 5, "price_per_night": base_price + 45, "why": "A more comfortable option if you want a higher-end stay."},
    ], nights, base_price)


def fetch_osm_hotels(place):
    query = f"""
    [out:json][timeout:12];
    (
      node["tourism"~"hotel|hostel|guest_house|apartment"](around:6000,{place["lat"]},{place["lon"]});
      way["tourism"~"hotel|hostel|guest_house|apartment"](around:6000,{place["lat"]},{place["lon"]});
      relation["tourism"~"hotel|hostel|guest_house|apartment"](around:6000,{place["lat"]},{place["lon"]});
    );
    out center tags 12;
    """
    try:
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers=HTTP_HEADERS,
            timeout=16,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return []

    hotels = []
    seen = set()
    for item in data.get("elements", []):
        tags = item.get("tags", {})
        name = tags.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        location = tags.get("addr:street") or tags.get("addr:city") or tags.get("tourism", "").replace("_", " ").title()
        hotels.append({"name": name, "location": location})
    return hotels


def get_itinerary(destination, days, nights, budget, interests, weather, hotels):
    hotel_names = ", ".join(hotel["name"] for hotel in hotels[:3])
    prompt = (
        "Create a practical, personalized travel itinerary in English.\n"
        f"Destination: {destination}\n"
        f"Days: {days}, nights: {nights}, total budget: EUR {budget}\n"
        f"Interests: {interests}\n"
        f"Weather: {weather[:900]}\n"
        f"Hotels/accommodation options: {hotel_names}\n"
        "Structure each day with Morning, Afternoon, and Evening. "
        "Include one budget tip at the end. Do not use markdown tables."
    )
    answer = ask_gemini(prompt)
    if answer:
        return answer

    rows = []
    for day in range(1, days + 1):
        rows.append(
            f"Day {day}\n"
            f"Morning: explore a key area in {destination}.\n"
            f"Afternoon: choose an activity around your interests: {interests}.\n"
            "Evening: enjoy a local dinner and a relaxed walk in a central area."
        )
    rows.append("Budget tip: keep about 40% of your budget for accommodation and use the rest for food, transport, and activities.")
    return "\n\n".join(rows)


def ask_gemini(prompt):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY")
    if not api_key or genai is None:
        return ""

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
        response = model.generate_content(prompt)
        return (getattr(response, "text", "") or "").strip()
    except Exception:
        return ""


def ask_gemini_json(prompt):
    text = ask_gemini(prompt)
    if not text:
        return None

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def normalize_hotels(items, nights, fallback_price):
    hotels = []
    for index, item in enumerate(items[:6]):
        price = clamp_int(item.get("price_per_night"), 30, 10000, fallback_price + index * 12)
        stars = clamp_int(item.get("stars"), 1, 5, 3 + (index % 3))
        hotels.append({
            "name": clean_text(item.get("name")) or "Hotel",
            "location": clean_text(item.get("location")) or "Convenient location",
            "stars": stars,
            "price_per_night": price,
            "total": price * nights,
            "why": clean_text(item.get("why")) or "Option adjusted to your budget.",
        })
    return hotels


def weather_label(code):
    labels = {
        0: "clear sky",
        1: "mostly clear",
        2: "partly cloudy",
        3: "cloudy",
        45: "fog",
        48: "depositing rime fog",
        51: "light drizzle",
        53: "drizzle",
        55: "dense drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "light showers",
        81: "showers",
        82: "heavy showers",
        95: "thunderstorm",
    }
    return labels.get(code, "variable weather")


def clamp_int(value, minimum, maximum, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    app.run(debug=True)
