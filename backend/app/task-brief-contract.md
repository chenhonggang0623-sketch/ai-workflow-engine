# Task: Implement Task Contract + Communication Broker

## Files to create

### 1. `backend/app/contract/__init__.py`
Export: ContractManager, ContractLifecycle, CommunicationBroker

### 2. `backend/app/contract/contract_manager.py` — ContractManager

```python
class ContractManager:
    """
    Manages the full lifecycle of task contracts between Supervisor and Agents.
    
    - create(execution_id, issuer_id, executor_id, task_name, ...) → Contract
    - get(contract_id) → Contract
    - list(executor_id, status) → list of contracts
    - accept(contract_id) → agent accepts the contract
    - complete(contract_id, result) → agent completes with result
    - fail(contract_id, error) → contract failed
    - cancel(contract_id) → cancel contract
    
    Contract status flow:
    pending → active → completed | failed | cancelled
    pending → active → disputed → active (re-opened)
    
    Contract includes acceptance criteria that must be met for completion.
    """

    def __init__(self, db_session, evaluation_engine=None): ...
    async def create(self, execution_id: UUID, issuer_id: str, executor_id: str,
                      task_name: str, task_description: str = "",
                      input_schema: dict = None, output_schema: dict = None,
                      acceptance_criteria: list = None,
                      model_config: dict = None, timeout_seconds: int = 300,
                      priority: int = 0) -> TaskContract: ...
    async def get(self, contract_id: UUID) -> TaskContract: ...
    async def list(self, executor_id: str = None, status: str = None) -> list[TaskContract]: ...
    async def accept(self, contract_id: UUID) -> TaskContract: ...
    async def complete(self, contract_id: UUID, result: dict) -> TaskContract:
        """Validates result against output_schema and acceptance_criteria before completing."""
    async def fail(self, contract_id: UUID, error: str) -> TaskContract: ...
    async def cancel(self, contract_id: UUID) -> TaskContract: ...
    async def dispute(self, contract_id: UUID, reason: str) -> TaskContract: ...
    async def create_sub_contract(self, parent_id: UUID, executor_id: str,
                                    task_name: str, **kwargs) -> TaskContract:
        """Creates a sub-contract under a parent contract (contract chain)."""
```

### 3. `backend/app/contract/communication_broker.py` — CommunicationBroker

```python
class CommunicationBroker:
    """
    Message broker for Agent-to-Agent and Supervisor-to-Agent communication.
    
    - send_message(msg: AgentMessage) → publishes message to target
    - poll_messages(agent_id, execution_id) → returns undelivered messages for agent
    - request(agent_id, target_id, subject, payload, timeout) → sends and waits for response
    - register_handler(agent_id, subject, handler) → registers agent's message handler
    - broadcast(execution_id, subject, payload) → sends to all agents in execution
    
    Messages stored in agent_messages table.
    For MVP: simple poll-based delivery (agents poll for messages).
    Future: Redis pub/sub for real-time delivery.
    
    Each message has:
    - id, type (request/response/broadcast/event), sender_id, target_id, subject, payload
    - correlation_id (for matching requests to responses)
    - priority (0-10), ttl_seconds
    """

    def __init__(self, db_session, redis_client=None): ...
    async def send_message(self, execution_id: UUID, message_type: str,
                            sender_id: str, target_id: str | None,
                            subject: str, payload: dict,
                            correlation_id: UUID = None,
                            priority: int = 0) -> AgentMessage: ...
    async def poll_messages(self, agent_id: str, execution_id: UUID,
                             limit: int = 50) -> list[AgentMessage]: ...
    async def request(self, execution_id: UUID, sender_id: str,
                       target_id: str, subject: str, payload: dict,
                       timeout: int = 60) -> dict: ...
    async def broadcast(self, execution_id: UUID, sender_id: str,
                         subject: str, payload: dict) -> None: ...
    async def respond(self, execution_id: UUID, sender_id: str,
                       original_msg: AgentMessage, payload: dict) -> None: ...
```

## Constraints
- All methods are async
- Contract completion validates against acceptance_criteria
- Communication is poll-based for MVP (no Redis pub/sub needed)
- Request/response uses correlation_id matching with asyncio.Event for waiting
- Models already exist in `app/models/contract.py` and `app/models/message.py`

## Output
- Status: DONE / DONE_WITH_CONCERNS / BLOCKED
- Report file: `backend/app/task-brief-contract-report.md`
- Test output summary
