# ADR 0003: Need both a threshold and significance

**Status:** accepted

A very stable benchmark can show a statistically significant 1% change that nobody cares about; a noisy one can show a 30% change that is not significant. A regression must exceed the threshold (default 10%) and p < alpha (default 0.01). Small real differences are reported as unchanged with a note.

**Consequence:** Teams with strict budgets should lower the threshold, and say so in their CI command.
