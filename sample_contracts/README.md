# ClauseGuard Benchmark Test Contracts Suite

This directory contains 5 realistic fictional contracts used to test, calibrate, and validate the ClauseGuard triage agent against its 7-category risk rubric.

## Contracts Overview

| File | Contract Type | Key Tested Risks | Expected Flags |
|---|---|---|---|
| `01_freelance_developer_agreement.txt` | Freelance Developer Agreement | Pre-existing IP assignment, one-way uncapped indemnity, 18-month non-compete, invoice forfeiture | 4 flags |
| `02_saas_subscription_agreement.txt` | Enterprise SaaS Terms | 25% price escalation on auto-renewal, unilateral term modifications, $0 provider liability cap, mandatory arbitration & jury waiver | 4 flags |
| `03_commercial_office_lease.txt` | Commercial Office Lease | Uncapped capital improvement pass-throughs, 100% accelerated rent liquidated damages, unannounced landlord entry | 3 flags |
| `04_consulting_services_nda.txt` | Non-Disclosure Agreement | Shifted burden of proof on public info, perpetual confidentiality + non-solicitation, unilateral legal fee shifting | 3 flags |
| `05_safe_standard_vendor_agreement.txt` | Standard Vendor Agreement | Balanced mutual terms, capped liability (12 mo fees), mutual indemnity, standard court venue | 0 flags (Negative Control) |

## Ground Truth Answer Key
See `answer_key.json` for full details including risk categories, risk levels, rationales, and drafted counterparty questions.
