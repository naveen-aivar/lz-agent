# Software Requirements Specification: Billing Dispute Assistant

| Field | Value |
|---|---|
| Document | SRS - Billing Dispute Assistant, Northbridge Cloud Distribution |
| Version | 1.0 |
| Status | Approved for solution design |
| Date | 2026-10-05 |
| Owner | Billing Operations Lead, Northbridge Cloud Distribution |
| Prepared by | Discovery team |

## 1 Introduction

### 1.1 Purpose
This document specifies the requirements for the Billing Dispute Assistant (the "system"), an AI-assisted tool that helps Northbridge Cloud Distribution ("Northbridge") billing agents investigate and resolve billing disputes raised by partner resellers and end customers. It is the input to solution design.

### 1.2 Scope
Northbridge resells AWS to partner resellers and end customers. Today, a dispute ticket requires an agent to manually compare monthly AWS billing files (cost and usage report files and discount breakdowns), Northbridge invoices issued from the LedgerOne ERP, and the partner agreement. Mean time to resolution (MTTR) is about 20 days.

**In scope**
- Monthly ingestion of AWS billing files and nightly import of LedgerOne invoices.
- Dispute intake through the system's web UI and through the HelpTrack ticketing webhook.
- Retrieval and comparison of relevant line items, AI-drafted explanation and recommended resolution, agent review, edit and approval, and post-back to HelpTrack.
- Audit trail, search over past disputes, dashboard, notifications and PDF attachment text extraction.

**Out of scope**
- Issuing credit notes or changing invoices in LedgerOne.
- Automatic posting of responses without agent approval.
- Customer-facing access to the system.
- Languages other than English.
- Multi-Region or multi-AZ deployment during the pilot.

### 1.3 Definitions and acronyms
| Term | Meaning |
|---|---|
| CUR | AWS cost and usage report files (parquet or CSV) |
| Discount breakdown | Monthly file detailing discounts, credits and commitments applied per account |
| Dispute | A customer or partner challenge to a billed amount, tracked as a HelpTrack ticket |
| MTTR | Mean time to resolution, from ticket creation to response posted and ticket closed |
| HelpTrack | Northbridge's ticketing system |
| LedgerOne | Northbridge's ERP, source of invoices |
| Northbridge SSO | Corporate identity provider (SAML 2.0) |
| RPO / RTO | Recovery point / recovery time objective |

### 1.4 References
- Discovery workshop notes: Billing Operations workshop (2026-08-18), InfoSec and Architecture workshop (2026-09-02), Finance and Audit workshop (2026-09-09).
- Northbridge Information Security Policy, data classification standard "Confidential-Financial".
- HelpTrack REST API and webhook documentation; LedgerOne nightly export specification.

## 2 Overall description

### 2.1 Product perspective
The system is a new, standalone application that sits between HelpTrack (system of record for tickets), LedgerOne (system of record for invoices) and the monthly AWS billing files. It does not replace either system. Agents continue to communicate with partner resellers and customers through HelpTrack.

### 2.2 User classes and characteristics
| User class | Description | Volume |
|---|---|---|
| Billing agent | Investigates disputes, reviews and approves AI drafts. Domain experts, not technical. | ~40 named users, ~25 concurrent at peak |
| Billing Operations Lead | Monitors dashboard, reviews quality, manages roles. | 3 users |
| Finance auditor | Read-only access to disputes, drafts and audit trail. Must not see margins. | ~6 users |
| System integration | HelpTrack, LedgerOne and file sources acting through service accounts. | n/a |

### 2.3 Operating environment
The system runs on AWS in a single Region, us-east-1, across two Availability Zones for production (the landing-zone default for a 99.5% target); non-production may run single instances. No disaster-recovery Region is required for the pilot. Users access it from corporate networks and VPN using modern browsers.

