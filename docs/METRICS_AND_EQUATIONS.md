# Metrics, equations and interpretation

This document distinguishes **implemented measurements**, **proposed metric extensions**, and **future evaluation outcomes**. A mathematical definition is not evidence that a metric predicts harmful changes. No composite safety or method-quality score is claimed.

## 1. Measurement units and change direction

The current CLI records descriptive metrics for affected files. `cc_mean` and `cc_max` summarize the blocks returned by Radon, which can include class/method blocks; they are not a stored per-method panel or a whole-project control-flow graph. Method-level matching and local change measurements are future extensions. New/deleted files have absent baselines/post-states, not artificial zero quality.

For a metric with comparable before/after observations:

$$
\Delta m(u)=m_{\mathrm{after}}(u)-m_{\mathrm{before}}(u).
$$

Here $u$ is the declared unit: currently an affected file, or a consistently matched method in a future analysis. For presenting direction only, define $d_m=s_m\Delta m$, with $s_{MI}=-1$ and $s_m=+1$ for complexity/size descriptors. Positive $d_m$ is adverse-oriented metric movement, not confirmed harm.

A proposed threshold sensitivity event is:

$$
I_m(u;a_m,r_m)=\mathbf{1}\left[d_m(u)>0\;\land\;d_m(u)\geq
\max\{a_m,r_m|m_{\mathrm{before}}(u)|\}\right].
$$

Absolute thresholds $a_m$ and relative thresholds $r_m$ would need prespecification and validation. No such quality-rejection threshold is currently used by the CLI. A threshold grid can expose sensitivity but cannot establish practical significance by itself. Human reference patches, task requirements and independently labeled outcomes provide context; they do not make one particular implementation uniquely correct.

## 2. Cyclomatic complexity — implemented block summaries

For a control-flow graph, the conventional definition is:

$$
CC=E-N+2P,
$$

