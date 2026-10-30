# rental-market-runner

A daily snapshot of public rental listing pages in Kingston, Ontario.

Once a day a GitHub Action opens each public listings page in `sources.json` (once per page, with a few seconds between requests to the same site) and records whether it loaded. Each run's output (the pages and a status file) replaces the previous one on the `latest` branch. Nothing from earlier days is kept.

Only public listing pages are read. Nothing is submitted, and no personal information is collected.
