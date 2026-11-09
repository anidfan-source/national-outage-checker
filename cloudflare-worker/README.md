# Cloudflare Street Manager receiver

This Worker receives DfT Street Manager Open Data AWS SNS notifications and
stores relevant Permit events in D1. It exposes a bearer-token-protected API
consumed by the Streamlit dashboard.

## Deploy on the free plan

1. Create a free Cloudflare account. Workers signup does not require a card.
2. In this directory run `npx wrangler login`.
3. Create the database:
   `npx wrangler d1 create national-outage-street-manager`
4. Copy the returned database ID into `wrangler.toml`.
5. Apply the schema:
   `npx wrangler d1 migrations apply national-outage-street-manager --remote`
6. Create a long random read token:
   `npx wrangler secret put READ_TOKEN`
7. Deploy:
   `npm install && npm run typecheck && npm run deploy`
8. Verify `https://national-outage-street-manager.anidfan-national-outage.workers.dev/health`.

Use this unified URL in DfT Open Data onboarding:

- `https://national-outage-street-manager.anidfan-national-outage.workers.dev/street-manager/open-data`

The receiver is intentionally **Permit-only** to reduce free-plan utilisation.
It acknowledges but does not confirm or process Activity and Section 58 topics.
Topic-specific aliases remain available while old subscriptions are removed,
so AWS receives a successful response and does not retry ignored messages.

If Activity or Section 58 were previously confirmed, ask the DfT Street Manager
service desk to remove those two subscriptions. Code-side filtering cannot
reduce the Cloudflare request count because the notification has already reached
the Worker. When registering again, the unified endpoint confirms only Permit.

The Worker caches imported SNS signing keys in warm isolates, uses one
conditional D1 upsert for permit changes, and prunes retained messages once
daily with a Cron Trigger instead of during every API read.

Configure Streamlit with the Worker origin and the same read token:

```toml
[street_manager]
webhook_url = "https://national-outage-street-manager.anidfan-national-outage.workers.dev"
webhook_token = "the-read-token"
```

The Worker validates the SNS certificate host, signature, exact production
topic ARN and endpoint/topic match before confirming or storing a message.

