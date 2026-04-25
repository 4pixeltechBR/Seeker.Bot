# Seeker.Bot API Documentation

> Complete guide to Seeker.Bot's Python API for custom integration and extension.

## Quick Start

```python
from src.core.pipeline import SeekerPipeline
import asyncio

async def main():
    # Initialize pipeline
    api_keys = {
        'gemini': 'your-gemini-key',
        'groq': 'your-groq-key',
        'nvidia_nim': 'your-nvidia-key',
    }
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    
    # Process request
    result = await pipeline.process(
        text="Como implementar autenticação JWT em FastAPI?",
        user_id=12345
    )
    
    # Access result
    print(f"Response: {result.response}")
    print(f"Cognitive Depth: {result.depth}")
    print(f"Cost: ${result.total_cost_usd:.4f}")
    print(f"Latency: {result.total_latency_ms}ms")
    print(f"Sources Used: {result.facts_used} facts from memory")

asyncio.run(main())
```

---

## Core Components

### SeekerPipeline

Main orchestrator for request processing.

#### Constructor
```python
SeekerPipeline(api_keys: dict[str, str], db_path: str | None = None)
```

**Parameters:**
- `api_keys`: Dictionary of provider API keys
  - `gemini`: Google Gemini API key (REQUIRED for embeddings)
  - `groq`: Groq API key
  - `nvidia_nim`: NVIDIA NIM API key
  - `deepseek`: DeepSeek API key
  - `mistral`: Mistral API key
  - `tavily`: Tavily web search API key (optional)
  - `brave`: Brave web search API key (optional)
- `db_path`: Custom SQLite database path (optional)

#### Methods

##### `await init()`
Initialize all components and verify API connectivity.

```python
pipeline = SeekerPipeline(api_keys)
await pipeline.init()  # Must call before processing
```

##### `await process(text: str, user_id: int | str, session_id: str | None = None) -> PipelineResult`
Process a user query through the cognitive system.

**Parameters:**
- `text`: User message/query
- `user_id`: Unique user identifier
- `session_id`: Optional session ID (for conversation continuity)

**Returns:** `PipelineResult` object with:
- `response`: Generated response text
- `depth`: Cognitive depth used (REFLEX, DELIBERATE, DEEP)
- `routing_reason`: Why this depth was chosen
- `total_cost_usd`: API cost in USD
- `total_latency_ms`: End-to-end latency
- `llm_calls`: Number of LLM API calls made
- `facts_used`: Number of memory facts injected
- `new_facts_count`: Facts extracted and stored
- `arbitrage`: Evidence triangulation result (if DEEP)
- `verdict`: Judge's verification (if DEEP)

**Example:**
```python
result = await pipeline.process(
    text="Resumo dos últimos avanços em LLMs",
    user_id="user_123"
)
if result.depth.name == "DEEP":
    print(f"Deep analysis used {result.llm_calls} calls")
if result.arbitrage and result.arbitrage.has_conflicts:
    print(f"Found {len(result.arbitrage.conflict_zones)} conflicting claims")
```

##### `await cleanup()`
Close all connections and clean up resources.

```python
await pipeline.cleanup()
```

---

## Cognitive Routing

### CognitiveDepth

The pipeline automatically chooses processing depth based on request complexity:

| Depth | LLM Calls | Use Case | Speed |
|-------|-----------|----------|-------|
| **REFLEX** | 0 | Status checks, simple facts, memes | <50ms |
| **DELIBERATE** | 1-2 | Single-topic questions, news summaries | 1-5s |
| **DEEP** | 3-10 | Complex analysis, triangulation, research loops | 10-60s |

**Automatic Detection:**
```python
# These automatically route to REFLEX (no LLM calls)
await pipeline.process("/status")  # Bot status check
await pipeline.process("o que é Python?")  # Trivial fact

# These automatically route to DELIBERATE
await pipeline.process("Quais são os melhores frameworks Python?")

# These automatically route to DEEP
await pipeline.process("Compare arquiteturas de microserviços vs monolito, considerando latência, escalabilidade e complexidade operacional")
```

---

## Memory System

### MemoryStore

Access the persistent knowledge base.

```python
memory = pipeline.memory

# Store a fact
await memory.store_fact(
    user_id=123,
    content="Python 3.12 released in October 2023",
    domain="software",
    confidence=0.95,
    source="official_docs"
)

# Retrieve facts
facts = await memory.search_facts(
    query="Python releases",
    limit=5
)

# Access tables directly
async with memory.get_connection() as conn:
    cursor = await conn.execute(
        "SELECT * FROM facts WHERE domain = ?",
        ("software",)
    )
    rows = await cursor.fetchall()
```

---

## Evidence & Verification

### EvidenceArbitrage

Triangulates responses from multiple models.

```python
# Automatically used in DEEP phase
# Access results in PipelineResult.arbitrage

if result.arbitrage:
    print(f"Models compared: {result.arbitrage.model_ids}")
    print(f"Consensus score: {result.arbitrage.consensus_score}")
    
    if result.arbitrage.has_conflicts:
        for zone in result.arbitrage.conflict_zones:
            print(f"Disagreement on: {zone.topic}")
            print(f"  Model A: {zone.claim_a}")
            print(f"  Model B: {zone.claim_b}")
```

### VerificationGate

Independent judge verifies critical claims.

```python
if result.verdict:
    print(f"Judge decision: {result.verdict.decision}")
    print(f"Confidence: {result.verdict.confidence}")
    if result.verdict.flags:
        print(f"Warnings: {result.verdict.flags}")
```

---

## Web Search Integration

### WebSearcher

Automatic web search in DELIBERATE and DEEP phases.

