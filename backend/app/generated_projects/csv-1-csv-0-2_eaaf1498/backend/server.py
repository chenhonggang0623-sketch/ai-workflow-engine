"""CSV 销售数据统计工具 - FastAPI 服务。

职责：
- 提供 REST API（解析 / 统计 / 报表 / 验收）
- 托管前端静态资源（Frontend UI 模块）
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .parser import CsvParseError, parse_csv_source
from .pipeline import run_pipeline_from_parsed

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
SAMPLE_DATA_DIR = BACKEND_DIR / "sample_data"
SAMPLE_CSV = SAMPLE_DATA_DIR / "sample_sales.csv"

app = FastAPI(
    title="CSV 销售数据统计工具 API",
    description="解析、聚合、报表生成与验收一体的 CSV 销售数据统计服务",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_OUTPUT_DIR = PROJECT_DIR / "reports"


def _default_output_dir() -> str:
    return str(DEFAULT_OUTPUT_DIR)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "csv-sales-stats"}


@app.get("/api/sample")
def get_sample() -> JSONResponse:
    """返回示例 CSV 内容。"""
    if not SAMPLE_CSV.exists():
        raise HTTPException(status_code=404, detail="示例数据不存在")
    content = SAMPLE_CSV.read_text(encoding="utf-8-sig")
    return JSONResponse({"filename": SAMPLE_CSV.name, "content": content})


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)) -> JSONResponse:
    """解析并聚合上传的 CSV，返回统计结果（不生成报表）。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码需为 UTF-8")
    try:
        parsed = parse_csv_source(text)
    except CsvParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from .aggregator import aggregate

    return JSONResponse({"parsed": parsed.to_dict(), "stats": aggregate(parsed).to_dict()})


@app.post("/api/generate")
async def generate(
    file: UploadFile = File(...),
    output_dir: str = Form(default=""),
) -> JSONResponse:
    """解析、统计并生成 Markdown 报表，返回报表内容与路径。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码需为 UTF-8")
    try:
        parsed = parse_csv_source(text)
    except CsvParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    out_dir = output_dir.strip() or _default_output_dir()
    result = run_pipeline_from_parsed(parsed, out_dir, file.filename or "sales.csv")
    report_path = result["report_path"]
    result["report_content"] = Path(report_path).read_text(encoding="utf-8")
    return JSONResponse(result)


@app.post("/api/run")
async def run(
    file: UploadFile = File(...),
    output_dir: str = Form(default=""),
) -> JSONResponse:
    """执行完整流水线：解析 → 聚合 → 生成报表 → 验收。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码需为 UTF-8")
    try:
        parsed = parse_csv_source(text)
    except CsvParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    out_dir = output_dir.strip() or _default_output_dir()
    result = run_pipeline_from_parsed(parsed, out_dir, file.filename or "sales.csv")
    report_path = result["report_path"]
    result["report_content"] = Path(report_path).read_text(encoding="utf-8")
    return JSONResponse(result)


@app.get("/api/report/{report_filename}")
def get_report(report_filename: str) -> FileResponse:
    """下载生成的报表文件。"""
    safe = Path(report_filename).name
    path = DEFAULT_OUTPUT_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="报表文件不存在")
    return FileResponse(path, media_type="text/markdown", filename=safe)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动服务（供 start.sh 调用）。"""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()