export interface Env {
  DB: D1Database;
  READ_TOKEN: string;
}

const TOPICS: Record<string, string> = {
  permit: "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic",
  activity: "arn:aws:sns:eu-west-2:287813576808:prod-activity-topic",
  "section-58": "arn:aws:sns:eu-west-2:287813576808:prod-section-58-topic",
};

const OBJECT_TYPES: Record<string, Set<string>> = {
  permit: new Set(["PERMIT", "WORK"]),
  activity: new Set(["ACTIVITY"]),
  "section-58": new Set(["SECTION_58", "SECTION58"]),
};

type SnsMessage = Record<string, string>;

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

function signingText(message: SnsMessage): string {
  const fields = ["Message", "MessageId"];
  if (message.Subject != null) fields.push("Subject");
  if (["SubscriptionConfirmation", "UnsubscribeConfirmation"].includes(message.Type)) {
    fields.push("SubscribeURL", "Timestamp", "Token", "TopicArn", "Type");
  } else {
    fields.push("Timestamp", "TopicArn", "Type");
  }
  return fields.map((field) => `${field}\n${message[field]}\n`).join("");
}

function awsSnsUrl(value: string, certificate = false): URL | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.hostname !== "sns.eu-west-2.amazonaws.com" ||
        url.username || url.password || (url.port && url.port !== "443")) return null;
    if (certificate && !/^\/SimpleNotificationService-[A-Za-z0-9_-]+\.pem$/.test(url.pathname)) return null;
    return url;
  } catch {
    return null;
  }
}

function pemBytes(pem: string): Uint8Array {
  const encoded = pem.replace(/-----[^-]+-----/g, "").replace(/\s/g, "");
  return Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
}

type Tlv = { start: number; content: number; end: number; tag: number };

function tlv(bytes: Uint8Array, start: number): Tlv {
  const tag = bytes[start];
  let offset = start + 1;
  let length = bytes[offset++];
  if (length & 0x80) {
    const count = length & 0x7f;
    if (!count || count > 4) throw new Error("Unsupported DER length");
    length = 0;
    for (let index = 0; index < count; index++) length = length * 256 + bytes[offset++];
  }
  const end = offset + length;
  if (end > bytes.length) throw new Error("Invalid DER certificate");
  return { start, content: offset, end, tag };
}

function children(bytes: Uint8Array, node: Tlv): Tlv[] {
  const result: Tlv[] = [];
  let offset = node.content;
  while (offset < node.end) {
    const child = tlv(bytes, offset);
    result.push(child);
    offset = child.end;
  }
  if (offset !== node.end) throw new Error("Invalid DER sequence");
  return result;
}

function certificateSpki(certificate: Uint8Array): ArrayBuffer {
  const certificateSequence = tlv(certificate, 0);
  const tbs = children(certificate, certificateSequence)[0];
  const fields = children(certificate, tbs);
  const offset = fields[0].tag === 0xa0 ? 1 : 0;
  const spki = fields[offset + 5];
  if (!spki || spki.tag !== 0x30) throw new Error("Certificate has no public key");
  return certificate.slice(spki.start, spki.end).buffer;
}

async function verifySns(message: SnsMessage, topic: string): Promise<boolean> {
  if (message.TopicArn !== TOPICS[topic] || !["1", "2"].includes(message.SignatureVersion)) return false;
  const certUrl = awsSnsUrl(message.SigningCertURL, true);
  if (!certUrl) return false;
  const certResponse = await fetch(certUrl, { headers: { "User-Agent": "National-Outage-Checker/1.0" } });
  if (!certResponse.ok) return false;
  const certificate = pemBytes(await certResponse.text());
  const algorithm = message.SignatureVersion === "1" ? "SHA-1" : "SHA-256";
  const key = await crypto.subtle.importKey(
    "spki", certificateSpki(certificate), { name: "RSASSA-PKCS1-v1_5", hash: algorithm }, false, ["verify"],
  );
  const signature = Uint8Array.from(atob(message.Signature), (char) => char.charCodeAt(0));
  return crypto.subtle.verify(
    { name: "RSASSA-PKCS1-v1_5" }, key, signature,
    new TextEncoder().encode(signingText(message)),
  );
}

async function receive(request: Request, env: Env, topic: string): Promise<Response> {
  if (!(topic in TOPICS)) return json({ error: "Unknown Street Manager topic" }, 404);
  const headerType = request.headers.get("x-amz-sns-message-type");
  if (!headerType) return json({ error: "SNS message header required" }, 400);
  let message: SnsMessage;
  try {
    message = await request.json();
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }
  if (message.Type !== headerType) return json({ error: "SNS message type mismatch" }, 400);
  try {
    if (!(await verifySns(message, topic))) return json({ error: "Invalid SNS signature or topic" }, 403);
  } catch {
    return json({ error: "Unable to verify SNS signature" }, 403);
  }

  if (message.Type === "SubscriptionConfirmation") {
    const subscribeUrl = awsSnsUrl(message.SubscribeURL);
    if (!subscribeUrl) return json({ error: "Invalid SNS confirmation URL" }, 403);
    const confirmation = await fetch(subscribeUrl);
    if (!confirmation.ok) return json({ error: "SNS confirmation failed" }, 502);
    return json({ ok: true, confirmed: true, topic });
  }
  if (message.Type !== "Notification") return json({ ok: true, ignored: true });

  let event: Record<string, unknown>;
  try {
    event = JSON.parse(message.Message);
  } catch {
    return json({ error: "Invalid embedded event JSON" }, 400);
  }
  const objectType = String(event.object_type || "").toUpperCase();
  if (objectType && !OBJECT_TYPES[topic].has(objectType)) {
    return json({ error: "Event object type does not match endpoint" }, 400);
  }
  await env.DB.prepare(
    `INSERT OR IGNORE INTO messages
     (message_id, received_at, event_time, event_type, object_reference, object_type, topic, payload)
     VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)`,
  ).bind(
    message.MessageId, event.event_time || null, event.event_type || null,
    event.object_reference || null, objectType, topic, JSON.stringify(event),
  ).run();
  return json({ ok: true, topic });
}

async function events(request: Request, env: Env): Promise<Response> {
  if (!env.READ_TOKEN || request.headers.get("authorization") !== `Bearer ${env.READ_TOKEN}`) {
    return json({ error: "Unauthorized" }, 401);
  }
  const url = new URL(request.url);
  const topic = url.searchParams.get("topic");
  if (topic && !(topic in TOPICS)) return json({ error: "Unknown Street Manager topic" }, 400);
  const requested = Number.parseInt(url.searchParams.get("limit") || "1000", 10);
  const limit = Math.max(1, Math.min(Number.isFinite(requested) ? requested : 1000, 5000));
  const statement = topic
    ? env.DB.prepare("SELECT payload FROM messages WHERE topic = ? ORDER BY received_at DESC LIMIT ?").bind(topic, limit)
    : env.DB.prepare("SELECT payload FROM messages ORDER BY received_at DESC LIMIT ?").bind(limit);
  const result = await statement.all<{ payload: string }>();
  return json({ ok: true, events: result.results.map((row) => JSON.parse(row.payload)) });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, topics: Object.keys(TOPICS), storage: "D1" });
    }
    if (request.method === "GET" && url.pathname === "/api/events") return events(request, env);
    const match = url.pathname.match(/^\/street-manager\/(permit|activity|section-58)$/);
    if (request.method === "POST" && match) return receive(request, env, match[1]);
    return json({ error: "Not found" }, 404);
  },
};
