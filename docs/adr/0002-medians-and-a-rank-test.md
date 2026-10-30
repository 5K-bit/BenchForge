# ADR 0002: Compare medians with a rank test

**Status:** accepted

Timing samples are right-skewed with occasional large outliers, which break a t-test on means. The verdict uses the ratio of medians plus a Mann-Whitney U test, and a seeded bootstrap interval for the ratio.

**Consequence:** The test has less power than a t-test on clean, normal data. With fewer than 5 samples per side no test is run and the verdict is inconclusive.
