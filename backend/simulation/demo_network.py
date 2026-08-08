"""
Demo 路网定义 — Phase 13 V1

小型演示交通网络，使用真实经纬度格式（≈北京中心坐标偏移），
所有名称标记为演示/模拟数据。

结构:
  6 Intersections (路口)
  12 RoadSegments (双向路段)
  6 Cameras (模拟传感器)

  2-3 可注入事件位置 (R01/R03/I01)
"""

from backend.simulation.models import (
    TrafficIntersection,
    TrafficRoadSegment,
    TrafficCameraSensor,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Intersections
# ═══════════════════════════════════════════════════════════════════════════════

INTERSECTIONS: list[TrafficIntersection] = [
    TrafficIntersection(
        intersection_id="I01",
        name="演示北路口（模拟路网）",
        longitude=116.397,
        latitude=39.908,
        connected_road_ids=["R01", "R02", "R07", "R08", "R11", "R12"],
        signal_state="normal",
    ),
    TrafficIntersection(
        intersection_id="I02",
        name="演示南路口（模拟路网）",
        longitude=116.397,
        latitude=39.904,
        connected_road_ids=["R01", "R02", "R09", "R10"],
        signal_state="normal",
    ),
    TrafficIntersection(
        intersection_id="I03",
        name="创新路西口（模拟路网）",
        longitude=116.395,
        latitude=39.906,
        connected_road_ids=["R03", "R04", "R07", "R08"],
        signal_state="normal",
    ),
    TrafficIntersection(
        intersection_id="I04",
        name="创新路东口（模拟路网）",
        longitude=116.400,
        latitude=39.906,
        connected_road_ids=["R03", "R04", "R09", "R10"],
        signal_state="normal",
    ),
    TrafficIntersection(
        intersection_id="I05",
        name="智慧路西口（模拟路网）",
        longitude=116.394,
        latitude=39.907,
        connected_road_ids=["R05", "R06", "R11", "R12"],
        signal_state="normal",
    ),
    TrafficIntersection(
        intersection_id="I06",
        name="智慧路东口（模拟路网）",
        longitude=116.401,
        latitude=39.907,
        connected_road_ids=["R05", "R06"],
        signal_state="normal",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Road Segments
# ═══════════════════════════════════════════════════════════════════════════════

ROAD_SEGMENTS: list[TrafficRoadSegment] = [
    # ── 演示大道（主干道，双向） ──
    TrafficRoadSegment(
        road_id="R01",
        name="演示大道（北→南）",
        from_intersection_id="I01",
        to_intersection_id="I02",
        geometry=[[116.397, 39.908], [116.397, 39.906], [116.397, 39.904]],
        lanes=3,
        capacity=1800,
        free_flow_speed=50.0,
    ),
    TrafficRoadSegment(
        road_id="R02",
        name="演示大道（南→北）",
        from_intersection_id="I02",
        to_intersection_id="I01",
        geometry=[[116.397, 39.904], [116.397, 39.906], [116.397, 39.908]],
        lanes=3,
        capacity=1800,
        free_flow_speed=50.0,
    ),
    # ── 创新路（次干道，双向） ──
    TrafficRoadSegment(
        road_id="R03",
        name="创新路（西→东）",
        from_intersection_id="I03",
        to_intersection_id="I04",
        geometry=[[116.395, 39.906], [116.3975, 39.906], [116.400, 39.906]],
        lanes=2,
        capacity=1200,
        free_flow_speed=40.0,
    ),
    TrafficRoadSegment(
        road_id="R04",
        name="创新路（东→西）",
        from_intersection_id="I04",
        to_intersection_id="I03",
        geometry=[[116.400, 39.906], [116.3975, 39.906], [116.395, 39.906]],
        lanes=2,
        capacity=1200,
        free_flow_speed=40.0,
    ),
    # ── 智慧路（次干道，双向） ──
    TrafficRoadSegment(
        road_id="R05",
        name="智慧路（西→东）",
        from_intersection_id="I05",
        to_intersection_id="I06",
        geometry=[[116.394, 39.907], [116.3975, 39.907], [116.401, 39.907]],
        lanes=2,
        capacity=1200,
        free_flow_speed=40.0,
    ),
    TrafficRoadSegment(
        road_id="R06",
        name="智慧路（东→西）",
        from_intersection_id="I06",
        to_intersection_id="I05",
        geometry=[[116.401, 39.907], [116.3975, 39.907], [116.394, 39.907]],
        lanes=2,
        capacity=1200,
        free_flow_speed=40.0,
    ),
    # ── 交通路（连接路，双向） ──
    TrafficRoadSegment(
        road_id="R07",
        name="交通路（北→南西）",
        from_intersection_id="I01",
        to_intersection_id="I03",
        geometry=[[116.397, 39.908], [116.396, 39.907], [116.395, 39.906]],
        lanes=2,
        capacity=800,
        free_flow_speed=35.0,
    ),
    TrafficRoadSegment(
        road_id="R08",
        name="交通路（南西→北）",
        from_intersection_id="I03",
        to_intersection_id="I01",
        geometry=[[116.395, 39.906], [116.396, 39.907], [116.397, 39.908]],
        lanes=2,
        capacity=800,
        free_flow_speed=35.0,
    ),
    # ── 科技路（连接路，双向） ──
    TrafficRoadSegment(
        road_id="R09",
        name="科技路（东→南）",
        from_intersection_id="I04",
        to_intersection_id="I02",
        geometry=[[116.400, 39.906], [116.3985, 39.905], [116.397, 39.904]],
        lanes=2,
        capacity=800,
        free_flow_speed=35.0,
    ),
    TrafficRoadSegment(
        road_id="R10",
        name="科技路（南→东）",
        from_intersection_id="I02",
        to_intersection_id="I04",
        geometry=[[116.397, 39.904], [116.3985, 39.905], [116.400, 39.906]],
        lanes=2,
        capacity=800,
        free_flow_speed=35.0,
    ),
    # ── 演示北路（连接路，双向） ──
    TrafficRoadSegment(
        road_id="R11",
        name="演示北路（北→西）",
        from_intersection_id="I01",
        to_intersection_id="I05",
        geometry=[[116.397, 39.908], [116.3955, 39.9075], [116.394, 39.907]],
        lanes=2,
        capacity=800,
        free_flow_speed=35.0,
    ),
    TrafficRoadSegment(
        road_id="R12",
        name="演示北路（西→北）",
        from_intersection_id="I05",
        to_intersection_id="I01",
        geometry=[[116.394, 39.907], [116.3955, 39.9075], [116.397, 39.908]],
        lanes=2,
        capacity=800,
        free_flow_speed=35.0,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Cameras
# ═══════════════════════════════════════════════════════════════════════════════

CAMERAS: list[TrafficCameraSensor] = [
    TrafficCameraSensor(
        camera_id="CAM01",
        name="演示大道北段摄像头（模拟）",
        longitude=116.397,
        latitude=39.907,
        road_id="R01",
        status="active",
        simulated=True,
    ),
    TrafficCameraSensor(
        camera_id="CAM02",
        name="演示大道南段摄像头（模拟）",
        longitude=116.397,
        latitude=39.905,
        road_id="R02",
        status="active",
        simulated=True,
    ),
    TrafficCameraSensor(
        camera_id="CAM03",
        name="创新路西段摄像头（模拟）",
        longitude=116.396,
        latitude=39.906,
        road_id="R03",
        status="active",
        simulated=True,
    ),
    TrafficCameraSensor(
        camera_id="CAM04",
        name="创新路东段摄像头（模拟）",
        longitude=116.399,
        latitude=39.906,
        road_id="R04",
        status="active",
        simulated=True,
    ),
    TrafficCameraSensor(
        camera_id="CAM05",
        name="智慧路西段摄像头（模拟）",
        longitude=116.396,
        latitude=39.907,
        road_id="R05",
        status="active",
        simulated=True,
    ),
    TrafficCameraSensor(
        camera_id="CAM06",
        name="交通路口摄像头（模拟）",
        longitude=116.396,
        latitude=39.907,
        road_id="R07",
        status="active",
        simulated=True,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# 聚合
# ═══════════════════════════════════════════════════════════════════════════════


class DemoNetwork:
    """Demo 路网聚合对象。"""

    def __init__(self):
        self.intersections: dict[str, TrafficIntersection] = {
            i.intersection_id: i for i in INTERSECTIONS
        }
        self.road_segments: dict[str, TrafficRoadSegment] = {
            r.road_id: r for r in ROAD_SEGMENTS
        }
        self.cameras: dict[str, TrafficCameraSensor] = {
            c.camera_id: c for c in CAMERAS
        }

    def get_intersection(self, iid: str) -> TrafficIntersection | None:
        return self.intersections.get(iid)

    def get_road(self, rid: str) -> TrafficRoadSegment | None:
        return self.road_segments.get(rid)

    def get_camera(self, cid: str) -> TrafficCameraSensor | None:
        return self.cameras.get(cid)

    def get_cameras_on_road(self, rid: str) -> list[TrafficCameraSensor]:
        return [c for c in self.cameras.values() if c.road_id == rid]

    def get_roads_at_intersection(self, iid: str) -> list[TrafficRoadSegment]:
        """获取经过某路口的所有路段。"""
        return [
            r for r in self.road_segments.values()
            if r.from_intersection_id == iid or r.to_intersection_id == iid
        ]

    def get_connected_intersections(self, iid: str) -> list[TrafficIntersection]:
        """获取与某路口相邻的路口。"""
        inter = self.intersections.get(iid)
        if not inter:
            return []
        neighbor_ids: set[str] = set()
        for rid in inter.connected_road_ids:
            road = self.road_segments.get(rid)
            if road:
                if road.from_intersection_id == iid:
                    neighbor_ids.add(road.to_intersection_id)
                elif road.to_intersection_id == iid:
                    neighbor_ids.add(road.from_intersection_id)
        return [self.intersections[nid] for nid in neighbor_ids if nid in self.intersections]

    def get_intersections_near_point(
        self, lng: float, lat: float, max_distance: float = 0.01
    ) -> list[TrafficIntersection]:
        """简单距离筛选获取附近路口。"""
        result = []
        for inter in self.intersections.values():
            dist = ((inter.longitude - lng) ** 2 + (inter.latitude - lat) ** 2) ** 0.5
            if dist <= max_distance:
                result.append(inter)
        return result

    def get_cameras_near_point(
        self, lng: float, lat: float, max_distance: float = 0.015
    ) -> list[TrafficCameraSensor]:
        """简单距离筛选获取附近摄像头。"""
        result = []
        for cam in self.cameras.values():
            dist = ((cam.longitude - lng) ** 2 + (cam.latitude - lat) ** 2) ** 0.5
            if dist <= max_distance:
                result.append(cam)
        return result

    def to_geojson(self) -> dict:
        """将路网转为 GeoJSON FeatureCollection。"""
        features = []
        for road in self.road_segments.values():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": road.geometry,
                },
                "properties": {
                    "roadId": road.road_id,
                    "name": road.name,
                    "lanes": road.lanes,
                    "capacity": road.capacity,
                    "freeFlowSpeed": road.free_flow_speed,
                    "featureType": "road",
                },
            })
        for inter in self.intersections.values():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [inter.longitude, inter.latitude],
                },
                "properties": {
                    "intersectionId": inter.intersection_id,
                    "name": inter.name,
                    "signalState": inter.signal_state,
                    "connectedRoadIds": inter.connected_road_ids,
                    "featureType": "intersection",
                },
            })
        for cam in self.cameras.values():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [cam.longitude, cam.latitude],
                },
                "properties": {
                    "cameraId": cam.camera_id,
                    "name": cam.name,
                    "roadId": cam.road_id,
                    "status": cam.status,
                    "simulated": cam.simulated,
                    "featureType": "camera",
                },
            })
        return {"type": "FeatureCollection", "features": features}


# 全局单例
DEMO_NETWORK = DemoNetwork()
