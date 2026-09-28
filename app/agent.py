# ruff: noqa
import base64
import datetime
import json
import os
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

PROJECT_ID = "qwiklabs-gcp-03-3303f858f7df"
COLLECTION_NAME = "flight_deals"
BUCKET_NAME = "flight-price-finder-media-3303f858f7df"

# Read agent engine resource name from deployment_metadata.json
METADATA_FILE = Path(__file__).parent.parent / "deployment_metadata.json"
agent_engine_resource_name = None
MEMORY_BANK_ID = "1732326749049454592"

if METADATA_FILE.exists():
    try:
        with open(METADATA_FILE, "r") as f:
            metadata = json.load(f)
            agent_engine_resource_name = metadata.get("remote_agent_runtime_id")
            if agent_engine_resource_name:
                MEMORY_BANK_ID = agent_engine_resource_name.split("/")[-1]
    except Exception:
        pass

if not agent_engine_resource_name:
    agent_engine_resource_name = f"projects/{PROJECT_ID}/locations/us-east1/reasoningEngines/{MEMORY_BANK_ID}"

db = firestore.Client(project=PROJECT_ID)
genai_client = genai.Client(
    vertexai=True, project=PROJECT_ID, location="global"
)
storage_client = storage.Client(project=PROJECT_ID)

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name,
    optimize_data_file=True,
)


# WRITE: after each turn, send the session to Memory Bank for extraction.
async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


def memory_service_builder():
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


def search_flight_deals(origin: str = "BOM", destination: str = "") -> str:
    """Searches flight deals stored in the Firestore database.

    Args:
        origin: Origin airport code (default 'BOM' for Mumbai).
        destination: Optional destination airport code (e.g. DEL, DXB, LHR, GOI, SIN).

    Returns:
        A string listing matching flight deals with prices in INR (₹) and USD, dates, and airlines.
    """
    query = db.collection(COLLECTION_NAME)
    if origin:
        query = query.where("origin", "==", origin.upper())
    if destination:
        query = query.where("destination", "==", destination.upper())

    docs = query.stream()
    results = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        results.append(data)

    if not results:
        return f"No flight deals found for origin='{origin}' and destination='{destination}'."

    output = ["Found the following flight deals:"]
    for deal in results:
        price_inr = deal.get("price_inr", deal.get("price_usd", 0) * 83.5)
        output.append(
            f"- Deal ID {deal.get('id')}: {deal.get('origin')} to {deal.get('destination')} | "
            f"Departure: {deal.get('departure_date')}, Return: {deal.get('return_date')} | "
            f"Price: ₹{price_inr:,.2f} INR (${deal.get('price_usd', 0):.2f} USD) | "
            f"Airline: {deal.get('airline')} | Seats: {deal.get('available_seats')}"
        )
    return "\n".join(output)


def add_flight_deal(
    origin: str = "BOM",
    destination: str = "DEL",
    departure_date: str = "2026-10-15",
    return_date: str = "2026-10-22",
    price_inr: float = 4500.0,
    airline: str = "IndiGo",
    available_seats: int = 10,
) -> str:
    """Adds or updates a flight deal in the Firestore database.

    Args:
        origin: Origin airport code (default 'BOM' for Mumbai).
        destination: Destination airport code (e.g. DEL, DXB).
        departure_date: Departure date in YYYY-MM-DD format.
        return_date: Return date in YYYY-MM-DD format.
        price_inr: Flight price in Indian Rupees (INR ₹).
        airline: Name of the airline.
        available_seats: Number of available seats (default 10).

    Returns:
        Confirmation message with the created document ID.
    """
    doc_id = f"{origin.upper()}-{destination.upper()}-{departure_date.replace('-', '')[-4:]}"
    price_usd = round(price_inr / 83.5, 2)
    deal_data = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date,
        "return_date": return_date,
        "price_inr": float(price_inr),
        "price_usd": price_usd,
        "airline": airline,
        "available_seats": int(available_seats),
    }
    db.collection(COLLECTION_NAME).document(doc_id).set(deal_data)
    return f"Successfully added flight deal {doc_id} to Firestore!"


