# Advanced Refactoring — AOP & Custom Annotations

Use AOP to separate cross-cutting concerns: Logging, Validation, Audit, Performance.

## @TrackAction Pattern

```java
// Custom annotation
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface TrackAction {
    String value() default "";
}

// AOP Aspect — auto log + measure performance
@Aspect
@Component
@Slf4j
public class TrackActionAspect {

    @Around("@annotation(trackAction)")
    public Object track(ProceedingJoinPoint joinPoint, TrackAction trackAction) throws Throwable {
        String method = joinPoint.getSignature().toShortString();
        log.info("TrackAction - {} - START - args: {}", method, joinPoint.getArgs());

        long start = System.currentTimeMillis();
        Object result = joinPoint.proceed();
        long elapsed = System.currentTimeMillis() - start;

        log.info("TrackAction - {} - END - elapsed: {}ms", method, elapsed);
        return result;
    }
}

// Usage — clean service, no manual logging
@Service
public class OrderServiceImpl {
    @TrackAction("Create Order")
    @Transactional
    public OrderDto createOrder(CreateOrderDto request) {
        // Pure business logic — logging handled by AOP
    }
}
```

## When to Use AOP

- ✅ Performance tracking / method timing
- ✅ Audit logging (who did what, when)
- ✅ Input/output logging for debugging
- ✅ Security validation (custom role checks)
- ❌ NOT for core business logic