where $E$ and $N$ are edge/node counts and $P$ is the number of connected components. A single connected function has $P=1$. Radon uses Python AST decision-counting rules; the prototype calls its pinned implementation rather than constructing these graphs explicitly. See [Radon's metric definitions](https://radon.readthedocs.io/en/latest/intro.html).

**Use:** identify branching changes and guide relevant boundary/path tests. **Limit:** adding a necessary guard or exception path can raise complexity while improving behavior. File/block aggregates can hide a localized hotspot. Do not classify every positive delta as poor quality.

## 3. Cognitive complexity — proposed, not currently computed

Cognitive complexity targets the difficulty of following a method's control flow, using flow interruptions and eligible nesting increments. It is distinct from cyclomatic complexity. A future implementation should pin a Python analyzer and test it against a declared interpretation of [Sonar's specification](https://www.sonarsource.com/resources/cognitive-complexity/).

It should produce per-method values, preserve method matching across changes, and record unsupported constructs. We do not present a simplified nesting sum as an exact implementation of the full specification. The present charts contain no cognitive-complexity observations.

**Use:** an additional understandability descriptor. **Limit:** it does not establish that a developer understood the method, that a method is correct, or that a change is insecure. Human comprehension evidence would be needed for those interpretations.

## 4. Exception handling — proposed structural profile

A useful starting point is a vector of inspectable indicators rather than an “exception-handling quality percentage”:

$$
\mathbf e(h)=
\left(n_{\mathrm{bare}},n_{\mathrm{broad}},n_{\mathrm{pass-only}},
      n_{\mathrm{reraise}},n_{\mathrm{cleanup}}\right).
$$

For method $h$, proposed counts describe bare handlers, handlers catching broad exception classes, pass-only handler bodies, explicit re-raises, and `finally` cleanup blocks. Symbol resolution is necessary for broad exception types; matching the string `Exception` alone is insufficient. Cleanup using context managers should be recorded separately. Nested function scopes should not be silently double-counted.

The vector does not determine correctness. Catching a broad exception can be justified at a system boundary; logging and re-raising is different from swallowing a failure. More `try` blocks do not establish more robustness. Validation needs tests of expected failures, propagation and cleanup behavior. See the [Python exception-handling semantics](https://docs.python.org/3/reference/compound_stmts.html#the-try-statement).

## 5. Depth of inheritance — proposed and context-dependent

For an explicitly resolved, acyclic class graph, a proposed convention is:

$$
DIT(C)=
\begin{cases}
0, & C\text{ has no non-object base classes},\\
1+\max_{B\in\mathcal B(C)}DIT(B), & \text{all relevant bases are resolved}.
\end{cases}
$$

Here $\mathcal B(C)$ excludes `object`. A missing/imported/dynamic base or a cycle yields **unknown**, not zero. Multiple inheritance uses the longest ancestry path under this chosen convention, not the number of parents or Python's method-resolution-order length. Other DIT conventions differ, so the convention must accompany any result.

The current changed-files-only tool does not resolve whole-repository class hierarchies and does not compute DIT. Python's dynamic classes and [multiple-inheritance rules](https://docs.python.org/3/tutorial/classes.html#multiple-inheritance) make naive AST-only depth unreliable.

**Use:** assess changes to class structure where inheritance is central. **Limit:** deeper inheritance can be intentional framework design; it is a lower-priority feature for many function-oriented Python patches and is not a universal defect predictor.

## 6. Maintainability Index — implemented proxy, not maintenance effort

The installed Radon 6.0.1 code uses the following normalized expression for positive $V$ and $L$:

$$
MI=\operatorname{clip}_{[0,100]}\left[
\frac{100}{171}\left(171-5.2\ln V-0.23G-16.2\ln L
+50\sin\sqrt{2.46C_{\mathrm{rad}}}\right)\right].
$$

$V$ is Halstead volume; $G$ is Radon's total complexity input; $L$ is the logical-line count supplied by `mi_parameters`; $C_{\mathrm{rad}}$ is the comment percentage converted to radians. This is the **pinned code's expression**, not a claim that every published MI variant uses the same constants or inputs. The CLI uses `multi=True`, so Radon's multiline-string counting affects the comment input. See [Radon 6.0.1 source](https://github.com/rubik/radon/blob/v6.0.1/radon/metrics.py).

In that code, nonpositive Halstead volume or line count returns 100. Several tiny demo methods reach this boundary. An MI of 100 is not 100% quality, and a lower value after a documentation edit is not proof of reduced maintainability.

**Use:** retain as one descriptive summary. **Limit:** MI already combines complexity, size and comment information; it must not be treated as an independent “non-complexity” outcome or added to its inputs as if they were independent harms. Maintenance time, comprehension effort and change reliability require separate outcome studies.

## 7. Quality of developed methods — proposed evidence profile

There is no universally justified scalar “method quality” score in this project. A future profile could retain:

$$
\mathbf q(h)=\left(CC(h),Cog(h),Depth(h),Length(h),
                 \mathbf e(h),Warnings(h),Tests(h),Review(h)\right).
$$

This is a structured evidence record, not an ordered score or a sum. Test and review fields remain unknown when not collected. Matching identity, location, new/deleted methods and missing measurements need explicit accounting. Functional correctness, security, readability and maintainability are different dimensions; a convenient weighted sum would require its own validation.

Prioritize localized CC/cognitive/nesting measurements, observable exception patterns and independently supported outcomes before attempting a composite score. Parameter counts or docstring presence can add context but do not prove API clarity or method quality.

## 8. Current selection policy — implemented at file level

For an affected Python file $f$:

$$
g(f)=\mathbf{1}\left[S(f)=1\;\lor\;C(f)\geq20\;\lor\;U(f)=1\right].
$$

$S(f)$ indicates recognized sensitive context in either snapshot, $C(f)$ counts added-plus-removed source lines, and $U(f)$ indicates a context-parse failure. Adaptive mode requests Bandit when $g(f)=1$; otherwise it records a skipped check. Full mode requests Bandit on all affected Python files. The 20-line value is an illustrative fixed rule, not a learned risk tolerance.

## 9. Timing and diagnostic-output comparison — implemented

For per-case measured check times after warming both modes:

$$
S_T(p)=100\left[1-
\frac{\operatorname{median}_{r}T_{\mathrm{adaptive},r}(p)}
     {\operatorname{median}_{r}T_{\mathrm{full},r}(p)}\right].
$$

Selection and scanner subprocess startup are included; shared snapshot preparation, warm-up and report generation are excluded. A negative value means adaptive checking was slower. At cohort level, distinguish the median of per-patch reductions from the reduction in the sum of per-patch median times; they answer different questions. Three timing repetitions are not independent patches.

For comparable newly observed diagnostic multisets:

$$
P_D=\frac{\sum_{d}\min\{n_A(d),n_F(d)\}}{\sum_dn_F(d)},
\qquad \sum_dn_F(d)>0.
$$

$n_A(d)$ and $n_F(d)$ are diagnostic multiplicities under adaptive and full modes. Diagnostic identity includes source/rule context and matching is heuristic. Empty or incomplete full references have undefined preservation fractions. This quantity describes scanner-output preservation, not vulnerability recall or assurance confidence. The current synthetic assert example demonstrates that it can be below 1.

## 10. Future resource-allocation objective — not implemented or validated

A prospective evaluation could learn a policy that selects verification actions $\mathcal A$ under a measured budget:

$$
\max_{\mathcal A}\;\mathbb E[Y(\mathcal A)\mid X]
\quad\text{subject to}\quad
\sum_{a\in\mathcal A}\widehat c(a)\leq B.
$$

$Y$ must represent independently supported useful outcomes, $X$ available pre-selection evidence, $\widehat c$ estimated checking cost, and $B$ the stated budget. This equation specifies a research objective, not the current rule-based implementation. Scanner counts alone cannot validate it. Calibration, uncertainty, operational failures and the cost of gathering features must be part of that evaluation.
