from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-3303f858f7df"
COLLECTION_NAME = "flight_deals"

def seed():
    db = firestore.Client(project=PROJECT_ID)
    flights = [
        {
            "id": "BOM-DEL-1015",
            "origin": "BOM",
            "destination": "DEL",
            "departure_date": "2026-10-15",
            "return_date": "2026-10-22",
            "price_inr": 4500.00,
            "price_usd": 54.00,
            "airline": "IndiGo",
            "available_seats": 12
        },
        {
            "id": "BOM-DEL-1018",
            "origin": "BOM",
            "destination": "DEL",
            "departure_date": "2026-10-18",
            "return_date": "2026-10-25",
            "price_inr": 3800.00,
            "price_usd": 45.50,
            "airline": "Air India",
            "available_seats": 8
        },
        {
            "id": "BOM-DXB-1101",
            "origin": "BOM",
            "destination": "DXB",
            "departure_date": "2026-11-01",
            "return_date": "2026-11-08",
            "price_inr": 18500.00,
            "price_usd": 222.00,
            "airline": "Emirates",
            "available_seats": 15
        },
        {
            "id": "BOM-LHR-1020",
            "origin": "BOM",
            "destination": "LHR",
            "departure_date": "2026-10-20",
            "return_date": "2026-10-28",
            "price_inr": 45000.00,
            "price_usd": 540.00,
            "airline": "British Airways",
            "available_seats": 6
        },
        {
            "id": "BOM-GOI-1105",
            "origin": "BOM",
            "destination": "GOI",
            "departure_date": "2026-11-05",
            "return_date": "2026-11-12",
            "price_inr": 3200.00,
            "price_usd": 38.50,
            "airline": "Akasa Air",
            "available_seats": 20
        },
        {
            "id": "BOM-SIN-1110",
            "origin": "BOM",
            "destination": "SIN",
            "departure_date": "2026-11-10",
            "return_date": "2026-11-18",
            "price_inr": 22000.00,
            "price_usd": 264.00,
            "airline": "Singapore Airlines",
            "available_seats": 10
        }
    ]
    
    for item in flights:
        doc_id = item.pop("id")
        db.collection(COLLECTION_NAME).document(doc_id).set(item)
        print(f"Seeded document {doc_id} into {COLLECTION_NAME}")

if __name__ == "__main__":
    seed()
