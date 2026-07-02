"""报告相关 Schema"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class DailyReportResponse(BaseModel):
    """日报响应"""
    date: str = ""
    totalEvents: int = 0
    highRiskEvents: int = 0
    majorRiskEvents: int = 0
    unclosedEvents: int = 0
    topRoads: List[Dict[str, Any]] = Field(default_factory=list)
    eventTypeDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    riskLevelDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    statusDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    keyFindings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    reportText: str = ""
    trendSummary: str = ""


class WeeklyReportResponse(BaseModel):
    """周报响应"""
    startDate: str = ""
    endDate: str = ""
    totalEvents: int = 0
    highRiskEvents: int = 0
    majorRiskEvents: int = 0
    unclosedEvents: int = 0
    topRoads: List[Dict[str, Any]] = Field(default_factory=list)
    eventTypeDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    riskLevelDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    statusDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    keyFindings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    reportText: str = ""
    trendSummary: List[Dict[str, Any]] = Field(default_factory=list)


class StatsResponse(BaseModel):
    """统计响应"""
    totalEvents: int = 0
    highRiskCount: int = 0
    avgRiskScore: float = 0.0
    pendingDispatch: int = 0
    riskDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    eventTypeDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    statusDistribution: List[Dict[str, Any]] = Field(default_factory=list)
    dailyTrend: List[Dict[str, Any]] = Field(default_factory=list)
