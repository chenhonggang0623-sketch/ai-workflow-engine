from fastapi import APIRouter

from app.api.routes.workflows import router as workflows_router
from app.api.routes.executions import router as executions_router
from app.api.routes.agents import router as agents_router
from app.api.routes.planner import router as planner_router
from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.supervisor import router as supervisor_router
from app.api.routes.blueprints import router as blueprints_router
from app.api.routes.config import router as config_router

router = APIRouter()

router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])
router.include_router(executions_router, prefix="/executions", tags=["executions"])
router.include_router(agents_router, prefix="/agents", tags=["agents"])
router.include_router(planner_router, prefix="/planner", tags=["planner"])
router.include_router(artifacts_router, prefix="/artifacts", tags=["artifacts"])
router.include_router(contracts_router, prefix="/contracts", tags=["contracts"])
router.include_router(supervisor_router, prefix="", tags=["supervisor"])
router.include_router(blueprints_router, prefix="/blueprints", tags=["blueprints"])
router.include_router(config_router, tags=["config"])
