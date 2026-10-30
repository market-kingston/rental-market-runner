# rental-market-runner

A daily snapshot of public rental listing pages in Kingston, Ontario.

Once a day a GitHub Action opens each public listings page in `sources.json` (once per page, with a few seconds between requests to the same site) records whether it loaded, and extracts the listings it shows (address, bedrooms, bathrooms, rent, availability, status). Each run's output (`listings/`, the pages and a status file) replaces the previous one on the `latest` branch. Nothing from earlier days is kept.

Only public listing pages are read. Nothing is submitted, and no personal information is collected.