def analyze_travel_dates(origin: str = "BOM", destination: str = "DEL") -> str:
    """Analyzes travel dates and prices for a route starting from Mumbai (BOM) to recommend the cheapest days to fly.

    Args:
        origin: Origin airport code (default 'BOM' for Mumbai).
        destination: Destination airport code (e.g. DEL, DXB, LHR, GOI, SIN).

    Returns:
        Analysis summary with the lowest price option, date recommendation, and savings in INR (₹).
    """
    query = (
        db.collection(COLLECTION_NAME)
        .where("origin", "==", origin.upper())
        .where("destination", "==", destination.upper())
    )
    docs = list(query.stream())

    if not docs:
        return f"No travel date price data found for {origin.upper()} to {destination.upper()}."

    deals = [d.to_dict() for d in docs]
    for d in deals:
        if "price_inr" not in d:
            d["price_inr"] = d.get("price_usd", 0) * 83.5
    deals.sort(key=lambda x: x.get("price_inr", 0))

    cheapest = deals[0]
    highest = deals[-1]
    avg_price = sum(d.get("price_inr", 0) for d in deals) / len(deals)
    savings = highest.get("price_inr", 0) - cheapest.get("price_inr", 0)

    return (
        f"Date & Price Analysis for {origin.upper()} -> {destination.upper()}:\n"
        f"- Recommended Cheapest Travel Dates: Depart {cheapest.get('departure_date')}, Return {cheapest.get('return_date')} (₹{cheapest.get('price_inr'):,.2f} INR on {cheapest.get('airline')})\n"
        f"- Price Range: ₹{cheapest.get('price_inr'):,.2f} to ₹{highest.get('price_inr'):,.2f} INR (Average: ₹{avg_price:,.2f})\n"
        f"- Maximum Potential Savings: ₹{savings:,.2f} INR by choosing the cheapest departure window."
    )


def convert_flight_currency(amount_inr: float, target_currency: str = "USD") -> str:
    """Converts a flight price in Indian Rupees (INR ₹) into target foreign currencies using real-time exchange rates.

    Args:
        amount_inr: Flight price in Indian Rupees (INR ₹).
        target_currency: 3-letter target currency code (e.g. USD, EUR, GBP, AED, JPY, SGD).

    Returns:
        A string with the converted amount and current exchange rate.
    """
    api_key = os.environ.get("EXCHANGE_RATE_API_KEY")
    if api_key:
        url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/INR"
    else:
        url = "https://open.er-api.com/v6/latest/INR"

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        rates = data.get("rates", {})
        target = target_currency.upper()
        if target not in rates:
            return f"Currency {target} not supported. Try USD, EUR, GBP, AED, JPY, or SGD."

        rate = rates[target]
        converted = float(amount_inr) * rate
        return f"₹{amount_inr:,.2f} INR = {converted:,.2f} {target} (Exchange rate: 1 INR = {rate:.6f} {target})"
    except Exception as e:
        return f"Failed to fetch exchange rates: {e}"


