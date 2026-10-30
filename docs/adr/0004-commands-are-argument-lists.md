# ADR 0004: Commands are argument lists, never a shell

**Status:** accepted

A benchmark command is a list of strings started directly. There is no shell, so quoting mistakes and injection through arguments are not possible; pipes and globs are not available. Use a small script if you need them.

**Consequence:** Python callables are imported and called in process; that is code execution by design and is documented in the security policy.
