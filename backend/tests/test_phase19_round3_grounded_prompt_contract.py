"""
Phase19 Round3 — Grounded Semantic Replanner Prompt Contract（minimal reliability fix）

Grounded-only prompt hardening 的非网络契约测试：

  A. legacy semantic replan prompt 与 Phase18 golden 逐字节一致（sha256 + literal）
  B. grounded system prompt 覆盖全部输出契约：顶层闭包 / 步骤字段闭包 /
     全部 forbidden raw field 家族（与 production parser `_FORBIDDEN_RAW_FIELDS`
     语义覆盖断言，不手写漏项）/ 线性依赖命名空间 / snapshot capability /
     action capability cardinality / structural steps 自动生成 / no-authority
  C. grounded prompt 的 trust boundary：untrusted FreeText 只在 envelope 内
  D. legacy prompt 不含任何 grounded-only hardening 字节

全部非网络。grounded prompt 经真实 production 路径（_try_semantic_replan →
assemble_or_empty → build_grounded_semantic_replan_messages）捕获，仅 mock
provider 网络层。禁止放宽 STRONG fixture contract —— 本文件不与
real-provider fixture 冲突（A2 契约不变）。
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

import backend.config as cfg
from backend.tests.phase19_golden_capture import capture
from backend.tests.test_phase19_round3_grounded_semantic_replan import (
    INJECTION,
    _coord,
    _envelope_regions,
    _event_plan,
    _replan_call,
    _save_definition,
    _seed_failed_action_run,
)
from backend.workflow.repository import init_workflow_tables

GOLDEN_FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "phase19_phase18_golden_prompts.json"
)

# grounded-only hardening 的字节指纹（legacy prompt 不得出现）
GROUNDED_ONLY_MARKERS = (
    "补充硬性规则（grounded 输出契约",
    "输出结构（严格，示例仅为格式演示",
    '"proposalStepId": "s2"',
)


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    """临时 DB：golden capture 与 grounded 生产路径互不污染。"""
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "prompt_contract.db"))
    init_workflow_tables()


class SysCapturingClient:
    """grounded replan 边界捕获 (system, user)；返回合法最小 proposal。"""

    def __init__(self):
        self.calls = 0
        self.last_system = ""
        self.last_user = ""

    def call_structured_json_sync(self, system, user):
        assert "suffixSteps" in user, "prompt contract 测试只允许 semantic replan 调用"
        self.calls += 1
        self.last_system = system
        self.last_user = user
        return {"reasonSummary": "ok", "suffixSteps": []}, {}, 1


def _grounded_prompts():
    """真实 production 路径构建 grounded prompt（0 网络）。"""
    from backend.workflow.repository import SQLiteWorkflowRepository

    repo = SQLiteWorkflowRepository()
    plan = _event_plan(grounded=True, semantic_replan=True)
    _save_definition(repo, plan)
    run_id, _ = _seed_failed_action_run(repo, plan, run_id="pc_g", evidence=True)
    client = SysCapturingClient()
    coord = _coord(repo, critic_client=client)
    assert _replan_call(repo, coord, run_id, plan) is not None
    assert client.calls == 1
    return client.last_system, client.last_user


class TestLegacyByteFreeze:
    """A/D：legacy 字节与 Phase18 golden 完全一致，且不含 grounded-only hardening。"""

    def test_legacy_replan_prompt_byte_identical_to_golden(self):
        fixture = json.load(open(GOLDEN_FIXTURE, encoding="utf-8"))["scenarios"]
        captured = capture()
        for key in ("replan::tool_failed", "replan::node_failed", "replan::approval_rejected"):
            c = captured[key]
            raw = (c["system"] + "\x00" + c["user"]).encode("utf-8")
            assert hashlib.sha256(raw).hexdigest() == fixture[key]["sha256"], \
                f"{key} 与 Phase18 golden 不一致（legacy 字节漂移）"
            assert c["system"] == fixture[key]["system"]
            assert c["user"] == fixture[key]["user"]

    def test_legacy_prompt_has_no_grounded_only_hardening_bytes(self):
        captured = capture()
        for key in ("replan::tool_failed", "replan::node_failed", "replan::approval_rejected"):
            blob = captured[key]["system"] + "\n" + captured[key]["user"]
            for marker in GROUNDED_ONLY_MARKERS:
                assert marker not in blob, f"{key} 泄漏 grounded-only hardening 字节: {marker}"


class TestGroundedContractCoverage:
    """B：grounded system prompt 覆盖 §4 A-G 全部契约。"""

    def test_grounded_system_covers_output_contract(self):
        from backend.planning.proposal import _FORBIDDEN_RAW_FIELDS

        system, user = _grounded_prompts()

        # A 顶层闭包
        assert "顶层只允许两个字段" in system
        assert "reasonSummary" in system and "suffixSteps" in system
        # B 步骤字段闭包（9 个 parser 允许字段逐一出现）
        for field in ("proposalStepId", "intent", "expectedOutcome", "requiredCapabilities",
                      "evidenceNeeds", "riskHint", "dependsOnProposalStepIds",
                      "actionIntent", "parameterHints"):
            assert field in system, f"步骤字段闭包缺失: {field}"
        # C 全部 forbidden raw field 家族（与 production parser 常量语义覆盖）
        for tok in _FORBIDDEN_RAW_FIELDS:
            assert tok in system, f"forbidden raw field 未在 grounded prompt 中声明: {tok}"
        # D 线性依赖命名空间
        assert "只能依赖紧邻前一步" in system
        assert "禁止引用原 Plan 的 stepId/nodeId" in system
        # E snapshot capability + cardinality
        assert "capabilitySnapshot 中真实存在" in system
        assert "至少需要一个合法的 agent capability" in system
        assert "必须恰好" in system
        assert "一个 planner-eligible 的 action capability" in system
        # F structural steps 自动生成
        assert "结构性步骤由编译器/运行时自动生成" in system
        for structural in ("validate_event", "rule_router", "evidence_evaluate",
                           "risk_gate", "save_result", "close"):
            assert structural in system, f"structural step 未声明: {structural}"
        # G no-authority reminder
        assert "不能直接指定 tool、agent 实现、risk、approval、retry、timeout" in system

        # grounded user 使用强化示例（2 步 agent+action，展示线性依赖），
        # 且系统补充只存在于 system（不进 user payload）
        assert '"proposalStepId": "s1"' in user
        assert '"proposalStepId": "s2"' in user
        assert '"dependsOnProposalStepIds": ["s1"]' in user
        assert "补充硬性规则" not in user

    def test_grounded_trust_boundary_free_text_only_in_envelope(self):
        """C：注入 FreeText 只在 untrusted envelope，trusted 区干净。"""
        system, user = _grounded_prompts()
        inside, raw, outside = _envelope_regions(user)
        assert INJECTION in raw
        assert INJECTION not in outside      # trusted 指令区不得携带注入文本
        assert INJECTION not in system       # system 恒为系统指令，不含运行时文本


class TestGroundedParameterHintsContract:
    """parameterHints 输出契约（§9 B/C/D）：prompt 文案必须镜像真实 compiler contract。"""

    def test_grounded_system_has_parameter_hints_contract(self):
        from backend.planning.param_schema import _TYPE_MAP

        system, user = _grounded_prompts()

        # B1 key discipline：key 只能来自 businessParamSchema
        assert "parameterHints 的 key 只能来自该 action capability" in system
        assert "businessParamSchema 中声明的字段" in system
        assert "禁止发明参数名" in system
        # B2 type discipline：prompt 声明的类型必须与真实 _TYPE_MAP 逐 token 一致
        assert "JSON 类型必须与" in system
        for tok in _TYPE_MAP:
            assert tok in system, f"prompt 缺少真实编译器支持的 type token: {tok}"
        # B3 optional unknown → omit
        assert "省略该 key" in system
        # B4 required unknown → 按真实 runtime binding 规则（NOT_SUPPORTED）处理
        assert "runtime 不做任何参数绑定/替换" in system
        assert "不要提出该 action 步骤" in system
        # B5 no placeholder values
        assert "禁止使用占位语义的值填充 parameterHints" in system
        assert "不得输出「待定」" in system
        # B6 no fake typed placeholder
        assert "不得把占位文本" in system and "包装成数组" in system
        assert '["待定"]' in system  # 反例以错误形态出现

    def test_grounded_example_compile_legal_and_placeholder_free(self):
        """示例为 agent-only 两步（无 action 步骤）：不演示任何占位/伪业务值。

        4 个 planner-eligible action 全部 sideEffect=true 且为真实外部动作，
        示例演示任何具体 action 都会把模型锚定到副作用动作（anchoring）——
        示例只演示 agent 步骤与线性依赖，action 契约由规则 12/15-18 文本约束。

        断言范围限定在「输出结构」之后的示例区域 —— untrusted evidence 区
        可能合法携带运行时 business 参数（如失败动作的 target_road_ids）。
        """
        system, user = _grounded_prompts()
        example = user.split("输出结构（严格", 1)[1]

        assert '"intent": "analyze_congestion"' in example
        assert '"requiredCapabilities": ["congestion_analysis"]' in example
        assert '"intent": "dispatch_coordination"' in example
        assert '"requiredCapabilities": ["dispatch_analysis"]' in example
        assert '"parameterHints": {}' in example
        # 两步均为 agent 步骤（示例刻意不演示 action / 不演示 business 值）
        assert example.count('"actionIntent": null') == 2
        for cap in ("notify_wechat", "notify_dingtalk",
                    "simulate_traffic_diversion", "simulate_signal_adjustment"):
            assert cap not in example, f"示例不应锚定副作用 action: {cap}"
        for bad in ("待定", "稍后确定", "由s1", "unknown", "TBD", "placeholder"):
            assert bad not in example, f"示例泄漏占位语义: {bad}"
        for bad in ('"target_road_ids"', '"source_road_id"', '"diversion_ratio"',
                    '"intersection_id"', '"cycle_length"', "road_fixture"):
            assert bad not in example, f"示例不应演示 business 具体参数值: {bad}"

    def test_grounded_example_compiles_through_real_parser_and_compiler(self):
        """§12：示例必须通过真实 strict parser + compiler（compile-legality，
        非字符串外观断言）。"""
        from backend.planning.capability_snapshot import build_planner_capability_snapshot
        from backend.planning.proposal_compiler import compile_replan_suffix
        from backend.planning.replan_context import SemanticReplanProposal

        _system, user = _grounded_prompts()
        region = user.split("输出结构（严格", 1)[1]
        example_json = "{" + region.split("{", 1)[1]  # 区域尾部即示例 JSON
        data = json.loads(example_json)

        proposal = SemanticReplanProposal.from_dict_strict(data)
        snapshot = build_planner_capability_snapshot()
        suffix = compile_replan_suffix(proposal.suffixSteps, snapshot,
                                       requires_approval=True, carried_step_ids=set())
        # 示例 2 个 agent 步骤全部编译成功（编译器自动追加结构性步骤，
        # 属规则 13 的预期行为，不计入示例自身步骤）
        assert [s.stepId for s in suffix][:2] == ["agent_congestion_01",
                                                  "agent_dispatch_01"]
        for s in suffix[:2]:
            assert s.actionType in (None, ""), \
                "示例 agent 步骤不得携带 action（agent-only 示例契约）"

    def test_number_type_not_quoted_string(self):
        """§9 D：number 不得用 quoted string —— prompt 明确给出 0.3 vs \"0.3\"。"""
        system, _user = _grounded_prompts()
        assert "如 0.3" in system
        assert '不得写成 "0.3"' in system


