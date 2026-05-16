import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request


load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/trip")
def trip():
    return render_template("trip.html", maps_key=os.getenv("GOOGLE_MAPS_API_KEY", ""))


@app.get("/chat")
def chat():
    return render_template("chat.html")


@app.post("/api/trip")
def api_trip():
    payload = request.get_json(silent=True) or {}
    destination = payload.get("destination", "Destinacioni")
    days = int(payload.get("days") or 3)
    nights = int(payload.get("nights") or days)
    budget = int(payload.get("budget") or 900)
    interests = payload.get("interests") or "kulture, ushqim, shetitje"

    hotel_budget = max(120, int(budget * 0.4))
    nightly = max(35, int(hotel_budget / max(nights, 1)))

    return jsonify({
        "destination": destination,
        "coords": demo_coords(destination),
        "weather": (
            f"Parashikim demo per {destination}: mot i bute dhe i pershtatshem per shetitje.\n"
            "Merr nje xhakete te lehte, kepuce komode dhe kontrollo motin real para nisjes."
        ),
        "itinerary": build_demo_itinerary(destination, days, interests),
        "hotels": [
            {
                "name": f"{destination} Central Stay",
                "location": "Qender, prane transportit publik",
                "stars": 4,
                "price_per_night": nightly,
                "total": nightly * nights,
                "why": "Zgjedhje e mire per akses te shpejte ne atraksionet kryesore."
            },
            {
                "name": f"{destination} Urban Hotel",
                "location": "Zone aktive me restorante",
                "stars": 3,
                "price_per_night": max(30, nightly - 18),
                "total": max(30, nightly - 18) * nights,
                "why": "Me ekonomik dhe praktik per udhetime me buxhet te kontrolluar."
            },
            {
                "name": f"{destination} View Suites",
                "location": "Lagje panoramike",
                "stars": 5,
                "price_per_night": nightly + 42,
                "total": (nightly + 42) * nights,
                "why": "Opsion me komoditet me te larte nese do nje eksperience me speciale."
            }
        ]
    })


@app.post("/api/chat")
def api_chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        reply = "Shkruaj destinacionin ose pyetjen dhe une te ndihmoj me planin."
    else:
        reply = (
            "Per kete udhetim do te sugjeroja te fillosh me datat, buxhetin dhe interesat kryesore. "
            "Pastaj ndaj planin ne mengjes, pasdite dhe mbremje qe te mos ngarkohet dita."
        )

    return jsonify({"reply": reply})


def build_demo_itinerary(destination, days, interests):
    rows = []
    for day in range(1, days + 1):
        rows.append(
            f"Dita {day}: Mengjes - eksploro nje zone kryesore ne {destination}. "
            f"Pasdite - aktivitet bazuar ne interesat: {interests}. "
            "Mbremje - darke lokale dhe shetitje e lehte."
        )
    return "\n\n".join(rows)


def demo_coords(destination):
    lookup = {
        "rome": {"lat": 41.9028, "lon": 12.4964},
        "roma": {"lat": 41.9028, "lon": 12.4964},
        "paris": {"lat": 48.8566, "lon": 2.3522},
        "tokyo": {"lat": 35.6762, "lon": 139.6503},
        "london": {"lat": 51.5072, "lon": -0.1276},
        "tirana": {"lat": 41.3275, "lon": 19.8187},
        "prishtina": {"lat": 42.6629, "lon": 21.1655},
    }
    key = destination.lower().split(",")[0].strip()
    return lookup.get(key, {"lat": 41.3275, "lon": 19.8187})


if __name__ == "__main__":
    app.run(debug=True)
