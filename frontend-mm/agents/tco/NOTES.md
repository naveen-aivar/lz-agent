# TCO in the dashboard

Source: `aivar-tech/ingram-ai-tco-agent`, branch `feature/develop`, folder `app/ui` (plain JavaScript, its own sidebar and a light/dark switch).
The screens here are written for the dashboard, not generated. The isolated repository is not changed.

What is kept: the assessment list, a new assessment (Excel file, optional settings, migration credits when the service says to ask), the question the service is waiting on, results, the pricing-calculator link, migration credits, downloads and the timeline. The access key stays in this browser tab.

What changed for the dashboard: no API address to type (calls go to `/agents/tco/api/...`), no dark theme, five steps in everyday words, one pulse on the step that is running, and a short fade when a tab or a timeline row appears.

The API is REST API `tco-dev-api` (`sdcr1ipp07`) in account 831493647146, stage `dev`. The dashboard does not call it directly. CloudFront sends `/agents/tco/api/` to a function in the doc-ex account, which checks the signed-in person's Cognito token and then adds the access key from Secrets Manager (`ingram-mm-dashboard/tco-access-key`). There is no access-key page. The workbook upload still goes to bucket `tco-dev-data-831493647146`.

The live site does not proxy this until the dashboard is deployed again. The deck is a download, not an in-page preview, because the dashboard does not frame documents from another site.

Not verified: a real upload, a running assessment, or the browser at 1440 and 1024.

Also in the dashboard (UI only; the service is `ingram-ai-tco-agent`): the Microsoft licensing comparison (an optional section on a new assessment when the service reports `features.licensing == "ask"`: Software Assurance share or a Microsoft License Statement upload, optional prices, one thread per core; and a results card with both scenarios side by side, Microsoft's cost kept apart), the MAP-eligible estimate under the pricing calculator card (a second link, or a note when the main estimate already qualifies), and one notes box on the question form when the service asks for its own. The statement goes straight to the data bucket by a second presigned upload, like the inventory.

Parity with the isolated page (checked 2026-10-30; the isolated page `app/ui` of `ingram-ai-tco-agent` is frozen, this is now the only place that changes): the settings of a new assessment are grouped as there (`parameters.ts`, `settings-fields.tsx`: region and pricing with payment option, licensing for Windows, RHEL and SQL Server, database assumptions, utilization, and "answer automatically") and have no on-premises discounts; the results show no cost today and no saving (`onprem_annual_cost` is not read); the calculator card (`calculator-card.tsx`) has the Verified or Unverified badge and sentence, the estimate against Transform's figure, the pricing choices to review and the groups that do not add up; the MAP card (`map-card.tsx`) has the table, totals and notes; the timeline lists what was sent to AWS Transform; the licensing comparison, the MAP-eligible estimate and the single notes box are as on the isolated page. Different on purpose: five everyday steps instead of six technical ones, no dark theme, no API address or access-key page, and the deck is drawn from the PDF in the page.
