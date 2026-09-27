"""Street Manager Open Data SNS receiver.

Deploy this as a separate HTTPS service. It verifies AWS SNS signatures and
the DfT production topic before confirming subscriptions or storing events.
"""
import base64, json, os, sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI, Header, HTTPException, Request as FastAPIRequest

TOPICS = {
    "permit": "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic",
    "activity": "arn:aws:sns:eu-west-2:287813576808:prod-activity-topic",
    "section-58": "arn:aws:sns:eu-west-2:287813576808:prod-section-58-topic",
}
OBJECT_TYPES = {
    "permit": {"PERMIT", "WORK"},
    "activity": {"ACTIVITY"},
    "section-58": {"SECTION_58", "SECTION58"},
}
DB = Path(os.getenv("STREET_MANAGER_WEBHOOK_DB", "/data/street_manager.sqlite3"))
READ_TOKEN = os.getenv("STREET_MANAGER_WEBHOOK_TOKEN", "")
app = FastAPI(title="Street Manager Open Data Receiver")

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        message_id TEXT PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP,
        event_time TEXT, event_type TEXT, object_reference TEXT, payload TEXT NOT NULL
    )""")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if "topic" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN topic TEXT")
    if "object_type" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN object_type TEXT")
    return conn

def string_to_sign(message):
    fields = ["Message", "MessageId"]
    if message.get("Subject") is not None:
        fields.append("Subject")
    if message.get("Type") in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields += ["SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    else:
        fields += ["Timestamp", "TopicArn", "Type"]
    return "".join(f"{key}\n{message[key]}\n" for key in fields)

def valid_aws_url(value, path_prefix=None):
    parsed = urlsplit(str(value or ""))
    if (parsed.scheme != "https" or parsed.hostname != "sns.eu-west-2.amazonaws.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return False
    return not path_prefix or parsed.path.startswith(path_prefix)

def verify_sns(message, topic):
    if topic not in TOPICS or message.get("TopicArn") != TOPICS[topic]:
        raise HTTPException(403, "Unexpected SNS topic")
    cert_url = message.get("SigningCertURL")
    if not valid_aws_url(cert_url, "/SimpleNotificationService-"):
        raise HTTPException(403, "Invalid SNS certificate URL")
    if message.get("SignatureVersion") not in ("1", "2"):
        raise HTTPException(403, "Unsupported SNS signature version")
    request = Request(cert_url, headers={"User-Agent": "National-Outage-Checker/1.0"})
    with urlopen(request, timeout=8) as response:
        cert_bytes = response.read(100_000)
    cert = x509.load_pem_x509_certificate(cert_bytes)
    algorithm = hashes.SHA1() if message["SignatureVersion"] == "1" else hashes.SHA256()
    try:
        cert.public_key().verify(
            base64.b64decode(message["Signature"]),
            string_to_sign(message).encode(),
            padding.PKCS1v15(),
            algorithm,
        )
    except Exception as exc:
        raise HTTPException(403, "Invalid SNS signature") from exc

def confirm(message):
    url = message.get("SubscribeURL")
    if not valid_aws_url(url):
        raise HTTPException(403, "Invalid SNS confirmation URL")
    with urlopen(Request(url, headers={"User-Agent": "National-Outage-Checker/1.0"}), timeout=8) as response:
        if response.status >= 300:
            raise HTTPException(502, "SNS confirmation failed")

@app.get("/health")
def health():
    return {"ok": True, "topics": sorted(TOPICS)}

@app.post("/street-manager/{topic}")
async def receive(topic: str, request: FastAPIRequest,
                  x_amz_sns_message_type: str | None = Header(default=None)):
    if topic not in TOPICS:
        raise HTTPException(404, "Unknown Street Manager topic")
    if not x_amz_sns_message_type:
        raise HTTPException(400, "SNS message header required")
    try:
        message = json.loads((await request.body()).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    if message.get("Type") != x_amz_sns_message_type:
        raise HTTPException(400, "SNS message type mismatch")
    verify_sns(message, topic)
    if message["Type"] == "SubscriptionConfirmation":
        confirm(message)
        return {"ok": True, "confirmed": True, "topic": topic}
    if message["Type"] != "Notification":
        return {"ok": True, "ignored": True}
    try:
        event = json.loads(message["Message"])
    except Exception as exc:
        raise HTTPException(400, "Invalid embedded event JSON") from exc
    object_type = str(event.get("object_type", "")).upper()
    if object_type and object_type not in OBJECT_TYPES[topic]:
        raise HTTPException(400, "Event object type does not match endpoint")
    with db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO messages
               (message_id,event_time,event_type,object_reference,payload,topic,object_type)
               VALUES(?,?,?,?,?,?,?)""",
            (message["MessageId"], event.get("event_time"), event.get("event_type"),
             event.get("object_reference"), json.dumps(event), topic, object_type),
        )
    return {"ok": True, "topic": topic}

@app.get("/api/events")
def events(authorization: str | None = Header(default=None), limit: int = 1000,
           topic: str | None = None):
    if not READ_TOKEN or authorization != "Bearer " + READ_TOKEN:
        raise HTTPException(401, "Unauthorized")
    if topic is not None and topic not in TOPICS:
        raise HTTPException(400, "Unknown Street Manager topic")
    limit = max(1, min(limit, 5000))
    query = "SELECT payload FROM messages"
    params = []
    if topic:
        query += " WHERE topic = ?"
        params.append(topic)
    query += " ORDER BY received_at DESC LIMIT ?"
    params.append(limit)
    with db() as conn:
        rows = conn.execute(query, params).fetchall()
    return {"ok": True, "events": [json.loads(row[0]) for row in rows]}
