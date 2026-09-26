"""Street Manager Open Data Permit SNS receiver.

Deploy this as a separate HTTPS service. It verifies AWS SNS signatures and the
DfT production Permit topic before confirming subscriptions or storing events.
"""
import base64, json, os, sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI, Header, HTTPException, Request as FastAPIRequest
from fastapi.responses import JSONResponse

PERMIT_TOPIC = "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic"
DB = Path(os.getenv("STREET_MANAGER_WEBHOOK_DB", "/data/street_manager.sqlite3"))
READ_TOKEN = os.getenv("STREET_MANAGER_WEBHOOK_TOKEN", "")
app = FastAPI(title="Street Manager Permit Receiver")

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        message_id TEXT PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP,
        event_time TEXT, event_type TEXT, object_reference TEXT, payload TEXT NOT NULL
    )""")
    return conn

def string_to_sign(m):
    fields = ["Message","MessageId"]
    if m.get("Subject") is not None: fields.append("Subject")
    if m.get("Type") in ("SubscriptionConfirmation","UnsubscribeConfirmation"):
        fields += ["SubscribeURL","Timestamp","Token","TopicArn","Type"]
    else:
        fields += ["Timestamp","TopicArn","Type"]
    return "".join(f"{k}\n{m[k]}\n" for k in fields)

def valid_aws_url(value, path_prefix=None):
    p=urlsplit(str(value or ""))
    if p.scheme != "https" or p.hostname != "sns.eu-west-2.amazonaws.com" or p.username or p.password or p.port not in (None,443):
        return False
    return not path_prefix or p.path.startswith(path_prefix)

def verify_sns(m):
    if m.get("TopicArn") != PERMIT_TOPIC: raise HTTPException(403,"Unexpected SNS topic")
    cert_url=m.get("SigningCertURL")
    if not valid_aws_url(cert_url,"/SimpleNotificationService-"): raise HTTPException(403,"Invalid SNS certificate URL")
    if m.get("SignatureVersion") not in ("1","2"): raise HTTPException(403,"Unsupported SNS signature version")
    req=Request(cert_url,headers={"User-Agent":"National-Outage-Checker/1.0"})
    with urlopen(req,timeout=8) as r:
        cert_bytes=r.read(100_000)
    cert=x509.load_pem_x509_certificate(cert_bytes)
    algorithm=hashes.SHA1() if m["SignatureVersion"]=="1" else hashes.SHA256()
    try:
        cert.public_key().verify(base64.b64decode(m["Signature"]),string_to_sign(m).encode(),padding.PKCS1v15(),algorithm)
    except Exception:
        raise HTTPException(403,"Invalid SNS signature")

def confirm(m):
    url=m.get("SubscribeURL")
    if not valid_aws_url(url): raise HTTPException(403,"Invalid SNS confirmation URL")
    with urlopen(Request(url,headers={"User-Agent":"National-Outage-Checker/1.0"}),timeout=8) as r:
        if r.status >= 300: raise HTTPException(502,"SNS confirmation failed")

@app.get("/health")
def health():
    return {"ok":True,"topic":"permit"}

@app.post("/street-manager/permit")
async def permit(request: FastAPIRequest, x_amz_sns_message_type: str | None = Header(default=None)):
    if not x_amz_sns_message_type: raise HTTPException(400,"SNS message header required")
    try: m=json.loads((await request.body()).decode("utf-8"))
    except Exception: raise HTTPException(400,"Invalid JSON")
    if m.get("Type") != x_amz_sns_message_type: raise HTTPException(400,"SNS message type mismatch")
    verify_sns(m)
    if m["Type"]=="SubscriptionConfirmation":
        confirm(m)
        return {"ok":True,"confirmed":True}
    if m["Type"]!="Notification": return {"ok":True,"ignored":True}
    try: event=json.loads(m["Message"])
    except Exception: raise HTTPException(400,"Invalid embedded event JSON")
    if str(event.get("object_type","")).upper() != "PERMIT": return {"ok":True,"ignored":True}
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO messages(message_id,event_time,event_type,object_reference,payload) VALUES(?,?,?,?,?)",
                     (m["MessageId"],event.get("event_time"),event.get("event_type"),event.get("object_reference"),json.dumps(event)))
    return {"ok":True}

@app.get("/api/events")
def events(authorization: str | None = Header(default=None), limit: int = 1000):
    if not READ_TOKEN or authorization != "Bearer "+READ_TOKEN: raise HTTPException(401,"Unauthorized")
    limit=max(1,min(limit,5000))
    with db() as conn:
        rows=conn.execute("SELECT payload FROM messages ORDER BY received_at DESC LIMIT ?",(limit,)).fetchall()
    return {"ok":True,"events":[json.loads(x[0]) for x in rows]}
