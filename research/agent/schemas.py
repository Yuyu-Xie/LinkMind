from pydantic import BaseModel, ConfigDict, Field


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchBookmarksArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=300)
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=10)


class WebSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=8)


class ReadDocumentArgs(ToolArgs):
    source_id: int
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=6000, ge=500, le=12000)


class ExtractEvidenceArgs(ToolArgs):
    source_id: int
    quote: str = Field(min_length=2, max_length=2000)
    sub_question_id: int | None = None


class AddClaimArgs(ToolArgs):
    text: str = Field(min_length=2, max_length=2000)
    evidence_ids: list[int] = Field(default_factory=list)
    sub_question_id: int | None = None
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class AnswerSubQuestionArgs(ToolArgs):
    sub_question_id: int
    status: str = Field(pattern="^(answered|insufficient)$")
    answer: str = Field(default="", max_length=4000)


class FinishResearchArgs(ToolArgs):
    summary: str = Field(min_length=2, max_length=4000)
    unresolved_question_ids: list[int] = Field(default_factory=list)


ARG_MODELS: dict[str, type[ToolArgs]] = {
    "search_bookmarks": SearchBookmarksArgs,
    "web_search": WebSearchArgs,
    "read_document": ReadDocumentArgs,
    "extract_evidence": ExtractEvidenceArgs,
    "add_claim": AddClaimArgs,
    "answer_subquestion": AnswerSubQuestionArgs,
    "finish_research": FinishResearchArgs,
}


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_bookmarks",
            "description": "搜索用户自己的书签库。返回书签摘要和 source_id，读取正文需要再调用 read_document。",
            "parameters": _schema(
                {
                    "query": {
                        "type": "string",
                        "description": "检索关键词，可用空格分隔多个词",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选标签过滤，全部匹配",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "返回条数，默认 5",
                    },
                },
                ["query"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "在互联网上检索。返回标题、链接、摘要和 source_id。离线评测模式下不可用。",
            "parameters": _schema(
                {
                    "query": {"type": "string", "description": "检索关键词"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "返回条数，默认 5",
                    },
                },
                ["query"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "读取指定来源的正文。首次读取会抓取并缓存，长文档用 offset 分段读取。",
            "parameters": _schema(
                {
                    "source_id": {"type": "integer", "description": "来源 ID"},
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "从正文第几个字符开始，默认 0",
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 500,
                        "maximum": 12000,
                        "description": "本次返回的最大字符数，默认 6000",
                    },
                },
                ["source_id"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_evidence",
            "description": "从已读取的来源正文中摘取一段原文作为证据。quote 必须是正文中的连续片段。",
            "parameters": _schema(
                {
                    "source_id": {"type": "integer", "description": "来源 ID"},
                    "quote": {
                        "type": "string",
                        "description": "原文连续片段，不要改写或总结",
                    },
                    "sub_question_id": {
                        "type": "integer",
                        "description": "可选，证据主要服务的子问题 ID",
                    },
                },
                ["source_id", "quote"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_claim",
            "description": "记录一条研究主张，并绑定支持它的证据。报告只能引用已提取的证据。",
            "parameters": _schema(
                {
                    "text": {"type": "string", "description": "一句话主张"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "支持该主张的证据 ID 列表",
                    },
                    "sub_question_id": {
                        "type": "integer",
                        "description": "可选，对应的子问题 ID",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "置信度，默认 0.6",
                    },
                },
                ["text"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer_subquestion",
            "description": "更新子问题状态和答案。证据足够时标记 answered，检索不到时标记 insufficient。",
            "parameters": _schema(
                {
                    "sub_question_id": {"type": "integer", "description": "子问题 ID"},
                    "status": {
                        "type": "string",
                        "enum": ["answered", "insufficient"],
                        "description": "answered 或 insufficient",
                    },
                    "answer": {"type": "string", "description": "简要回答"},
                },
                ["sub_question_id", "status"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_research",
            "description": "结束研究。所有子问题必须已标记 answered 或 insufficient，否则会被拒绝。",
            "parameters": _schema(
                {
                    "summary": {"type": "string", "description": "研究结论摘要"},
                    "unresolved_question_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "仍未解决的子问题 ID",
                    },
                },
                ["summary"],
            ),
        },
    },
]