```python
searcher = pipeline.searcher

results = await searcher.search(
    query="Python 3.12 features",
    max_results=5
)

for result in results:
    print(f"Title: {result.title}")
    print(f"URL: {result.url}")
    print(f"Snippet: {result.snippet}")
    print(f"Freshness: {result.freshness_hours}h old")
```

---

## Machine Learning: RL Bandit

### Cascade Bandit

Learns which provider works best for each cognitive role.

```python
# Automatically learns from every request
# Shadow mode: predicts but doesn't change routing

bandit = pipeline.cascade_bandit
state = bandit.current_state()

print(f"Preferred FAST provider: {state.best_fast_provider}")
print(f"Preferred DEEP provider: {state.best_deep_provider}")
print(f"Preferred JUDGE provider: {state.best_judge_provider}")

# View learning progress
metrics = bandit.get_metrics()
print(f"Requests processed: {metrics['request_count']}")
print(f"Provider win rate: {metrics['provider_scores']}")
```

---

## Safety & Autonomy

### SafetyLayer

Controls autonomous actions and safety.

```python
# Check if action is allowed
action_type = ActionType.FILE_WRITE
autonomy_tier = AutonomyTier.SUPERVISED

is_allowed = pipeline.safety_layer.is_allowed(
    action=action_type,
    autonomy=autonomy_tier,
    context={"path": "/home/user/data.txt"}
)

if is_allowed:
    # Proceed with action
    pass
```

---

## Session Management

### SessionManager

Manage conversation history and context windowing.

```python
session = pipeline.session

# Get session context
context = await session.get_context(
    user_id=123,
    session_id="conv_456",
    window_tokens=4000
)

print(f"Total messages: {len(context.turns)}")
print(f"Tokens used: {context.token_count}")
print(f"Compressed: {context.compression_ratio}%")
```

---

## Goals & Skills

### Goal Scheduler

Run autonomous skills in background.

```python
from src.core.goals import GoalScheduler, discover_goals

scheduler = GoalScheduler(pipeline)

# Auto-discover skills
goals = discover_goals(pipeline)
scheduler.register_all(goals)

# Start background execution
await scheduler.start()

# Later: stop
await scheduler.stop()
```

---

## Error Handling

### Standard Error Pattern

```python
from src.core.exceptions_handler import SeekerException

try:
    result = await pipeline.process("Sua pergunta")
except SeekerException as e:
    print(f"Seeker error: {e.code} - {e.message}")
    if e.recovery:
        print(f"Recovery suggestion: {e.recovery}")
except Exception as e:
    print(f"Unexpected error: {e}")
finally:
    await pipeline.cleanup()
```

---

## Performance Metrics

### System Profiler

Monitor system performance.

```python
profiler = pipeline.profiler

# Get current metrics
metrics = profiler.get_metrics()
print(f"Avg latency: {metrics['avg_latency_ms']}ms")
print(f"Memory usage: {metrics['memory_mb']}MB")
print(f"LLM calls/min: {metrics['llm_throughput']}")

# Export to Prometheus
exporter = pipeline.prometheus_exporter
prometheus_text = exporter.export()
# Push to Prometheus server
```

---

## Best Practices

### 1. Always Initialize
```python
pipeline = SeekerPipeline(api_keys)
await pipeline.init()  # Don't skip!
```

### 2. Use Context Managers
```python
# Better: cleanup guaranteed
try:
    result = await pipeline.process(...)
finally:
    await pipeline.cleanup()
```

### 3. Check Depth Before Acting
```python
result = await pipeline.process("...")
if result.depth == CognitiveDepth.DEEP:
    # Reliable for critical decisions
    apply_decision(result.response)
elif result.depth == CognitiveDepth.REFLEX:
    # Lower confidence, may need verification
    log_warning("Reflex response used")
```

### 4. Monitor Costs
```python
if result.total_cost_usd > 1.0:
    log_warning(f"Expensive query: ${result.total_cost_usd}")
```

### 5. Use Evidence When Available
```python
if result.arbitrage and result.arbitrage.consensus_score > 0.9:
    # High confidence triangulation
    trust_response(result)
elif result.arbitrage:
    # Conflicting models
    request_user_verification(result)
```

---

## Examples

### Example 1: Simple Q&A
```python
async def answer_question(question: str):
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    try:
        result = await pipeline.process(question, user_id="user_1")
        print(result.response)
    finally:
        await pipeline.cleanup()

asyncio.run(answer_question("Como aprender Python?"))
```

### Example 2: Multi-turn Conversation
```python
async def conversation():
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    session_id = "conv_123"
    
    try:
        # Turn 1
        r1 = await pipeline.process("Python vs JavaScript", user_id=1, session_id=session_id)
        print(f"Bot: {r1.response}")
        
        # Turn 2 (same session)
        r2 = await pipeline.process("Qual é mais rápido?", user_id=1, session_id=session_id)
        print(f"Bot: {r2.response}")  # Remembers context from Turn 1
    finally:
        await pipeline.cleanup()

asyncio.run(conversation())
```

### Example 3: Research Loop
```python
async def research(topic: str):
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    try:
        result = await pipeline.process(
            f"Pesquisa completa sobre: {topic}",
            user_id="researcher_1"
        )
        # DEEP phase automatically does research loops
        # Detects conflicts → searches more → resolves
        print(result.response)
        if result.arbitrage:
            print(f"Triangulation used {len(result.arbitrage.model_ids)} models")
    finally:
        await pipeline.cleanup()

asyncio.run(research("Fusão nuclear fria"))
```

---

## See Also

- [Architecture](./ARCHITECTURE.md)
- [Skills Guide](./SKILLS.md)
- [Deployment Guide](../README.md#deployment)
