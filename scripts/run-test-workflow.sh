#!/usr/bin/env bash
# 使用本地 CLI 代理（opencode + claude）的测试工作流
# 前提：./start.sh 正在运行
set -euo pipefail

API="http://localhost:8000/api"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> 1. 创建测试工作流..."

WORKFLOW_RESP=$(curl -sf -X POST "$API/workflows" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "项目测试",
    "description": "使用 opencode + claude 运行后端和前端测试",
    "definition": {
      "nodes": [
        {
          "id": "backend_test",
          "type": "agent",
          "label": "后端测试",
          "config": {
            "executor_type": "local_cli",
            "executor_config": {
              "provider": "opencode",
              "working_directory": "'"$ROOT_DIR"'/backend",
              "auto_approve": true,
              "model": "openai/gpt-4o"
            },
            "timeout_seconds": 600
          },
          "input_mapping": [
            {"source": "$.backend_test_prompt", "target": "prompt"}
          ],
          "output_mapping": [
            {"source": "output", "target": "$.backend_test_result"}
          ]
        },
        {
          "id": "frontend_test",
          "type": "agent",
          "label": "前端测试",
          "config": {
            "executor_type": "local_cli",
            "executor_config": {
              "provider": "opencode",
              "working_directory": "'"$ROOT_DIR"'/frontend",
              "auto_approve": true,
              "model": "openai/gpt-4o"
            },
            "timeout_seconds": 600
          },
          "input_mapping": [
            {"source": "$.frontend_test_prompt", "target": "prompt"}
          ],
          "output_mapping": [
            {"source": "output", "target": "$.frontend_test_result"}
          ]
        },
        {
          "id": "review",
          "type": "agent",
          "label": "结果审查",
          "config": {
            "executor_type": "local_cli",
            "executor_config": {
              "provider": "claude",
              "allow_dangerously_skip_permissions": true,
              "model": "claude-sonnet-4-20250514"
            },
            "timeout_seconds": 600
          },
          "input_mapping": [
            {"source": "$.review_prompt", "target": "prompt"}
          ],
          "output_mapping": [
            {"source": "output", "target": "$.review_summary"}
          ]
        }
      ],
      "edges": [
        {"source": "backend_test", "target": "review"},
        {"source": "frontend_test", "target": "review"}
      ]
    }
  }')

WORKFLOW_ID=$(echo "$WORKFLOW_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "   工作流 ID: $WORKFLOW_ID"

echo ""
echo "==> 2. 开始执行（测试约需 5-15 分钟）..."

EXEC_RESP=$(curl -sf -X POST "$API/workflows/$WORKFLOW_ID/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "context": {
      "backend_test_prompt": "在 backend/ 目录中运行完整的后端测试套件。执行: python3 -m pytest -v。如果测试失败，尝试修复。报告所有结果——包括通过、失败和跳过的测试数量以及失败详情。",
      "frontend_test_prompt": "在 frontend/ 目录中运行前端 lint 检查。执行: npx tsc --noEmit 和 npm run lint。修复任何可以修复的错误。报告所有结果。",
      "review_prompt": "审查后端和前端测试结果。总结通过/失败/跳过的测试数量。识别失败中的任何模式。从 10 分制给出质量评分。提供改进建议。"
    }
  }')

EXEC_ID=$(echo "$EXEC_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['execution_id'])")
echo "   执行 ID: $EXEC_ID"

echo ""
echo "==> 3. 监控执行..."
echo "   进度: http://localhost:3000/executions/$EXEC_ID"
echo ""

# 轮询直到完成
for i in $(seq 1 60); do
  sleep 10
  STATUS_RESP=$(curl -sf "$API/executions/$EXEC_ID" 2>/dev/null || echo "{}")
  STATUS=$(echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "pending")
  echo "   [$(date +%H:%M:%S)] 状态: $STATUS"
  if [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
    break
  fi
done

echo ""
echo "==> 完成！状态: $STATUS"
echo "   执行详情: http://localhost:3000/executions/$EXEC_ID"
echo "   工作流:   http://localhost:3000/workflows/$WORKFLOW_ID"
