"""Read-only Evaluation Dashboard API."""
from fastapi import APIRouter, HTTPException, Query
from backend.evaluation.history_repository import list_reports, get_report, get_case, compare_reports
from backend.observability.models import sanitize_observability

router = APIRouter(prefix="/evaluation", tags=["Evaluation Dashboard"])


@router.get("/reports", summary="列出 Evaluation Reports")
async def api_list_reports(limit: int = Query(default=50, le=100)):
    return {"reports": list_reports(limit)}


@router.get("/reports/{report_id}", summary="获取完整 Evaluation Report")
async def api_get_report(report_id: str):
    report = get_report(report_id)
    if report is None: raise HTTPException(status_code=404, detail="Report not found")
    return sanitize_observability(report)


@router.get("/reports/{report_id}/cases/{case_id}", summary="获取单个 Evaluation Case")
async def api_get_case(report_id: str, case_id: str):
    case = get_case(report_id, case_id)
    if case is None: raise HTTPException(status_code=404, detail="Case not found")
    return sanitize_observability(case)


@router.get("/compare", summary="比较两个 Evaluation Report")
async def api_compare(base: str = Query(...), target: str = Query(...)):
    result = compare_reports(base, target)
    if result is None: raise HTTPException(status_code=404, detail="Report not found")
    return result