### 2.4 Design and implementation constraints
- C-01: AWS-native managed services only; no self-managed software on virtual machines unless no managed option exists.
- C-02: Generative AI shall be provided only through Amazon Bedrock.
- C-03: The user interface and all generated content are in English only.
- C-04: All data, including backups and logs, shall remain in us-east-1.
- C-06: Production zonal resources shall span the two Availability Zones the landing zone provides; no second Region is used.
- C-05: Per Northbridge InfoSec, data stores shall use private networking only, encryption at rest and in transit, and authentication through Northbridge SSO.

### 2.5 Assumptions and dependencies
- Billing files are delivered by Northbridge staff or automation to a landing area by the 3rd business day of each month.
- HelpTrack exposes an outbound webhook and a REST API with OAuth client-credentials; LedgerOne produces the nightly export reliably.
- Northbridge SSO can supply agent role through SAML attributes.
- Bedrock model access for the chosen model is approved for Northbridge's account in us-east-1.

## 3 Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | The system shall ingest monthly AWS billing files delivered to a landing area: CUR (about 30 GB per month, compressed parquet or CSV) and discount breakdown (up to 8 GB per month), validate them and make them queryable. | Must |
| FR-02 | The system shall import the nightly LedgerOne invoice export (CSV, about 200 MB) and reject or quarantine malformed files with an alert. | Must |
| FR-03 | The system shall let a billing agent create a dispute in the web UI, capturing partner, billing period, invoice reference and disputed amount. | Must |
| FR-04 | The system shall receive disputes from the HelpTrack outbound webhook and create or update the matching dispute, ignoring duplicates. | Must |
| FR-05 | The system shall retrieve the billing line items, invoice lines and partner agreement terms relevant to a dispute and present a side-by-side comparison highlighting differences. | Must |
| FR-06 | The system shall generate an explanation and recommended resolution for a dispute using a generative AI model, with each statement citing the supporting line items or agreement clauses. | Must |
| FR-07 | The system shall let the agent review, edit, approve or reject a draft and request regeneration; nothing is posted without explicit approval. | Must |
| FR-08 | The system shall post the approved response to the HelpTrack ticket through its REST API and record the outcome, retrying on failure. | Must |
| FR-09 | The system shall record an immutable audit event for every AI draft (inputs referenced, model, prompt version, output) and every agent action. | Must |
| FR-10 | The system shall provide search over past disputes by partner, period, amount, status and free text. | Should |
| FR-11 | The system shall provide a dashboard of dispute status, ageing and MTTR, filterable by period and partner. | Should |
| FR-12 | The system shall enforce role-based access (agent, Billing Operations Lead, finance auditor) and hide margin fields from read-only roles. | Must |
| FR-13 | The system shall send an email notification to the assigned agent when a draft is ready. | Should |
| FR-14 | The system shall extract text from PDF invoices attached to disputes and make it available to comparison and drafting. | Could |

## 4 Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Volume | About 200 disputes per week, peaking at 60 per day at month-end; about 1,500 AI drafts per month (including regenerations). |
| NFR-02 | Performance | UI p95 response time under 2 s for page loads and searches. |
| NFR-03 | Performance | AI draft generation p95 under 45 s from request to draft displayed. |
| NFR-04 | Performance | Monthly billing files ingested and queryable within 4 h of arrival; nightly invoice import completed within 30 min. |
| NFR-05 | Availability | 99.5% during business hours (Monday-Friday, 07:00-19:00 US Eastern); two Availability Zones in us-east-1 for production. |
| NFR-06 | Recovery | RPO 24 h and RTO 8 h. |
| NFR-07 | Retention | Audit trail and billing data retained 7 years. Raw billing files move to lower-cost storage after 90 days and remain retrievable. |
| NFR-08 | Security | Northbridge SSO with MFA enforced by the identity provider; least-privilege access for users and services; encryption at rest and in transit; no publicly accessible data stores; security-relevant events logged. |
| NFR-09 | Scalability | Support 3x growth in disputes, users and file volumes within 2 years without redesign. |
| NFR-10 | Observability | Central logs, metrics and alarms for ingestion, integrations, AI latency and errors; alarms routed to the operations team. |
| NFR-11 | Cost | Operate within the pilot budget ceiling of USD 6,000 per month; prefer serverless and managed services, and Graviton-based compute where compute is needed. |
| NFR-12 | Compliance | Handles financial data; personal data limited to names and email addresses of agents and partner contacts; no customer end-user personal data stored. |
| NFR-13 | Maintainability | Infrastructure defined as code; deployments repeatable across development, test and pilot environments. |

