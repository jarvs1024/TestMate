"""log 诊断请求 / 响应。"""
from typing import Optional
from pydantic import BaseModel, Field


class DiagnoseRequest(BaseModel):
    log_content: str = Field(min_length=1, max_length=10_000_000, description="上传的 log 内容")
    environment: Optional[dict] = Field(default=None, description="环境变量:固件版本/NAND 型号等")
    dataset: Optional[str] = Field(default=None, description="RAGFlow 数据集 id,可选")


class DiagnoseChunk(BaseModel):
    """SSE 单个事件载荷。"""
    type: str  # "thinking" | "code" | "conclusion" | "error" | "done"
    content: str
