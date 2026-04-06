# System Design & Concurrency

## Messaging (Redis Streams / SQS)

- ✅ Design **Idempotent Consumer** — prevent duplicate processing
- ✅ Always configure **Dead Letter Queue (DLQ)** for failed messages
- ✅ Use unique `messageId` for deduplication

## Redis / Caching

- ✅ **Cache-Aside Pattern:** check cache → miss → load DB → put cache
- ✅ **All keys MUST have TTL** — no infinite cache
- ✅ Configurable TTL per entity type via `application.yml`

## Background Jobs

- ✅ Use **ShedLock** or distributed lock for multi-instance jobs
- ✅ Prevent duplicate job execution across cluster

## Multi-threading

```java
// ✅ Virtual Threads (Java 21) for I/O-bound tasks
@Bean
public ExecutorService virtualThreadExecutor() {
    return Executors.newVirtualThreadPerTaskExecutor();
}

// ✅ Custom pool for CompletableFuture
CompletableFuture.supplyAsync(() -> fetchData(), virtualThreadExecutor);

// ❌ Default ForkJoinPool — NEVER
CompletableFuture.supplyAsync(() -> fetchData()); // Uses common pool!
```

## Concurrency Checklist

- [ ] Race conditions checked in "find-or-create" flows
- [ ] Idempotency: repeated requests = no duplicate side effects
- [ ] Long-running ops: batch writes, not per-item
- [ ] External input: validate/handle bad input (no NPE/ClassCast)
- [ ] List endpoints: paginated or explicitly bounded
