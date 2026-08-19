"""
Thin Planner LLM Client — Phase 18 Round 1

planning-scoped thin client（不重构现有 11 处 ad-hoc LLM 调用、不引入 LangChain）。

职责仅：
  - OpenAI-compatible sync provider client（DeepSeek）
  - async 调用层经 asyncio.to_thread offload（不阻塞 event loop）
  - timeout（默认 30s）
  - max_attempts=2，仅 transport / malformed JSON 可 retry；schema invalid 不 retry
  - strict JSON extraction + strict PlanProposal parser
  - usage 读取（若 provider 返回）
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from backend.planning.capability_snapshot import PlannerCapabilitySnapshot
from backend.planning.context import PlanningContext
from backend.planning.prompts import build_planner_messages
from backend.planning.proposal import MAX_JSON_CHARS, PlanProposal, PlannerFailure, PlannerFailureCode


def _system_proposal_id() -> str:
    """SYSTEM 生成 proposalId（不作为 security/runtime identity，仅 audit 标签）。"""
    return f"proposal_{uuid.uuid4().hex[:8]}"


def get_planning_llm_client_optional(timeout: float = 30.0, max_attempts: int = 2) -> Optional["PlannerLLMClient"]:
    """从现有 config 创建 planning LLM client（无 key → None）。

    None 表示环境不可用（不表示 production assessment/critic 被硬编码禁用）。
    复用 Round1 已验证的 PlannerLLMClient（max_retries=0 + timeout + bounded retry）。
    每次创建新实例（无 global mutable singleton，简单、线程安全）。
    """
    if not (DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "your_api_key"):
        return None
    return PlannerLLMClient(timeout=timeout, max_attempts=max_attempts)


def _extract_json(text: str) -> Dict[str, Any]:
    """从 LLM 输出提取 JSON 对象（严格，不做松散正则拼字段）。"""
    text = (text or "").strip()
    # 剥离 markdown 代码围栏
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        raise PlannerFailure(
            PlannerFailureCode.INVALID_JSON, "LLM 输出不是 JSON object（非 dict）", retryable=False
        )
    except json.JSONDecodeError as e:
        # 尝试截取第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        raise PlannerFailure(
            PlannerFailureCode.INVALID_JSON, f"无法解析 LLM JSON 输出: {e}", retryable=True
        )


class PlannerLLMClient:
    """薄 LLM planner client。sync provider + async offload。"""

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_attempts: int = 2,
    ):
        self._model = model or DEEPSEEK_MODEL
        self._base_url = base_url or DEEPSEEK_BASE_URL
        self._api_key = api_key if api_key is not None else DEEPSEEK_API_KEY
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._enabled = bool(self._api_key and self._api_key != "your_api_key")
        self.last_attempt_count = 0
        self.last_usage: Dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def generate_proposal(
        self,
        ctx: PlanningContext,
        snapshot: PlannerCapabilitySnapshot,
        user_goal: str,
    ) -> PlanProposal:
        """生成 PlanProposal（async，sync provider offload 到线程）。

        Raises:
            PlannerFailure: llm_unavailable / timeout / transport_error / invalid_json /
                            schema_invalid / attempts_exhausted。
        """
        if not self._enabled:
            raise PlannerFailure(
                PlannerFailureCode.LLM_UNAVAILABLE, "LLM 未配置（无 API key）", retryable=False
            )

        system, user = build_planner_messages(ctx, snapshot, user_goal)

        data, usage, attempts = await self.call_structured_json(system, user)

        try:
            proposal = PlanProposal.from_dict_strict(data)
        except PlannerFailure:
            # schema invalid 不 retry
            raise

        # SYSTEM/CLIENT-owned 字段覆盖：不信任 LLM 回显的 audit/control 元数据
        proposal.capabilitySnapshotHash = snapshot.snapshotHash
        proposal.planningModeUsed = "llm"
        proposal.plannerModel = self._model
        proposal.fallbackReason = None
        proposal.proposalId = _system_proposal_id()
        return proposal

    async def call_structured_json(self, system: str, user: str):
        """公开结构化 JSON 原语（async，Phase18 Round2）。

        职责仅：OpenAI-compatible transport + max_retries=0 + timeout + bounded retry +
        JSON 提取 + usage。不做任何 schema validation（PlanProposal / Critic /
        Assessment 各自 strict parse）。sync provider 经 asyncio.to_thread offload。
        """
        if not self._enabled:
            raise PlannerFailure(
                PlannerFailureCode.LLM_UNAVAILABLE, "LLM 未配置（无 API key）", retryable=False
            )
        data, usage, attempts = await asyncio.to_thread(self._call_attempts, system, user)
        self.last_usage = usage
        self.last_attempt_count = attempts
        return data, usage, attempts

    def call_structured_json_sync(self, system: str, user: str):
        """公开结构化 JSON 原语（sync，供 sync continuation 路径使用）。

        与 call_structured_json 同职责，但直接调用 sync provider（不 offload）。
        """
        if not self._enabled:
            raise PlannerFailure(
                PlannerFailureCode.LLM_UNAVAILABLE, "LLM 未配置（无 API key）", retryable=False
            )
        data, usage, attempts = self._call_attempts(system, user)
        self.last_usage = usage
        self.last_attempt_count = attempts
        return data, usage, attempts

    def _call_attempts(self, system: str, user: str):
        """sync 调用 + 有限 retry（transport / malformed JSON）。

        JSON 提取在 retry 循环内：malformed JSON → retry（retryable），
        直到 maxAttempts；schema invalid（from_dict_strict）在循环外，不 retry。
        返回 (parsed_dict, usage, attempts)。
        """
        last_error: Optional[Exception] = None
        attempts = 0
        for attempt in range(1, self._max_attempts + 1):
            attempts = attempt
            try:
                text, usage = self._call_once(system, user)
                if len(text or "") > MAX_JSON_CHARS:
                    raise PlannerFailure(
                        PlannerFailureCode.INVALID_JSON,
                        f"raw JSON 长度超过上限 {MAX_JSON_CHARS}",
                        retryable=False,
                    )
                data = _extract_json(text)  # malformed → INVALID_JSON retryable=True
                return data, usage, attempts
            except PlannerFailure as e:
                if not e.retryable:
                    raise
                last_error = e
            except Exception as e:  # transport
                last_error = e
        raise PlannerFailure(
            PlannerFailureCode.ATTEMPTS_EXHAUSTED,
            f"LLM 调用 {self._max_attempts} 次均失败: {last_error}",
            retryable=False,
        )

    def _call_once(self, system: str, user: str):
        """单次 sync OpenAI-compatible 调用。返回 (raw_text, usage_dict)。

        max_retries=0：显式关闭 SDK 内部 retry，确保真实 provider request attempt
        完全由上层 _call_attempts（maxAttempts=2）控制，不叠加 SDK 默认重试。
        """
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=self._base_url, max_retries=0)
        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=2048,
                timeout=self._timeout,
            )
        except Exception as e:
            raise PlannerFailure(
                PlannerFailureCode.TRANSPORT_ERROR, f"LLM transport 失败: {e}", retryable=True
            )

        text = response.choices[0].message.content or ""
        usage: Dict[str, Any] = {}
        try:
            u = response.usage
            usage = {
                "promptTokens": getattr(u, "prompt_tokens", None),
                "completionTokens": getattr(u, "completion_tokens", None),
                "totalTokens": getattr(u, "total_tokens", None),
            }
        except Exception:
            pass
        return text, usage
