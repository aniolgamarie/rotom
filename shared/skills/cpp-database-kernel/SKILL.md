---
name: cpp-database-kernel
description: Use for C++ database-kernel changes involving ownership, concurrency, transactions, WAL, recovery, persistence, storage compatibility, or hot-path performance.
---

# C++ Database Kernel

Before editing, identify the relevant:

- ownership and lifetime;
- lock domain and lock order;
- atomics and memory ordering;
- thread, coroutine, callback, and shutdown boundaries;
- transaction and recovery boundaries;
- WAL, checkpoint, and replication implications;
- persistent-format and backward-compatibility impact;
- iterator, pointer, reference, and handle invalidation;
- partial initialization and failure cleanup;
- hot-path allocation and algorithmic complexity.

Use one writer only.

For small bounded changes, execute directly.

For substantial interface, behavior, format, or cross-module changes, first
identify the affected contracts and verification requirements.

For complex implementation, split the work into bounded stages and follow the
current project's explicitly configured process and permissions. Check the
result independently against the contracts and final diff. Report unavailable
checks, missing prerequisites, and unverified risks; do not invent capabilities,
require installation of an external platform, or bypass the project's
permission boundary.

Do not combine correctness fixes with unrelated modernization.

Before completion:

1. build the affected target;
2. run focused tests;
3. run sanitizers, stress tests, or benchmarks when relevant;
4. inspect the final diff;
5. report unverified risks once, then stop.

For concrete evidence and failure-path checks, read the relative
[database contracts reference](references/database-contracts.md). Apply it to
the project's own transaction, persistence, and lifecycle contracts; it does not
prescribe a universal engine protocol or enable an execution service.