class TestCompilerParameterHintsContract:
    """§10：真实 production compiler（normalize_parameter_hints）非网络契约，
    证明 prompt 文案与 compiler 行为一致。禁止修改 compiler 迎合测试。"""

    def test_case1_placeholder_string_target_road_ids_rejected(self):
        from backend.planning.param_schema import normalize_parameter_hints
        from backend.planning.proposal import PlannerFailure, PlannerFailureCode

        with pytest.raises(PlannerFailure) as e:
            normalize_parameter_hints(
                "simulation_traffic_diversion",
                {"target_road_ids": "待定", "source_road_id": "road_1"},
            )
        assert e.value.code == PlannerFailureCode.INVALID_PARAMETER_HINTS

    def test_case2_list_of_strings_target_road_ids_passes(self):
        from backend.planning.param_schema import normalize_parameter_hints

        normalized = normalize_parameter_hints(
            "simulation_traffic_diversion",
            {"source_road_id": "road_1", "target_road_ids": ["road_1"]},
        )
        # 类型校验 PASS；required（source_road_id + target_road_ids）均已满足
        assert normalized == {"source_road_id": "road_1", "target_road_ids": ["road_1"]}

    def test_case3_quoted_diversion_ratio_rejected(self):
        from backend.planning.param_schema import normalize_parameter_hints
        from backend.planning.proposal import PlannerFailure, PlannerFailureCode

        with pytest.raises(PlannerFailure) as e:
            normalize_parameter_hints(
                "simulation_traffic_diversion",
                {"source_road_id": "road_1", "target_road_ids": ["road_1"],
                 "diversion_ratio": "0.3"},
            )
        assert e.value.code == PlannerFailureCode.INVALID_PARAMETER_HINTS
        assert "diversion_ratio" in e.value.message

    def test_case4_numeric_diversion_ratio_passes(self):
        from backend.planning.param_schema import normalize_parameter_hints

        normalized = normalize_parameter_hints(
            "simulation_traffic_diversion",
            {"source_road_id": "road_1", "target_road_ids": ["road_1"],
             "diversion_ratio": 0.3},
        )
        # 类型校验 PASS（0.3 为 JSON number）；required 均已满足
        assert normalized["diversion_ratio"] == 0.3
        assert set(normalized) == {"source_road_id", "target_road_ids", "diversion_ratio"}
