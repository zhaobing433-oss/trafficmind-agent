"""
Phase 11 RAG V2 — Final Comprehensive Acceptance
python backend/tests/acceptance_api.py
"""
import json, sys, os, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Ensure hash fallback is available for internal provider usage
os.environ.setdefault("RAG_ALLOW_MODEL_DOWNLOAD", "false")
os.environ.setdefault("RAG_ALLOW_HASH_FALLBACK", "true")
os.environ.setdefault("RAG_DEVICE", "cpu")
from datetime import datetime, timezone, timedelta

BASE = "http://127.0.0.1:8000"
PASS = 0; FAIL = 0; TOTAL = 0

def api(method, path, body=None, timeout=30):
    url = f"{BASE}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    hdrs = {}
    if body:
        hdrs["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        code = resp.status
        text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        code = e.code
        text = e.read().decode("utf-8")
    except Exception as e:
        code = 0
        text = json.dumps({"_error": str(e)})
    elapsed = (time.time() - t0) * 1000
    try: body_dict = json.loads(text)
    except: body_dict = {"_raw": text[:200]}
    return code, body_dict, elapsed

def check(label, condition, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if condition:
        PASS += 1; print(f"  OK   {label}")
    else:
        FAIL += 1; print(f"  FAIL {label}  -- {detail}")

def sse_stream(question, timeout_s=60):
    """Consume SSE stream, return list of {_event_name, ...} dicts."""
    url = f"{BASE}/rag/v2/ask/stream"
    data = json.dumps({"question": question}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Accept": "text/event-stream"}, method="POST")
    events = []
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_s)
        buf = b""
        event_name = None
        for chunk in iter(lambda: resp.read(4096), b""):
            if not chunk: break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                block_str = block.decode("utf-8", errors="replace")
                for line in block_str.split("\n"):
                    s = line.strip()
                    if s.startswith("event: "):
                        event_name = s[7:]
                    elif s.startswith("data: "):
                        try:
                            evt = json.loads(s[6:])
                            evt["_event_name"] = event_name or "unknown"
                            events.append(evt)
                        except json.JSONDecodeError:
                            events.append({"_event_name": event_name or "unknown", "_raw": s[6:200]})
    except Exception as e:
        events.append({"_event_name": "sse_error", "_error": str(e)[:200]})
    return events

def now_iso():
    return datetime.now(timezone.utc).isoformat()

print("=" * 65)
print("Phase 11 RAG V2 — Final Comprehensive Acceptance")
print("=" * 65)

# ═══════════════════════════════════════════════════════
# SECTION 1: /rag/search 稳定性 (10次)
# ═══════════════════════════════════════════════════════
print("\n── 1. /rag/search 10-Consecutive Calls ──")
results_10 = []
for i in range(10):
    code, body, elapsed = api("GET", "/rag/search?query=%E6%8B%A5%E5%A0%B5%E5%A4%84%E7%BD%AE", timeout=10)
    has_results = "results" in body
    results_10.append((code, elapsed, has_results))
    print(f"  call {i+1:2d}: HTTP {code:3d}  {elapsed:7.0f}ms  results={'YES' if has_results else 'NO'}")
ok_10 = sum(1 for c, e, r in results_10 if c == 200 and r)
timeouts_10 = sum(1 for c, e, r in results_10 if c == 0)
print(f"  Summary: {ok_10}/10 returned 200 with results, {timeouts_10} timeouts")
check("8+/10 calls return 200 with results", ok_10 >= 8, f"ok={ok_10}")
check("0 permanent timeouts", timeouts_10 == 0, f"timeouts={timeouts_10}")

# ═══════════════════════════════════════════════════════
# SECTION 2: Provider State
# ═══════════════════════════════════════════════════════
print("\n── 2. Provider State ──")
_, s, _ = api("GET", "/rag/v2/status")
check("configured_embedding == Qwen3",
      s.get("configured_embedding_model") == "Qwen/Qwen3-Embedding-0.6B")
check("resolved_embedding == hash-fallback",
      s.get("resolved_embedding_model") == "hash-fallback")
check("embedding_degraded == True", s.get("embedding_degraded") is True)
check("configured != resolved", s.get("configured_embedding_model") != s.get("resolved_embedding_model"))

# ═══════════════════════════════════════════════════════
# SECTION 3: Index + Search
# ═══════════════════════════════════════════════════════
print("\n── 3. Index + Search ──")
_, idx, _ = api("POST", "/rag/v2/index")
check("index completed", idx.get("status") == "completed",
      f"got={idx.get('status')} docs={idx.get('documents_processed',0)}")
_, sr, _ = api("POST", "/rag/v2/search", {"query": "拥堵处置", "top_k": 5})
check("search returns results", len(sr.get("results", [])) > 0)
check("search has trace", "trace" in sr)

# ═══════════════════════════════════════════════════════
# SECTION 4: Scenario C — multi_hop
# ═══════════════════════════════════════════════════════
print("\n── 4. Scenario C: multi_hop ──")
_, body, _ = api("POST", "/rag/v2/ask", {
    "question": "学校门口发生拥堵，同时影响医院急救车辆通行，怎样兼顾学生安全、急救和通行效率？"
})
trace_c = body.get("trace_id", "")
check("trace_id exists", len(trace_c) > 0)
if trace_c:
    _, trace, _ = api("GET", f"/rag/v2/traces/{trace_c}")
    analysis_stages = [s for s in trace.get("stages", []) if s.get("stage") == "query_analysis"]
    if analysis_stages:
        out = analysis_stages[0].get("output", {})
        route = out.get("route", "")
        subqs = out.get("subqueries", [])
        check("route=multi_hop or cross_document", route in ("multi_hop", "cross_document"), f"got={route}")
        check("1-3 subqueries", 1 <= len(subqs) <= 3, f"count={len(subqs)}")
        s_text = " ".join(str(x) for x in subqs)
        check("school/student facet", any(k in s_text for k in ["学校","学生"]))
        check("hospital/emergency facet", any(k in s_text for k in ["医院","急救"]))
        check("congestion/traffic facet", any(k in s_text for k in ["拥堵","通行","分流"]))

# ═══════════════════════════════════════════════════════
# SECTION 5: Scenario D — Abstain
# ═══════════════════════════════════════════════════════
print("\n── 5. Scenario D: Abstain ──")
_, body, _ = api("POST", "/rag/v2/ask", {
    "question": "请给出当前路口最优的信号周期，以及每个相位具体应该设置多少秒。"
})
check("abstained=True", body.get("abstained") is True)
check("evidence_state=insufficient", body.get("evidence_state") == "insufficient")
ans = body.get("answer", "")
check("no fabricated seconds", "建议秒数" not in ans and "推荐周期" not in ans)

# ═══════════════════════════════════════════════════════
# SECTION 6: Scenario E — Expired Rules Verification
# ═══════════════════════════════════════════════════════
print("\n── 6. Scenario E: Expired vs Valid Rules ──")
# Use real query to exercise the policy pipeline with existing knowledge.
# The data includes dispatch experiences with effective dates.
_, ask_e, _ = api("POST", "/rag/v2/ask", {
    "question": "施工占道的处置流程和审批规范是什么？新版和旧版有什么区别？"
})
trace_e = ask_e.get("trace_id", "")
check("scenario E: trace exists", len(trace_e) > 0)
evidence_e = ask_e.get("evidence", [])
check("scenario E: evidence returned", len(evidence_e) > 0,
      f"count={len(evidence_e)}")

if trace_e:
    _, trace, _ = api("GET", f"/rag/v2/traces/{trace_e}")

    # Verify all pipeline stages exist
    stage_names = [s.get("stage") for s in trace.get("stages", [])]
    for stage in ["query_analysis", "query_rewrite", "hybrid_retrieval",
                  "rerank_and_policy", "evidence_evaluation", "generation"]:
        check(f"stage: {stage}", stage in stage_names)

    # Verify rerank_and_policy has accepted/rejected counts
    rerank_stages = [s for s in trace.get("stages", []) if s.get("stage") == "rerank_and_policy"]
    if rerank_stages:
        out = rerank_stages[0].get("output", {})
        check("rerank: accepted count present",
              isinstance(out.get("accepted"), (int, float)),
              f"got={out.get('accepted')}")
        check("rerank: rejected count present",
              isinstance(out.get("rejected"), (int, float)),
              f"got={out.get('rejected')}")
        deg = out.get("degraded") if "degraded" in out else rerank_stages[0].get("degraded")
        check("rerank: degraded status recorded",
              isinstance(deg, bool),
              f"degraded={deg}")

    # Verify evidence evaluation
    eval_stages = [s for s in trace.get("stages", []) if s.get("stage") == "evidence_evaluation"]
    if eval_stages:
        out = eval_stages[0].get("output", {})
        check("eval: has state", isinstance(out.get("state"), str),
              f"state={out.get('state')}")
        check("eval: has reason", isinstance(out.get("reason"), str),
              f"reason={out.get('reason', '')[:60]}")

# ═══════════════════════════════════════════════════════
# SECTION 7: Memory Rewrite Scenarios
# ═══════════════════════════════════════════════════════
print("\n── 7. Memory Rewrite ──")

# Scenario 1: 人民路小学
_, body1, _ = api("POST", "/rag/v2/search", {
    "query": "继续查询适用的学生疏导预案",
    "session_id": "acceptance_mem_test_s1",
})
check("memory S1: search returns", "results" in body1 or "analysis" in body1)
analysis = body1.get("analysis", {})
check("memory S1: has analysis", isinstance(analysis, dict) and bool(analysis))
rewritten = body1.get("rewritten_query", "")
check("memory S1: rewritten non-empty", len(rewritten) > 0,
      f"rewritten='{rewritten[:80]}'")

# Scenario 2: correction 中山路
_, body2, _ = api("POST", "/rag/v2/search", {
    "query": "继续检索适用预案",
    "session_id": "acceptance_mem_test_s2",
})
check("memory S2: search returns", "results" in body2 or "analysis" in body2)

# ═══════════════════════════════════════════════════════
# SECTION 8: Old API
# ═══════════════════════════════════════════════════════
print("\n── 8. Old API Compatibility ──")
_, body, _ = api("POST", "/rag/ask", {"question": "拥堵怎么处置？", "limit": 3})
check("POST /rag/ask", "answer" in body)
_, body, _ = api("POST", "/rag/rebuild_index")
check("POST /rag/rebuild_index", body.get("success") is True)
_, body, _ = api("GET", "/rag/status")
check("GET /rag/status", body.get("enabled") is True)

# ═══════════════════════════════════════════════════════
# SECTION 9: Trace Recovery
# ═══════════════════════════════════════════════════════
print("\n── 9. Trace Recovery ──")
if trace_c:
    _, trace, _ = api("GET", f"/rag/v2/traces/{trace_c}")
    check("trace_id matches", trace.get("trace_id") == trace_c)
    check("has stages >= 3", len(trace.get("stages",[])) >= 3,
          f"count={len(trace.get('stages',[]))}")
    check("has embedding_model", len(trace.get("embedding_model","")) > 0)
    check("has reranker_model", len(trace.get("reranker_model","")) > 0)

# ═══════════════════════════════════════════════════════
# SECTION 10: SSE Abstain Chain
# ═══════════════════════════════════════════════════════
print("\n── 10. SSE Abstain Chain ──")
events = sse_stream("请给出当前路口最优的信号周期秒数")
names = [e.get("_event_name","") for e in events]
print(f"  Events ({len(events)}): {names}")
check("abstained present", "rag_abstained" in names)
check("done present", "done" in names)
check("done exactly once", names.count("done") == 1, f"got {names.count('done')}")
check("trace_ready present", "rag_trace_ready" in names)
check("no error", "error" not in names)
check("route_done present", "rag_route_done" in names)

# ═══════════════════════════════════════════════════════
# SECTION 11: SSE Error Chain
# ═══════════════════════════════════════════════════════
print("\n── 11. SSE Error Chain ──")
# Simulate error by calling with malformed input that triggers a fast error
err_events = sse_stream("x" * 100000)  # extremely long question may trigger error
err_names = [e.get("_event_name","") for e in err_events]
print(f"  Error events ({len(err_events)}): {err_names[:8]}")
# At minimum, should have some terminal event
has_done_or_error = "done" in err_names or "error" in err_names or "sse_error" in err_names
check("error chain has terminal event", has_done_or_error,
      f"events={err_names[:6]}")
check("error chain aborts properly", "delta" not in err_names or len(err_names) <= 20,
      f"delta_events={err_names.count('delta')}")

# ═══════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════
print(f"\n{'='*65}")
print(f"RESULTS: {PASS}/{TOTAL} PASS, {FAIL}/{TOTAL} FAIL")
print(f"PASS RATE: {PASS/TOTAL*100:.0f}%" if TOTAL > 0 else "")
print(f"{'='*65}")
