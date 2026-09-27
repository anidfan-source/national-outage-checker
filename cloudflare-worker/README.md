# Cloudflare Street Manager receiver

This Worker receives the three DfT Street Manager Open Data AWS SNS topics and
stores their events in D1. It exposes a bearer-token-protected API consumed by
the Streamlit dashboard.

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
8. Verify `https://national-outage-street-manager.<account>.workers.dev/health`.

Use these URLs in DfT Open Data onboarding:

- `https://...workers.dev/street-manager/permit`
- `https://...workers.dev/street-manager/activity`
- `https://...workers.dev/street-manager/section-58`

Configure Streamlit with the Worker origin and the same read token:

```toml
[street_manager]
webhook_url = "https://national-outage-street-manager.<account>.workers.dev"
webhook_token = "the-read-token"
```

The Worker validates the SNS certificate host, signature, exact production
topic ARN and endpoint/topic match before confirming or storing a message.
