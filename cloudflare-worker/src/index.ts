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

const TELECOM_TERMS = [
  "telecom", "telecommunications", "broadband", "fibre", "fiber", "internet",
  "openreach", "virgin media", "virginmedia", "cityfibre", "city fibre", "vodafone",
  "voneus", "hyperoptic", "gigaclear", "community fibre", "communityfibre", "zzoomm",
  "giganet", "toob", "talktalk", "telefonica",
];

const TELECOM_TOKENS = new Set(["bt", "ee", "o2", "three", "sky", "isp"]);
const CANCELLED_TERMS = ["cancelled", "canceled", "cancel", "withdrawn", "revoked"];
const CLOSED_RETENTION_DAYS = 7;
const ACTIVE_RETENTION_DAYS = 90;

function normalise(value: unknown): string {
  return String(value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function eventData(event: Record<string, unknown>): Record<string, unknown> {
  const raw = event.object_data;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) return raw as Record<string, unknown>;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    } catch { /* use the outer event */ }
  }
  return event;
}

function scalarValues(value: unknown): string[] {
  if (value == null) return [];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return [String(value)];
  if (Array.isArray(value)) return value.flatMap(scalarValues);
  if (typeof value === "object") return Object.values(value as Record<string, unknown>).flatMap(scalarValues);
  return [];
}

const RELEVANT_FIELD_KEYS = new Set([
  "promoterorganisation", "promoterorganisationname", "workspromotername",
  "promotername", "organisationname", "promoter", "workdescription",
  "worksdescription", "description", "activitytype", "worktype",
  "workcategory", "permitcategory", "activitydescription",
]);

function compactKey(value: unknown): string {
  return String(value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function relevantFieldValues(value: unknown): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const values: string[] = [];
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (RELEVANT_FIELD_KEYS.has(compactKey(key))) values.push(...scalarValues(child));
    if (child && typeof child === "object" && !Array.isArray(child)) {
      values.push(...relevantFieldValues(child));
    }
  }
  return values;
}

function searchableText(event: Record<string, unknown>): string {
  return normalise(relevantFieldValues(eventData(event)).join(" "));
}

function isTelecomEvent(event: Record<string, unknown>): boolean {
  const text = searchableText(event);
  if (!text) return false;
  if (TELECOM_TERMS.some((term) => text.includes(normalise(term)))) return true;
  const tokens = new Set(text.split(" "));
  return [...TELECOM_TOKENS].some((term) => tokens.has(term));
}

function isCancelledEvent(event: Record<string, unknown>): boolean {
  const data = eventData(event);
  const statusText = normalise([
    event.event_type, data.work_status, data.permit_status, data.status,
    data.activity_status, data.event_type,
  ].filter(Boolean).join(" "));
  return CANCELLED_TERMS.some((term) => statusText.includes(term));
}


const COMPACT_FIELDS: Record<string, string[]> = {
  workReferenceNumber: ["work_reference_number", "work_reference", "works_reference", "reference", "activity_reference", "object_reference"],
  promoterOrganisation: ["promoter_organisation", "promoter_organisation_name", "works_promoter_name", "promoter_name", "organisation_name", "promoter"],
  streetName: ["street_name", "street", "road_name"],
  latitude: ["latitude", "lat", "location_latitude", "start_latitude"],
  longitude: ["longitude", "lng", "lon", "location_longitude", "start_longitude"],
  startDate: ["proposed_start_time", "proposed_start_date", "start_time", "start_date", "actual_start_date_time", "actual_start"],
  trafficManagementType: ["traffic_management_type", "traffic_management", "traffic_management_description"],
};

function fieldValue(value: unknown, names: string[]): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const wanted = new Set(names.map(compactKey));
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (wanted.has(compactKey(key)) && child != null && child !== "") return child;
  }
  for (const child of Object.values(value as Record<string, unknown>)) {
    const nested = fieldValue(child, names);
    if (nested != null && nested !== "") return nested;
  }
  return null;
}