def generate_destination_image(
    destination: str, prompt_description: str = "", tool_context: ToolContext = None
) -> str:
    """Generates a promotional travel image for a destination using gemini-3.1-flash-lite-image in the global region.

    Saves the image as an artifact in the Playground panel, uploads the image bytes to Cloud Storage, and returns its public URL.

    Args:
        destination: Destination city or landmark name (e.g. 'Goa', 'Delhi', 'Dubai', 'London', 'Singapore').
        prompt_description: Optional additional visual prompt details.
        tool_context: ADK ToolContext injected automatically by the runtime.

    Returns:
        The public HTTPS URL of the generated destination image.
    """
    prompt = f"Vibrant travel promotional poster of {destination}. {prompt_description}".strip()

    try:
        res = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
        )
        part = res.candidates[0].content.parts[0]
        image_bytes = part.inline_data.data
        mime_type = part.inline_data.mime_type or "image/jpeg"

        clean_name = "".join(c if c.isalnum() else "_" for c in destination.lower())
        filename = f"{clean_name}_{int(time.time())}.jpg"

        # 1. Save artifact in the Playground's Artifacts panel
        if tool_context:
            tool_context.save_artifact(
                filename=filename,
                artifact=types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            )

        # 2. Upload in-memory image bytes to public Cloud Storage bucket
        bucket = storage_client.bucket(BUCKET_NAME)
        blob_name = f"destinations/{filename}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
        return public_url
    except Exception as e:
        return f"Failed to generate destination image: {e}"


def generate_destination_video(
    destination: str, prompt_description: str = "", tool_context: ToolContext = None
) -> str:
    """Generates a short promotional travel video for a destination using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video as an artifact in the Playground's Artifacts panel, uploads the video bytes to Cloud Storage, and returns its public URL.

    Args:
        destination: Destination city or landmark name (e.g. 'Tokyo', 'London', 'Dubai', 'Goa', 'Singapore').
        prompt_description: Optional additional visual prompt details for the video.
        tool_context: ADK ToolContext injected automatically by the runtime.

    Returns:
        The public HTTPS URL of the generated destination video.
    """
    prompt = f"Cinematic short promotional travel highlight video of {destination}. {prompt_description}".strip()

    try:
        res = genai_client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        if not res.output_video or not res.output_video.data:
            return f"Failed to generate video for {destination}: No video output received from model."

        raw_data = res.output_video.data
        if isinstance(raw_data, str):
            video_bytes = base64.b64decode(raw_data)
        else:
            video_bytes = raw_data

        mime_type = res.output_video.mime_type or "video/mp4"

        clean_name = "".join(c if c.isalnum() else "_" for c in destination.lower())
        filename = f"{clean_name}_{int(time.time())}.mp4"

        # 1. Save artifact in the Playground's Artifacts panel
        if tool_context:
            tool_context.save_artifact(
                filename=filename,
                artifact=types.Part.from_bytes(data=video_bytes, mime_type=mime_type),
            )

        # 2. Upload in-memory video bytes to public Cloud Storage bucket
        bucket = storage_client.bucket(BUCKET_NAME)
        blob_name = f"videos/{filename}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
        return public_url
    except Exception as e:
        return f"Failed to generate destination video: {e}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Flight & Travel Price Finder, specialized for travel out of Mumbai, India (BOM - Chhatrapati Shivaji Maharaj International Airport). "
        "Your primary currency is Indian Rupees (INR ₹). Help users find cheap flight deals from Mumbai, analyze travel dates for savings in INR, "
        "convert prices to foreign currencies, generate promotional destination images and videos, run Python calculations safely, remember user travel preferences across sessions, "
        "and manage flight price entries in Firestore."
    ),
    workflow_description=(
        "Analyze the user request, call appropriate tools, and return structured A2UI UI when appropriate. Always pay close attention to user travel preferences "
        "(preferred destinations, budget in INR ₹, preferred airlines, dates, seating choices) and apply preloaded memories across sessions."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use Table or Heading (unsupported), or Buttons, actions, or forms (they do nothing in adk web). "
        "You may include one Image component, but only when you have a public https URL for the image (for example the URL an image tool returns after uploading to a public bucket). "
        "Set the Image url to that exact https link, for example {\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an Image at a bare filename, "
        "an artifact name, or a non-http(s) path. If you do not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in <a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        search_flight_deals,
        add_flight_deal,
        analyze_travel_dates,
        convert_flight_currency,
        generate_destination_image,
        generate_destination_video,
        PreloadMemoryTool(),
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
    code_executor=code_executor,
)

app = App(
    root_agent=root_agent,
    name="app",
)
