# Next experiment: verification effectiveness on independently labeled outcomes

**Status: proposed, not executed.** This protocol is intended to strengthen the scientific contribution beyond integrating scanners or describing metric movement. It cannot guarantee acceptance. The current 60-patch run has too few new diagnostics and no independent harm labels to validate security effectiveness.

## Central question

Can an evidence-aware verification policy retain an acceptable level of independently confirmed problem detection while reducing measured verification cost, compared with efficient alternatives under the same budget?

The method must define its decision procedure, inputs, missing-evidence behavior and resource constraint. Any learned component, threshold or calibration must use development data only. A fixed heuristic is a baseline, not an assumed novel algorithm.

## Data and independent labels

1. Assemble a separately versioned set of real generated patches with historical functional-test evidence and independently supported additional failures or vulnerabilities. Require issue/test/exploit/maintainer evidence; a scanner message is not its own ground truth.
2. Have domain reviewers assess a prespecified rubric, blinded to ranking outputs when feasible; report disagreements, adjudication and unknown outcomes. Do not force uncertain examples into positive or negative labels.
3. Freeze splits by repository and task before tuning. Keep task duplicates across models in the same split. Reserve an untouched evaluation cohort.
4. Add stress tests constructed from documented real security fixes if useful, but label them as constructed regressions. They are not actual AI-generated patches and must remain a separate cohort.
5. Define the negative/reference population carefully. Absence of a reported failure is not proof of absence of a problem. Document the verification procedure used for reference labels.

## Baselines and method ablations

Compare the proposed policy with full verification, random budget allocation, size-based prioritization, the current fixed context/churn rule, and relevant AST-based references. Include an efficiently implemented full baseline: batch scanner startup and reusable base-snapshot results where appropriate. Apply equivalent caching and batching opportunities to all methods. Otherwise a speed claim may mostly reflect avoidable subprocess overhead.

Ablate quality descriptors, sensitive-context signals, missing-evidence escalation and each proposed verification stage. More metric columns do not establish that those columns improve decisions; show their incremental utility beyond patch size.

## Outcomes and costs

Primary outcomes should include independently confirmed problems detected/missed, false escalations, unknown/abstained cases and measured total verification cost. Report precision/recall only where the reference labels and denominators support them:

$$
\mathrm{Recall}=\frac{TP}{TP+FN},\qquad
\mathrm{Precision}=\frac{TP}{TP+FP}.
$$

A zero denominator is undefined. Distinguish detector-output preservation from these independently labeled quantities. Analyze quality/maintainability and security outcomes separately before discussing joint utility. Include acquisition, feature extraction, selection, verification and operational-failure costs. Human review cost requires a study with reviewers rather than machine runtime as a substitute.

For no observed misses among $n$ independent positive cases, a one-sided exact binomial upper bound on the miss probability is:

$$
u_{1-\alpha}=1-\alpha^{1/n}.
$$

For example, at $\alpha=0.05$, at least 59 independent positive cases with zero misses are needed for this bound to be below 5%. This is an illustration of sample planning, not a guarantee or the current sample's result. Correlated repository/task cases violate the independence assumption and require a different uncertainty analysis. An acceptable risk tolerance must be justified by the intended use case, not selected after inspecting results.

## Decision criteria

Prespecify the budget, comparison, acceptable detection loss, uncertainty procedure and test sample plan. Report failed hypotheses, unfavorable baselines and policy misses. If an efficient full baseline performs just as well at similar cost, the adaptive claim is not supported. A negative result can still contribute a well-designed empirical study, but the title and conclusion must match it.

The potential contribution is a validated decision procedure with actionable evidence, not merely a larger collection of conventional metrics. No dataset labels, external adoption, expert endorsements or evaluation outcomes are claimed by this proposed protocol.