function compactEvent(event: Record<string, unknown>): Record<string, unknown> {
  const data = eventData(event);
  const value = (name: keyof typeof COMPACT_FIELDS) =>
    fieldValue(data, COMPACT_FIELDS[name]) ?? fieldValue(event, COMPACT_FIELDS[name]);
  const workReferenceNumber = value("workReferenceNumber") ?? event.object_reference ?? null;
  return {
    object_reference: event.object_reference ?? workReferenceNumber,
    event_reference: event.event_reference ?? event.event_id ?? event.object_reference ?? null,
    event_time: event.event_time ?? event.event_timestamp ?? event.created_at ?? null,
    event_type: event.event_type ?? event.event_name ?? null,
    object_type: event.object_type ?? null,
    object_data: {
      WorkReferenceNumber: workReferenceNumber,
      PromoterOrganisationName: value("promoterOrganisation"),
      StreetName: value("streetName"),
      Latitude: value("latitude"),
      Longitude: value("longitude"),
      ProposedStartDate: value("startDate"),
      TrafficManagementType: value("trafficManagementType"),
    },
  };
}

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

async function receive(request: Request, env: Env, requestedTopic: string | null): Promise<Response> {
  const headerType = request.headers.get("x-amz-sns-message-type");
  if (!headerType) return json({ error: "SNS message header required" }, 400);
  let message: SnsMessage;
  try {
    message = await request.json();
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }
  if (message.Type !== headerType) return json({ error: "SNS message type mismatch" }, 400);
  const topic = requestedTopic || Object.keys(TOPICS).find((name) => TOPICS[name] === message.TopicArn);
  if (!topic || !(topic in TOPICS)) return json({ error: "Unknown Street Manager topic" }, 403);
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
    await env.DB.prepare(
      `INSERT INTO subscription_status(topic, confirmed_at, last_confirmation_message_id)
       VALUES (?, datetime('now'), ?)
       ON CONFLICT(topic) DO UPDATE SET confirmed_at=excluded.confirmed_at,
       last_confirmation_message_id=excluded.last_confirmation_message_id`,
    ).bind(topic, message.MessageId).run();
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
  // Filter before D1: the national Street Manager feeds are extremely high volume.
  // Subscription confirmations are handled above; only relevant live telecom works are persisted.
  if (isCancelledEvent(event)) {
    const objectReference = event.object_reference || null;
    if (objectReference) {
      const existing = await env.DB.prepare(
        "SELECT message_id FROM messages WHERE topic = ? AND object_reference = ? LIMIT 1",
      ).bind(topic, objectReference).first();
      if (existing) {
        await env.DB.prepare(
          "DELETE FROM messages WHERE topic = ? AND object_reference = ?",
        ).bind(topic, objectReference).run();
      }
    }
    return json({ ok: true, topic, ignored: true, reason: "cancelled" });
  }
  if (!isTelecomEvent(event)) {
    return json({ ok: true, topic, ignored: true, reason: "non-telecom" });
  }

  // Store only the fields needed by the dashboard. This keeps D1 writes and
  // the dashboard response bounded even when the DfT notification schema grows.
  const compact = compactEvent(event);
  const payload = JSON.stringify(compact);
  const objectReference = compact.object_reference ? String(compact.object_reference) : null;
  if (objectReference) {
    const existing = await env.DB.prepare(
      "SELECT payload FROM messages WHERE topic = ? AND object_reference = ? LIMIT 1",
    ).bind(topic, objectReference).first<{ payload: string }>();
    if (existing?.payload === payload) {
      return json({ ok: true, topic, ignored: true, reason: "duplicate" });
    }
  }

  // Keep the hot path to one D1 row write. Activity and retention are derived/read
  // during API requests instead of adding writes to every SNS notification.
  await env.DB.prepare(
    `INSERT INTO messages
     (message_id, received_at, event_time, event_type, object_reference, object_type, topic, payload)
     VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)
     ON CONFLICT(topic, object_reference) WHERE object_reference IS NOT NULL DO UPDATE SET
       message_id=excluded.message_id,
       received_at=excluded.received_at,
       event_time=excluded.event_time,
       event_type=excluded.event_type,
       object_type=excluded.object_type,
       payload=excluded.payload`,
  ).bind(
    message.MessageId, event.event_time || null, event.event_type || null,
    objectReference, objectType, topic, payload,
  ).run();
  return json({ ok: true, topic });
}

