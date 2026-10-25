# Research scope

## Supported by this repository

- An executable local prototype for static verification prioritization.
- Reproducible before/after diagnostic reports with explicit operational status.
- A transparent, illustrative selection policy and a full-check reference mode.
- A self-contained synthetic demonstration of observed warnings, warning attribution, skipped evidence and timing.
- Automated tests of source non-execution, checkout preservation, input isolation, warning matching, operational failures and report behavior.

The tool's security-sensitive context matching is syntactic. It is not a calibrated risk model. The synthetic cases are engineering examples, not a representative evaluation dataset. The included eval example demonstrates a scanner warning, not an independently verified exploit.

## Evidence needed for stronger research claims

1. Versioned public patch cohorts with explicit provenance and inclusion/exclusion accounting.
2. Independently established defect, vulnerability or practical-maintainability outcomes, with annotation or test evidence.
3. A frozen development/evaluation protocol that prevents repository/task leakage and test-set tuning.
4. Cost-matched comparisons against full checks, size-based selection, random selection and justified reference methods.
5. Measurements of problems caught/missed, false alarms, operational failures, checking cost and uncertainty.
6. Separate measurement of human review time if claiming reviewer-effort savings.

Keep imported datasets and empirical experiments explicitly versioned and attributable. Do not present synthetic scanner results as new findings about real AI-generated patches. The current source distribution makes no dataset-prevalence or immigration-eligibility claims.

## Planned framework components

The implemented components are patch intake, static context/quality inspection, selective security scanning and evidence reporting. Independent functional verification, behavioral completeness, calibrated confidence, acceptance decisions and validated joint quality/security assurance are outside the current implementation.
