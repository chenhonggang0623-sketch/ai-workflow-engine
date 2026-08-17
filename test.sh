#!/usr/bin/env bash
# AI Workflow Engine — 快速测试脚本
set -euo pipefail

BASE="${1:-http://localhost:8000}"
echo "==> Testing against: $BASE"
echo ""

# 1. 健康检查
echo "1. Health check"
curl -s "$BASE/health" | python3 -m json.tool
echo ""

# 2. 列出内置 Agent
echo "2. List built-in agents"
curl -s "$BASE/api/agents" | python3 -m json.tool
echo ""

# 3. Planner 模板
echo "3. List planner templates"
curl -s "$BASE/api/planner/templates" | python3 -m json.tool
echo ""

# 4. Planner 生成 Workflow（不需要 API key，用关键词匹配回退）
echo "4. Generate workflow plan from requirement"
PLAN=$(curl -s -X POST "$BASE/api/planner/plan" \
  -H "Content-Type: application/json" \
  -d '{"requirement": "开发一个用户管理系统，前后端分离"}')
echo "$PLAN" | python3 -m json.tool
echo ""

# 4.1 校验计划响应携带蓝图
echo "4.1. Plan response includes blueprint"
echo "$PLAN" | python3 -c "
import sys, json
plan = json.load(sys.stdin)
assert 'blueprint' in plan, 'missing blueprint'
bp = plan['blueprint']
assert bp.get('content', {}).get('modules'), 'blueprint missing modules'
print(f'  - blueprint id={bp.get(\"id\")} version={bp.get(\"version\")} modules={len(bp[\"content\"][\"modules\"])}')
"

# 5. 确认计划并执行
echo "5. Confirm plan and execute"
WORKFLOW_JSON=$(echo "$PLAN" | python3 -c "
import sys, json
plan = json.load(sys.stdin)
# 提取 workflow 定义
wf = plan.get('plan', plan)
# 输出完整定义
print(json.dumps(wf))
")
BLUEPRINT_ID=$(echo "$PLAN" | python3 -c "
import sys, json
plan = json.load(sys.stdin)
bp = plan.get('blueprint') or {}
print(bp.get('id') or '')
")
if [ -n "$BLUEPRINT_ID" ]; then
  echo "  - with blueprint_id=$BLUEPRINT_ID"
  CONFIRM=$(curl -s -X POST "$BASE/api/planner/confirm" \
    -H "Content-Type: application/json" \
    -d "{\"approved\": true, \"modifications\": $WORKFLOW_JSON, \"blueprint_id\": \"$BLUEPRINT_ID\"}")
else
  CONFIRM=$(curl -s -X POST "$BASE/api/planner/confirm" \
    -H "Content-Type: application/json" \
    -d "{\"approved\": true, \"modifications\": $WORKFLOW_JSON}")
fi
echo "$CONFIRM" | python3 -m json.tool
EXEC_ID=$(echo "$CONFIRM" | python3 -c "import sys,json; print(json.load(sys.stdin).get('execution_id',''))")
WF_ID=$(echo "$CONFIRM" | python3 -c "import sys,json; print(json.load(sys.stdin).get('workflow_id',''))")
echo ""

# 6. 查看执行状态
echo "6. Check execution status"
if [ -n "$EXEC_ID" ]; then
  curl -s "$BASE/api/executions/$EXEC_ID" | python3 -m json.tool
fi
echo ""

# 7. 列出 Workflows
echo "7. List all workflows"
curl -s "$BASE/api/workflows" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Total workflows: {len(data)}')
for w in data:
  print(f'  - {w[\"id\"]}: {w[\"name\"]} ({w[\"status\"]})')
"
echo ""

# 8. Wiki 模板快速创建
echo "8. Quick-create a workflow (Wiki template)"
curl -s -X POST "$BASE/api/workflows" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Wiki Documentation Generator",
    "description": "Auto-generate project documentation",
    "definition": {
      "nodes": [
        {"id": "pm", "type": "agent", "label": "PM", "config": {"agent_id": "pm_agent", "timeout_seconds": 300}},
        {"id": "dev", "type": "agent", "label": "Developer", "config": {"agent_id": "developer_agent", "timeout_seconds": 600}},
        {"id": "qa", "type": "agent", "label": "QA", "config": {"agent_id": "qa_agent", "timeout_seconds": 300}}
      ],
      "edges": [
        {"id": "e1", "source": "pm", "target": "dev"},
        {"id": "e2", "source": "dev", "target": "qa"}
      ]
    }
  }' | python3 -m json.tool
echo ""

# 9. 蓝图查询（从步骤 5 创建的 workflow 关联）
echo "9. Fetch blueprint for workflow"
if [ -n "$WF_ID" ]; then
  curl -s "$BASE/api/blueprints/$WF_ID" | python3 -c "
import sys, json
bp = json.load(sys.stdin)
print(f'  - blueprint v{bp[\"version\"]} status={bp[\"status\"]} modules={len(bp[\"content\"][\"modules\"])}')
"
  echo ""
  echo "9.1. Blueprint versions"
  curl -s "$BASE/api/blueprints/$WF_ID/versions" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'  - {len(data[\"versions\"])} version(s)')
"
else
  echo "  (no workflow from step 5 — skipped)"
fi
echo ""

echo "==> Done."
echo ""
echo "Swagger UI: $BASE/docs"
echo "OpenAPI:    $BASE/openapi.json"