## 5 External interface requirements

| Interface | Requirement |
|---|---|
| User interface | Responsive web application for current versions of Chrome, Edge, Firefox and Safari; English only; accessible per WCAG 2.1 AA for core workflows. |
| HelpTrack | REST API for reading and updating tickets and posting responses; outbound webhook for new and updated disputes. OAuth 2.0 client-credentials authentication. Webhook payloads shall be authenticated. |
| LedgerOne | Nightly CSV export (about 200 MB) delivered by LedgerOne as an SFTP push to a Northbridge-controlled endpoint provided by the system, authenticated by key. |
| Northbridge SSO | SAML 2.0; role and name supplied as assertion attributes. |
| Email | Outbound notification email from a Northbridge-domain sender address; delivery mechanism left to design. |
| AWS billing files source | Files placed in the landing area by Northbridge staff or automation; CUR as parquet or CSV, discount breakdown as CSV. |

## 6 Data requirements

| Entity | Description | Indicative volume |
|---|---|---|
| Dispute | Ticket reference, partner, period, amount, status, assignee, timestamps | ~870 per month; ~10,500 per year |
| BillingLineItem | Normalised CUR and discount lines | CUR ~30 GB and discount ~8 GB per month (~455 GB per year raw) |
| Invoice | LedgerOne invoice headers and lines | ~200 MB per nightly export |
| Partner | Partner reseller, agreement terms, contacts | ~350 partners |
| AIDraft | Draft text, citations, model, prompt version, agent decision | ~1,500 per month |
| AuditEvent | Immutable record of drafts and agent actions | ~25,000 per month |

- **Growth:** 3x within 2 years (NFR-09). Seven-year retention implies several terabytes of billing data.
- **Classification:** all entities are Confidential-Financial.
- **Retention:** 7 years for all entities; raw files to lower-cost storage after 90 days (NFR-07). Audit events shall be tamper-evident.

## 7 Acceptance criteria

| ID | Criterion |
|---|---|
| AC-01 | During a 3-month pilot, MTTR falls from about 20 days to 5 days or less. |
| AC-02 | At least 80% of AI drafts are approved with minor edits (under 20% of text changed). |
| AC-03 | At least 95% of cited line items in sampled drafts are verified correct by the Billing Operations Lead. |
| AC-04 | Monthly files (38 GB) are ingested and queryable within 4 h in two consecutive months. |
| AC-05 | UI p95 under 2 s and AI draft p95 under 45 s at 25 concurrent users during month-end load testing. |
| AC-06 | Every AI draft and agent action is traceable in the audit trail; zero gaps in an auditor review. |
| AC-07 | Security review confirms private data stores, encryption, SSO enforcement and margin hiding for the finance auditor role. |
| AC-08 | Restore test demonstrates recovery within RPO 24 h and RTO 8 h. |

## 8 Open issues

| ID | Issue | Owner |
|---|---|---|
| OI-01 | Selection of the Amazon Bedrock model and acceptable data handling terms to be confirmed with InfoSec. | Billing Operations Lead / InfoSec |
| OI-02 | Production availability target and multi-AZ requirement after the pilot to be decided. | Head of Billing Operations |
| OI-03 | Confirmation of the HelpTrack API rate limits and webhook retry behaviour. | HelpTrack platform owner |
| OI-04 | Whether partner agreements are available as structured data or only as PDF documents. | Partner Management Lead |
