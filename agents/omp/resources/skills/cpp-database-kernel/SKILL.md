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

For substantial interface, behavior, format, or cross-module changes, use
OpenSpec.

For complex implementation requiring multiple independent stages, use the
saved kernel-change workflow. Do not invent an ad-hoc workflow.

Do not combine correctness fixes with unrelated modernization.

Before completion:

1. build the affected target;
2. run focused tests;
3. run sanitizers, stress tests, or benchmarks when relevant;
4. inspect the final diff;
5. report unverified risks once, then stop.
