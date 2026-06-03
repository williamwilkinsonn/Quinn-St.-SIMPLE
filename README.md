# Quinn Street Lead Generator

This is a volume-first lead generator for Quinn Street. It helps you:

- search markets for likely retail partners using Google Places
- dedupe overlapping searches
- enrich leads with website and email/contact-page discovery
- export the lead list to CSV
- keep the discovery profile aligned to Quinn Street's premium boutique positioning

## What It Pulls

From Google Places:

- business name
- address
- phone
- website
- Google Maps link
- rating and review count
- matched search terms

From website enrichment:

- direct emails when they are publicly exposed
- extra emails when multiple are found
- likely contact/about/wholesale pages when no direct email is visible

## Setup

1. Copy `.env.example` to `.env`
2. Add your Google Places API key to `.env`
3. Start the server:

```bash
cd "/Users/williamwilkinson/Documents/New project/quinn_street_leads"
python3 server.py
```

4. Open [http://127.0.0.1:8035](http://127.0.0.1:8035)

## Notes

- This app uses the Google Places API (New) `places:searchText` endpoint.
- It is optimized for volume-first discovery, not final market scoring.
- Google Places does not provide a general business email field, so email collection comes from public website pages.
- Search queries work best with Quinn Street-aligned retail terms like `baby boutique`, `children's boutique`, `baby clothing store`, `children's clothing store`, `newborn boutique`, `gift boutique`, `maternity boutique`, and `toy boutique`.

## Quinn Street Fit Signals

The current defaults are shaped by the public Quinn Street site and brand story:

- premium baby essentials with giftable appeal
- soft bamboo / organic-cotton-adjacent comfort positioning
- swaddles, sleepers, rompers, accessories, and matching sets
- stylish, cozy, heirloom-quality messaging
- family-founded brand story and boutique-friendly merchandising

## Suggested Next Upgrade

When you are ready for phase two, the natural next version is a scoring layer with fields like:

- market
- neighborhood quality
- website quality
- retailer fit
- premium positioning
- multi-location presence
- outreach readiness
