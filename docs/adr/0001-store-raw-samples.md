# ADR 0001: Store raw samples, not summaries

**Status:** accepted

Result files keep every sample in nanoseconds. Summaries are recomputed on load, so no stored statistic can disagree with the data, and any later analysis (another test, another threshold) can be run on old results.

**Consequence:** A file with 30 samples is larger than one with a median. At the caps (100,000 samples per benchmark) that is still a few hundred KiB.