async function pruneMessages(env: Env): Promise<void> {
  await env.DB.batch([
    env.DB.prepare(
      `DELETE FROM messages
       WHERE received_at < datetime('now', '-${CLOSED_RETENTION_DAYS} days')
       AND (
         lower(payload) LIKE '%completed%'
         OR lower(payload) LIKE '%complete%'
         OR lower(payload) LIKE '%closed%'
         OR lower(payload) LIKE '%finished%'
         OR lower(payload) LIKE '%cancelled%'
         OR lower(payload) LIKE '%canceled%'
         OR lower(payload) LIKE '%withdrawn%'
         OR lower(payload) LIKE '%revoked%'
       )`,
    ),
    env.DB.prepare(`DELETE FROM messages WHERE received_at < datetime('now', '-${ACTIVE_RETENTION_DAYS} days')`),
  ]);
}

async function events(request: Request, env: Env): Promise<Response> {
  if (!env.READ_TOKEN || request.headers.get("authorization") !== `Bearer ${env.READ_TOKEN}`) {
    return json({ error: "Unauthorized" }, 401);
  }
  await pruneMessages(env);
  const url = new URL(request.url);
  const topic = url.searchParams.get("topic");
  if (topic && !(topic in TOPICS)) return json({ error: "Unknown Street Manager topic" }, 400);
  const requested = Number.parseInt(url.searchParams.get("limit") || "1000", 10);
  const limit = Math.max(1, Math.min(Number.isFinite(requested) ? requested : 1000, 5000));
  const statement = topic
    ? env.DB.prepare("SELECT payload FROM messages WHERE topic = ? ORDER BY received_at DESC LIMIT ?").bind(topic, limit)
    : env.DB.prepare("SELECT payload FROM messages ORDER BY received_at DESC LIMIT ?").bind(limit);
  const result = await statement.all<{ payload: string }>();
  // Compact legacy rows at read time too, so records saved before this change
  // cannot make the dashboard response exceed its safety limit.
  return json({ ok: true, events: result.results.map((row) => compactEvent(JSON.parse(row.payload))) });
}

async function status(request: Request, env: Env): Promise<Response> {
  if (!env.READ_TOKEN || request.headers.get("authorization") !== `Bearer ${env.READ_TOKEN}`) {
    return json({ error: "Unauthorized" }, 401);
  }
  await pruneMessages(env);
  const [subscriptions, activity, totals] = await env.DB.batch([
    env.DB.prepare("SELECT topic, confirmed_at FROM subscription_status ORDER BY topic"),
    env.DB.prepare(
      `SELECT topic, MAX(event_time) AS last_event_at, MAX(received_at) AS last_received_at,
              COUNT(*) AS event_count
       FROM messages GROUP BY topic ORDER BY topic`,
    ),
    env.DB.prepare("SELECT topic, COUNT(*) AS stored_count FROM messages GROUP BY topic ORDER BY topic"),
  ]);
  return json({
    ok: true,
    expectedTopics: Object.keys(TOPICS),
    subscriptions: subscriptions.results,
    activity: activity.results,
    stored: totals.results,
    retentionDays: ACTIVE_RETENTION_DAYS,
    closedRetentionDays: CLOSED_RETENTION_DAYS,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, topics: Object.keys(TOPICS), storage: "D1" });
    }
    if (request.method === "GET" && url.pathname === "/api/events") return events(request, env);
    if (request.method === "GET" && url.pathname === "/api/status") return status(request, env);
    if (request.method === "POST" && url.pathname === "/street-manager/open-data") {
      return receive(request, env, null);
    }
    const match = url.pathname.match(/^\/street-manager\/(permit|activity|section-58)$/);
    if (request.method === "POST" && match) return receive(request, env, match[1]);
    return json({ error: "Not found" }, 404);
  },
};
