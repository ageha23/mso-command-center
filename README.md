# Polsinelli MSO Command Center

Live site: `https://<your-github-username>.github.io/<repo-name>/` (fill in once
GitHub Pages is enabled — see below).

This is the Law Firm MSO Command Center (heat map, decision tool, fee model,
legislation tracker, playbook, deal builder, BD pipeline), plus a **Daily
Ethics Watch** tab that updates itself automatically.

## How the daily update works

- `.github/workflows/daily-update.yml` runs on GitHub's own servers every day
  at 11:00 UTC (~6:00 AM Central) — it does **not** depend on any chat session
  being open.
- It runs `scripts/update_watch.py`, which searches:
  - **CourtListener** (free case-law search API) for recent opinions
    mentioning MSO / nonlawyer ownership / Rule 5.4 / fee-splitting / corporate
    practice of law.
  - **Google News RSS** for recent articles and guidance on the same topics.
- New, not-already-seen items (deduped by URL) are appended to
  `data/ethics-watch.json`. The file is capped at the 150 most recent items so
  it stays small.
- If anything changed, the workflow commits and pushes automatically. Since
  GitHub Pages serves straight from the `main` branch, the live site updates
  within a minute or two of the push — no manual step required.
- The page (`index.html`) fetches `data/ethics-watch.json` at load time and
  renders it under the **Daily Ethics Watch** tab, with a "last checked"
  timestamp.

Items here are **not** the same as the hand-curated **Legislation & Rule
Tracker** tab — that one stays manually maintained (edit the `LEG` array near
the top of the `<script>` block in `index.html`) so a bad automated match
never overwrites vetted content. Treat Ethics Watch as a leads list to review,
not a finished product — verify anything before relying on it or sharing it
with a client.

## One-time setup

1. **Create the repo** (if not already done) and push these files to the
   `main` branch.
2. **Enable GitHub Pages**: repo Settings → Pages → Source → "Deploy from a
   branch" → Branch: `main`, folder `/ (root)` → Save. The site will be live
   at `https://<username>.github.io/<repo>/` within a few minutes.
3. **Confirm Actions can push**: Settings → Actions → General → Workflow
   permissions → "Read and write permissions". (The workflow already requests
   `contents: write`; this setting must also allow it, or the daily commit
   will fail silently with a permissions error you'll see in the Actions log.)
4. **Run it once manually** to seed data instead of waiting for tomorrow's
   cron: Actions tab → "Daily Ethics Watch update" → "Run workflow".

## Adjusting what gets searched

Edit the `KEYWORDS` list and the CourtListener query terms at the top of
`scripts/update_watch.py`. Keep the scope narrow — broadening it will pull in
more noise per the tradeoff discussed when this was set up (MSO /
nonlawyer-ownership ethics only, not general legal ethics).

## Local preview

Any static file server works, e.g.:

```
python3 -m http.server 8000
```

then open `http://localhost:8000/`. (A handful of the tool's inputs — the
BD pipeline data, deal builder — reset on reload since there's no backend;
that matches the original file's behavior.)
