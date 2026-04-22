import os
import uuid
import csv
import io
import socket
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

from database import Database
from sheets import SheetsManager
from qr_gen import generate_qr_code

load_dotenv()

app = FastAPI(title="QR Attendance System")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database()
sheets = SheetsManager()

_DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(_DATA_DIR, exist_ok=True)
QR_DIR = os.path.join(_DATA_DIR, "qr_codes")
os.makedirs(QR_DIR, exist_ok=True)
app.mount("/qr_codes", StaticFiles(directory=QR_DIR), name="qr_codes")

STATIC_DIR = "static"
os.makedirs(os.path.join(STATIC_DIR, "images"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _landing_context() -> dict:
    """Read event config from .env for the landing page."""
    return {
        "event_name":    os.getenv("EVENT_NAME",    "QR Attendance System"),
        "event_tagline": os.getenv("EVENT_TAGLINE", "Scan the code below to get started."),
        "event_date":    os.getenv("EVENT_DATE",    ""),
        "event_venue":   os.getenv("EVENT_VENUE",   ""),
        "event_qr_url":  os.getenv("EVENT_QR_URL",  "http://localhost:8000"),
        "event_logo":    os.getenv("EVENT_LOGO_PATH", ""),
        "sponsors": [
            f"/static/images/{f}"
            for f in sorted(os.listdir(os.path.join(STATIC_DIR, "images")))
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg"))
            and not f.startswith(".")
        ],
        "promos": [
            {
                "icon":  os.getenv("PROMO_1_ICON",  "⚡"),
                "title": os.getenv("PROMO_1_TITLE", "Fast Check-In"),
                "text":  os.getenv("PROMO_1_TEXT",  "Scan your personal QR code at the entrance — no queues."),
            },
            {
                "icon":  os.getenv("PROMO_2_ICON",  "🕐"),
                "title": os.getenv("PROMO_2_TITLE", "Time Tracking"),
                "text":  os.getenv("PROMO_2_TEXT",  "Automatic time-in and time-out logging for every attendee."),
            },
            {
                "icon":  os.getenv("PROMO_3_ICON",  "📊"),
                "title": os.getenv("PROMO_3_TITLE", "Live Reports"),
                "text":  os.getenv("PROMO_3_TEXT",  "Attendance syncs to Google Sheets in real time."),
            },
        ],
    }


# ── Pydantic models ────────────────────────────────────────────────────────────

class AttendeeCreate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    school: str = ""
    position: str = ""


class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    school: str = ""
    position: str = ""


class CheckoutLookup(BaseModel):
    query: str  # name or email


class ScanRequest(BaseModel):
    attendee_id: str
    mode: str  # "time_in" or "time_out"


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def landing_page(request: Request):
    return templates.TemplateResponse(
        "landing.html", {"request": request, **_landing_context()}
    )


def _base_url() -> str:
    """Return the server's LAN URL, auto-detecting the network IP if EVENT_QR_URL is not set."""
    configured = os.getenv("EVENT_QR_URL", "").strip()
    if configured and configured != "http://localhost:8000":
        return configured.rstrip("/")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    return f"http://{ip}:8000"


@app.get("/landing-qr", include_in_schema=False)
def landing_qr_image():
    """Serve a QR code image encoding the server's base URL."""
    qr_path = "qr_codes/_landing.png"
    generate_qr_code(_base_url(), qr_path)
    return FileResponse(qr_path, media_type="image/png")


@app.get("/scanner-qr/in", include_in_schema=False)
def scanner_in_qr():
    """QR code that links to the self-registration (Time In) page."""
    qr_path = "qr_codes/_scanner_in.png"
    generate_qr_code(f"{_base_url()}/register", qr_path)
    return FileResponse(qr_path, media_type="image/png")


@app.get("/scanner-qr/out", include_in_schema=False)
def scanner_out_qr():
    """QR code that links to the self-checkout (Time Out) page."""
    qr_path = "qr_codes/_scanner_out.png"
    generate_qr_code(f"{_base_url()}/checkout", qr_path)
    return FileResponse(qr_path, media_type="image/png")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse("templates/admin.html")


@app.get("/scanner", include_in_schema=False)
def scanner_page():
    return FileResponse("templates/scanner.html")

@app.get("/scanner/in", include_in_schema=False)
def scanner_in_page():
    return FileResponse("templates/scanner_in.html")

@app.get("/scanner/out", include_in_schema=False)
def scanner_out_page():
    return FileResponse("templates/scanner_out.html")


@app.get("/register", include_in_schema=False)
def register_page():
    return FileResponse("templates/register.html")


@app.get("/register/confirm", include_in_schema=False)
def register_confirm_page():
    return FileResponse("templates/register_confirm.html")


@app.get("/checkout", include_in_schema=False)
def checkout_page():
    return FileResponse("templates/checkout.html")


# ── Self-registration & self-checkout ─────────────────────────────────────────

@app.post("/api/register")
def self_register(data: RegisterRequest):
    name  = data.name.strip()
    email = data.email.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Full name is required")
    if not email:
        raise HTTPException(status_code=400, detail="Email address is required")

    # Check if already registered by email
    all_attendees = db.get_all_attendees()
    existing = next((a for a in all_attendees if a["email"].lower() == email), None)

    if existing:
        attendance = db.get_attendance(existing["id"])
        if attendance and attendance.get("time_in"):
            t = datetime.fromisoformat(attendance["time_in"]).strftime("%I:%M %p")
            raise HTTPException(
                status_code=409,
                detail=f"You already checked in at {t}. Show your personal QR at the exit.",
            )
        attendee_id = existing["id"]
        attendee    = existing
    else:
        attendee_id = str(uuid.uuid4())
        db.add_attendee(attendee_id, name, email,
                        data.phone.strip(), data.school.strip(), data.position.strip())
        generate_qr_code(attendee_id, f"{QR_DIR}/{attendee_id}.png")
        attendee = {"id": attendee_id, "name": name, "email": email,
                    "phone": data.phone.strip(), "school": data.school.strip(),
                    "position": data.position.strip()}

    now = datetime.now()
    timestamp    = now.isoformat(timespec="seconds")
    display_time = now.strftime("%I:%M %p")
    db.record_time_in(attendee_id, timestamp)
    sheets.upsert_attendance(attendee, timestamp, None)
    return {"id": attendee_id, "name": attendee["name"], "time": display_time}


@app.post("/api/checkout")
def self_checkout(data: CheckoutLookup):
    query = data.query.strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="Please enter your name or email")

    all_attendees = db.get_all_attendees()
    # Prefer exact email match, fall back to name
    matches = [a for a in all_attendees if a["email"].lower() == query]
    if not matches:
        matches = [a for a in all_attendees if a["name"].lower() == query]
    if not matches:
        raise HTTPException(
            status_code=404,
            detail="No attendee found with that name or email. Please check your entry.",
        )

    attendee   = matches[0]
    attendance = db.get_attendance(attendee["id"])
    if not attendance or not attendance.get("time_in"):
        raise HTTPException(status_code=400, detail=f"{attendee['name']} has not checked in yet.")
    if attendance.get("time_out"):
        prev = datetime.fromisoformat(attendance["time_out"]).strftime("%I:%M %p")
        raise HTTPException(status_code=409, detail=f"You already checked out at {prev}.")

    now = datetime.now()
    timestamp    = now.isoformat(timespec="seconds")
    display_time = now.strftime("%I:%M %p")
    db.record_time_out(attendee["id"], timestamp)
    updated = db.get_attendance(attendee["id"])
    sheets.upsert_attendance(attendee, updated["time_in"], timestamp)
    return {
        "name":    attendee["name"],
        "time":    display_time,
        "message": f"Goodbye, {attendee['name']}! See you next time.",
    }


# ── Attendee endpoints ─────────────────────────────────────────────────────────

@app.post("/api/attendees")
def create_attendee(data: AttendeeCreate):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    attendee_id = str(uuid.uuid4())
    db.add_attendee(attendee_id, data.name.strip(), data.email.strip(),
                    data.phone.strip(), data.school.strip(), data.position.strip())
    generate_qr_code(attendee_id, f"{QR_DIR}/{attendee_id}.png")
    return {"id": attendee_id, "name": data.name.strip()}


@app.get("/api/attendees")
def list_attendees():
    return db.get_all_attendees()


# NOTE: /import must be defined before /{attendee_id} so FastAPI matches it first
@app.post("/api/attendees/import")
async def import_attendees(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    created = []
    errors = []

    for i, row in enumerate(reader, start=2):
        # Accept headers in any case
        name = (row.get("name") or row.get("Name") or row.get("NAME") or "").strip()
        if not name:
            errors.append(f"Row {i}: missing name — skipped")
            continue
        attendee_id = str(uuid.uuid4())
        db.add_attendee(
            attendee_id,
            name,
            (row.get("email") or row.get("Email") or "").strip(),
            (row.get("phone") or row.get("Phone") or "").strip(),
            (row.get("school") or row.get("School") or row.get("Name of School") or "").strip(),
            (row.get("position") or row.get("Position") or "").strip(),
        )
        generate_qr_code(attendee_id, f"{QR_DIR}/{attendee_id}.png")
        created.append({"id": attendee_id, "name": name})

    return {"created": len(created), "errors": errors, "attendees": created}


@app.get("/api/attendees/{attendee_id}/qr")
def get_qr(attendee_id: str):
    # Validate it's a proper UUID to prevent path traversal
    try:
        uuid.UUID(attendee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attendee ID")
    qr_path = f"{QR_DIR}/{attendee_id}.png"
    if not os.path.exists(qr_path):
        raise HTTPException(status_code=404, detail="QR code not found")
    return FileResponse(qr_path, media_type="image/png")


@app.delete("/api/attendees/{attendee_id}")
def delete_attendee(attendee_id: str):
    try:
        uuid.UUID(attendee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attendee ID")
    attendee = db.get_attendee(attendee_id)
    if not attendee:
        raise HTTPException(status_code=404, detail="Attendee not found")
    db.delete_attendee(attendee_id)
    qr_path = f"{QR_DIR}/{attendee_id}.png"
    if os.path.exists(qr_path):
        os.remove(qr_path)
    return {"message": "Deleted"}


# ── Scan endpoint ──────────────────────────────────────────────────────────────

@app.post("/api/scan")
def process_scan(data: ScanRequest):
    if data.mode not in ("time_in", "time_out", "auto"):
        raise HTTPException(status_code=400, detail="mode must be 'time_in', 'time_out', or 'auto'")

    # Validate UUID format to prevent injection
    try:
        uuid.UUID(data.attendee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid QR code")

    attendee = db.get_attendee(data.attendee_id)
    if not attendee:
        raise HTTPException(status_code=404, detail="QR code not registered in this event")

    attendance = db.get_attendance(data.attendee_id)
    now = datetime.now()
    timestamp = now.isoformat(timespec="seconds")
    display_time = now.strftime("%I:%M %p")

    # ── Auto mode: resolve to time_in or time_out based on current state ──
    if data.mode == "auto":
        if not attendance or not attendance.get("time_in"):
            data = ScanRequest(attendee_id=data.attendee_id, mode="time_in")
        elif not attendance.get("time_out"):
            data = ScanRequest(attendee_id=data.attendee_id, mode="time_out")
        else:
            raise HTTPException(
                status_code=409,
                detail=f"{attendee['name']} has already fully checked in and out",
            )

    if data.mode == "time_in":
        if attendance and attendance.get("time_in"):
            prev = datetime.fromisoformat(attendance["time_in"]).strftime("%I:%M %p")
            raise HTTPException(
                status_code=409,
                detail=f"{attendee['name']} already checked in at {prev}",
            )
        db.record_time_in(data.attendee_id, timestamp)
        sheets.upsert_attendance(attendee, timestamp, None)
        return {
            "status": "success",
            "type": "time_in",
            "name": attendee["name"],
            "message": f"Welcome, {attendee['name']}!",
            "time": display_time,
        }

    else:  # time_out
        if not attendance or not attendance.get("time_in"):
            raise HTTPException(
                status_code=400,
                detail=f"{attendee['name']} has not checked in yet",
            )
        if attendance.get("time_out"):
            prev = datetime.fromisoformat(attendance["time_out"]).strftime("%I:%M %p")
            raise HTTPException(
                status_code=409,
                detail=f"{attendee['name']} already checked out at {prev}",
            )
        db.record_time_out(data.attendee_id, timestamp)
        updated = db.get_attendance(data.attendee_id)
        sheets.upsert_attendance(attendee, updated["time_in"], timestamp)
        return {
            "status": "success",
            "type": "time_out",
            "name": attendee["name"],
            "message": f"Goodbye, {attendee['name']}! See you next time.",
            "time": display_time,
        }


# ── Attendance endpoints ───────────────────────────────────────────────────────

@app.get("/api/attendance")
def get_attendance():
    return db.get_all_attendance()


@app.get("/api/attendance/export")
def export_attendance():
    records = db.get_all_attendance()
    output = io.StringIO()
    fieldnames = ["name", "email", "phone", "school", "position", "time_in", "time_out", "duration"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        if r.get("time_in") and r.get("time_out"):
            try:
                diff = datetime.fromisoformat(r["time_out"]) - datetime.fromisoformat(r["time_in"])
                h, rem = divmod(int(diff.total_seconds()), 3600)
                r["duration"] = f"{h}h {rem // 60}m"
            except Exception:
                r["duration"] = ""
        else:
            r["duration"] = ""
        writer.writerow(r)
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance.csv"},
    )


@app.post("/api/attendance/reset")
def reset_attendance():
    db.reset_attendance()
    return {"message": "All attendance records cleared"}
