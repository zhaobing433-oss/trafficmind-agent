/** 前端类型定义 */

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

/** 事件动态推送条目 */
export interface NotifItem {
  eventId: string;
  eventTypeCn: string;
  roadName: string;
  riskLevel: string;
  riskScore: number;
  analyzedAt: string;
}
