/** 前端类型定义 — 第二阶段扩展 */

/** 统计分析请求体 */
export interface AnalyzeEventRequest {
  eventId: string;
  eventType: string;
  cameraId?: string;
  roadName: string;
  direction?: string;
  lane?: string;
  avgSpeed: number;
  queueLength: number;
  duration: number;
  vehicleCount?: number;
  weather?: string;
  timePeriod?: string;
  isMainRoad?: boolean;
  nearbySchool?: boolean;
  nearbyHospital?: boolean;
  confidence?: number;
}

/** 标准化事件对象 */
export interface StandardEvent {
  eventId: string;
  eventType: string;
  eventTypeCn: string;
  cameraId: string;
  roadName: string;
  direction: string;
  lane: string;
  avgSpeed: number;
  queueLength: number;
  duration: number;
  vehicleCount: number;
  confidence: number;
  weather: string;
  timePeriod: string;
  isMainRoad: boolean;
  nearbySchool: boolean;
  nearbyHospital: boolean;
}

/** /analyze_event 返回体 */
export interface AnalyzeResult {
  eventId: string;
  standardEvent: StandardEvent;
  riskScore: number;
  riskLevel: string;
  riskReasons: string[];
  matchedRule: string;
  suggestions: string[];
  dispatchMessage: string;
  publicMessage: string;
  report: string;
  status: string;
  saved: boolean;
  analyzedAt: string;
}

/** /history 中的单条记录 */
export interface EventRecord {
  eventId: string;
  eventType: string;
  eventTypeCn: string;
  roadName: string;
  riskScore: number;
  riskLevel: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

/** /stats 返回体 */
export interface StatsResponse {
  totalEvents: number;
  highRiskCount: number;
  avgRiskScore: number;
  pendingDispatch: number;
  riskDistribution: { level: string; count: number }[];
  eventTypeDistribution: { type: string; count: number }[];
  statusDistribution: { status: string; count: number }[];
  dailyTrend: { date: string; count: number }[];
}

/** 相似案例 */
export interface SimilarCase {
  eventId: string;
  eventType: string;
  roadName: string;
  direction: string;
  riskScore: number;
  riskLevel: string;
  status: string;
  similarityScore: number;
  similarityReasons: string[];
  report: string;
  createdAt: string;
}

/** /similar_cases 返回体 */
export interface SimilarCasesResponse {
  currentEvent: {
    eventId: string;
    eventType: string;
    roadName: string;
    direction: string;
    riskScore: number;
    riskLevel: string;
    status: string;
    createdAt: string;
  } | null;
  similarCases: SimilarCase[];
  error?: string;
}

/** 日报 */
export interface DailyReportResponse {
  date: string;
  totalEvents: number;
  highRiskEvents: number;
  majorRiskEvents: number;
  unclosedEvents: number;
  topRoads: { roadName: string; count: number }[];
  eventTypeDistribution: { type: string; count: number }[];
  riskLevelDistribution: { level: string; count: number }[];
  statusDistribution: { status: string; count: number }[];
  keyFindings: string[];
  suggestions: string[];
  reportText: string;
  trendSummary: string;
}

/** 周报 */
export interface WeeklyReportResponse {
  startDate: string;
  endDate: string;
  totalEvents: number;
  highRiskEvents: number;
  majorRiskEvents: number;
  unclosedEvents: number;
  topRoads: { roadName: string; count: number }[];
  eventTypeDistribution: { type: string; count: number }[];
  riskLevelDistribution: { level: string; count: number }[];
  statusDistribution: { status: string; count: number }[];
  keyFindings: string[];
  suggestions: string[];
  reportText: string;
  trendSummary: { date: string; count: number }[];
}

/** 未闭环告警 */
export interface AlertItem {
  eventId: string;
  eventType: string;
  roadName: string;
  direction: string;
  riskLevel: string;
  riskScore: number;
  status: string;
  createdAt: string;
  durationSinceCreated: string;
  alertReason: string;
  recommendedAction: string;
}

/** /alerts/unclosed 返回体 */
export interface UnclosedAlertsResponse {
  count: number;
  alerts: AlertItem[];
}

/** 高风险路口 */
export interface HighRiskRoad {
  roadName: string;
  totalEvents: number;
  highRiskCount: number;
  majorRiskCount: number;
  avgRiskScore: number;
  mostCommonEventType: string;
  unclosedCount: number;
  suggestedAction: string;
}

/** /stats/high_risk_roads 返回体 */
export interface HighRiskRoadsResponse {
  range: string;
  topRoads: HighRiskRoad[];
}
