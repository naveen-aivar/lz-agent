# MRA in the dashboard

Source: `shubham-aivar/mra-agent-final`, the review page in `mra/ui/static`. There is no `UI-ALIGNMENT.txt` in that repo. The isolated repository is not changed. The screens here are written for the dashboard.

What is kept: a new assessment (questionnaire and notes), the run list, overview, ratings, activities, validation, proposals, answers and notes, release (confirm, finalise, reopen, delete), outputs, and deck settings.

What changed for the dashboard: no second sign-in (decisions use the signed-in person), no sidebar of its own, eight review steps with one pulse on the open step, and a readiness dial that sweeps only while a score is being worked out.

API: `/agents/mra/api/...` proxies to `https://d3r4ziahwb4a6v.cloudfront.net/api/...`. `GET /api/health` answered 200 on 2026-10-29. Other routes need that site's own Cognito token, not the portal's, so a signed-in portal session does not yet authorize a live call.

Not verified against the live service: an upload, a score, or a file download. The pages were checked in headless Chrome at 1440x900 and 1024x768 against a local stand-in.
