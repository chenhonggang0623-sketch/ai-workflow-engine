# Task Report: Task Contract + Communication Broker (Epic 5)

## Status: DONE

## Files Created

### `app/contract/__init__.py`
Exports `ContractManager`, `CommunicationBroker`.

### `app/contract/contract_manager.py`
- **`ContractManager(db_session, evaluation_engine=None)`** — full lifecycle management
- `create()` — creates `TaskContract` with schemas, criteria, priority, timeout
- `get()` / `list()` — query by ID or filter by executor_id/status, ordered by priority desc
- `accept()` — transitions `pending → active`, stamps `accepted_at`
- `complete()` — validates result against `output_schema` (type checking) + `acceptance_criteria` (exists/equals/contains/gte/lte operators), stamps `completed_at`
- `fail()` — transitions to `failed`, stores error in result
- `cancel()` — transitions to `cancelled`
- `dispute()` — transitions to `disputed`, records reason
- `create_sub_contract()` — chain contracts under parent (inherits schemas/criteria/config)
- Status flow: `pending → active → completed | failed | cancelled` and `active → disputed → active`

### `app/contract/communication_broker.py`
- **`CommunicationBroker(db_session, redis_client=None)`** — poll-based agent messaging
- `send_message()` — stores `AgentMessage`, triggers `asyncio.Event` for response correlation
- `poll_messages()` — query undelivered messages by agent_id + execution_id, priority-ordered
- `request()` — sends request with `correlation_id`, waits on `asyncio.Event` up to `timeout` seconds, raises `TimeoutError` if no response
- `respond()` — reply to a message by swapping sender/target and reusing correlation_id
- `broadcast()` — sends message with `target_id=None` to all agents in execution
- `register_handler()` — stores agent subject handlers in-memory dict

### `tests/test_contract_manager.py` — 19 tests
### `tests/test_communication_broker.py` — 9 tests

## Commits
No commits — project is not a git repository.

## Test Summary
```
28 passed in 0.42s
```

## Concerns
1. **`datetime.utcnow()` deprecation** — Same as prior epics; Python 3.14 warns. Kept for consistency, should migrate to `datetime.now(datetime.UTC)`.
2. **Acceptance criteria validation is in-memory only** — criteria operators (exists/equals/contains/gte/lte) are evaluated without DB persistence of the rules engine. Works for MVP.
3. **CommunicationBroker is fully in-memory for request/response** — `_pending_responses` and `_responses` dicts live only in process. If the service restarts, pending requests are lost. Future Redis-backed implementation should persist correlation state.
4. **`target_id` is not indexed** — `poll_messages` filters on `target_id` + `execution_id` but the `AgentMessage` model has no composite index. May need one at scale.
5. **No message delivery acknowledgment** — Polling returns all messages; there's no `delivered` flag or read-receipt. An agent could re-process the same message. Future: add `delivered_at` or `status` column to `AgentMessage`.
