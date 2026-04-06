# Database & Persistence (JPA/Hibernate)

## N+1 Prevention — CRITICAL

```java
// ❌ FATAL: N+1 query
items.stream().map(i -> repo.findById(i.getId()).orElse(null)); // N queries!

// ✅ Batch query + Map
List<String> ids = items.stream().map(Item::getId).distinct().toList();
Map<String, Entity> map = repo.findByIdIn(ids).stream()
    .collect(Collectors.toMap(Entity::getId, Function.identity())); // 1 query
items.stream().map(i -> map.get(i.getId()));
```

**Rules:**
- ✅ `findByIdIn(List<String> ids)` for batch loading
- ✅ `Map<String, Entity>` for O(1) lookup
- ✅ Filter at DB level, not Java streams after loading
- ✅ `EXISTS (SELECT 1 ...)` instead of `JOIN + DISTINCT`
- ✅ `@EntityGraph` or `JOIN FETCH` for lazy loading N+1
- ✅ Early return for empty lists

## Concurrency — Locking

```java
// ✅ Default: Optimistic Locking
@Entity
public class OrderEntity {
    @Version
    private Long version;
}

// ✅ Financial/Inventory: Pessimistic Locking
@Lock(LockModeType.PESSIMISTIC_WRITE)
@Query("SELECT o FROM OrderEntity o WHERE o.id = :id")
Optional<OrderEntity> findByIdForUpdate(@Param("id") String id);
```

## Database Design

- ✅ Index for columns in `WHERE` or `JOIN`
- ✅ Soft Delete (`isDeleted` / `deletedAt`) for important data
- ✅ `@CreatedDate`, `@LastModifiedDate` for audit fields

## Transaction Rules

- ✅ `@Transactional` in Application Services (never Controllers)
- ✅ ALWAYS for multi-DML operations
- ❌ **NEVER** call `@Transactional` method internally in same class (proxy bypass)

```java
// ❌ BAD: Internal call → proxy bypassed → no transaction!
@Service
public class OrderServiceImpl {
    @Transactional
    public void createOrder(OrderDto dto) {
        this.updateInventory(dto); // ❌ Not transactional!
    }
    @Transactional
    public void updateInventory(OrderDto dto) { ... }
}

// ✅ GOOD: Inject separate service
@Service
@RequiredArgsConstructor
public class OrderServiceImpl {
    private final InventoryService inventoryService;
    @Transactional
    public void createOrder(OrderDto dto) {
        inventoryService.updateInventory(dto); // ✅ Proxy works
    }
}
```

## JPQL/SQL — Text Blocks

```java
// ✅ Java 21 text blocks
@Query("""
    SELECT u FROM UserEntity u
    WHERE u.email = :identifier OR u.username = :identifier
    """)
Optional<UserEntity> findByEmailOrUsername(@Param("identifier") String identifier);

// ❌ String concatenation — NEVER
```
