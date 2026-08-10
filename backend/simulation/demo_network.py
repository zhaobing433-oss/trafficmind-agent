"""
Demo 路网定义 — Phase 13 Frontend Closure

城市街区结构 (2x3 grid with diagonals):
  I01 — I02 — I03   (北主干道: 演示大道)
   |  \  |  /  |
  I04 — I05 — I06   (中主干道: 创新路)
   |  /  |  \  |
  I07 — I08 — I09   (南主干道: 智慧路)

6 intersections → 9 intersections (city feel)
12 roads → 16 roads (bidirectional main + connectors)
6 cameras → 6 cameras (unchanged)
"""

from backend.simulation.models import TrafficIntersection, TrafficRoadSegment, TrafficCameraSensor

INTERSECTIONS: list[TrafficIntersection] = [
    TrafficIntersection(intersection_id="I01", name="演示北路口（模拟路网）", longitude=116.395, latitude=39.910, connected_road_ids=["R01","R02","R07","R08","R13","R14"], signal_state="normal"),
    TrafficIntersection(intersection_id="I02", name="演示中路口（模拟路网）", longitude=116.400, latitude=39.910, connected_road_ids=["R01","R02","R03","R04"], signal_state="normal"),
    TrafficIntersection(intersection_id="I03", name="演示东路口（模拟路网）", longitude=116.405, latitude=39.910, connected_road_ids=["R03","R04","R09","R10"], signal_state="normal"),
    TrafficIntersection(intersection_id="I04", name="创新西路口（模拟路网）", longitude=116.393, latitude=39.907, connected_road_ids=["R07","R08","R05","R06","R13","R14"], signal_state="normal"),
    TrafficIntersection(intersection_id="I05", name="创新中路口（模拟路网）", longitude=116.400, latitude=39.907, connected_road_ids=["R05","R06","R05b","R06b","R03","R04"], signal_state="normal"),
    TrafficIntersection(intersection_id="I06", name="创新东路口（模拟路网）", longitude=116.407, latitude=39.907, connected_road_ids=["R05b","R06b","R09","R10"], signal_state="normal"),
    TrafficIntersection(intersection_id="I07", name="智慧西路口（模拟路网）", longitude=116.393, latitude=39.904, connected_road_ids=["R11","R12","R13","R14"], signal_state="normal"),
    TrafficIntersection(intersection_id="I08", name="智慧中路口（模拟路网）", longitude=116.400, latitude=39.904, connected_road_ids=["R11","R12","R15","R16"], signal_state="normal"),
    TrafficIntersection(intersection_id="I09", name="智慧东路口（模拟路网）", longitude=116.407, latitude=39.904, connected_road_ids=["R15","R16"], signal_state="normal"),
]

ROAD_SEGMENTS: list[TrafficRoadSegment] = [
    # === 演示大道 (主干道, 北线) ===
    TrafficRoadSegment(road_id="R01", name="演示大道（西→东）", from_intersection_id="I01", to_intersection_id="I02", geometry=[[116.395,39.910],[116.3975,39.910],[116.400,39.910]], lanes=3, capacity=1800, free_flow_speed=50),
    TrafficRoadSegment(road_id="R02", name="演示大道（东→西）", from_intersection_id="I02", to_intersection_id="I01", geometry=[[116.400,39.910],[116.3975,39.9098],[116.395,39.9098]], lanes=3, capacity=1800, free_flow_speed=50),
    # === 演示大道东段 ===
    TrafficRoadSegment(road_id="R03", name="演示大道东（西→东）", from_intersection_id="I02", to_intersection_id="I03", geometry=[[116.400,39.910],[116.4025,39.910],[116.405,39.910]], lanes=3, capacity=1800, free_flow_speed=50),
    TrafficRoadSegment(road_id="R04", name="演示大道东（东→西）", from_intersection_id="I03", to_intersection_id="I02", geometry=[[116.405,39.910],[116.4025,39.9098],[116.400,39.9098]], lanes=3, capacity=1800, free_flow_speed=50),

    # === 创新路 (次干道, 中线) ===
    TrafficRoadSegment(road_id="R05", name="创新路（西→东）", from_intersection_id="I04", to_intersection_id="I05", geometry=[[116.393,39.907],[116.3965,39.907],[116.400,39.907]], lanes=2, capacity=1200, free_flow_speed=40),
    TrafficRoadSegment(road_id="R06", name="创新路（东→西）", from_intersection_id="I05", to_intersection_id="I04", geometry=[[116.400,39.907],[116.3965,39.9068],[116.393,39.9068]], lanes=2, capacity=1200, free_flow_speed=40),
    # 创新路东段
    TrafficRoadSegment(road_id="R05b", name="创新路东（西→东）", from_intersection_id="I05", to_intersection_id="I06", geometry=[[116.400,39.907],[116.4035,39.907],[116.407,39.907]], lanes=2, capacity=1200, free_flow_speed=40),
    TrafficRoadSegment(road_id="R06b", name="创新路东（东→西）", from_intersection_id="I06", to_intersection_id="I05", geometry=[[116.407,39.907],[116.4035,39.9068],[116.400,39.9068]], lanes=2, capacity=1200, free_flow_speed=40),

    # === 南北连接路 (交通路) ===
    TrafficRoadSegment(road_id="R07", name="交通路（北→南）", from_intersection_id="I04", to_intersection_id="I01", geometry=[[116.393,39.907],[116.394,39.9085],[116.395,39.910]], lanes=2, capacity=800, free_flow_speed=35),
    TrafficRoadSegment(road_id="R08", name="交通路（南→北）", from_intersection_id="I01", to_intersection_id="I04", geometry=[[116.395,39.910],[116.394,39.9085],[116.3932,39.907]], lanes=2, capacity=800, free_flow_speed=35),
    # 东侧南北连接 (科技路)
    TrafficRoadSegment(road_id="R09", name="科技路（北→南）", from_intersection_id="I06", to_intersection_id="I03", geometry=[[116.407,39.907],[116.406,39.9085],[116.405,39.910]], lanes=2, capacity=800, free_flow_speed=35),
    TrafficRoadSegment(road_id="R10", name="科技路（南→北）", from_intersection_id="I03", to_intersection_id="I06", geometry=[[116.405,39.910],[116.406,39.9085],[116.4072,39.907]], lanes=2, capacity=800, free_flow_speed=35),

    # === 智慧路 (南线次干道) ===
    TrafficRoadSegment(road_id="R11", name="智慧路（西→东）", from_intersection_id="I07", to_intersection_id="I08", geometry=[[116.393,39.904],[116.3965,39.904],[116.400,39.904]], lanes=2, capacity=1200, free_flow_speed=40),
    TrafficRoadSegment(road_id="R12", name="智慧路（东→西）", from_intersection_id="I08", to_intersection_id="I07", geometry=[[116.400,39.904],[116.3965,39.9038],[116.393,39.9038]], lanes=2, capacity=1200, free_flow_speed=40),

    # === 南北纵向连接 (演示北路/南路) ===
    TrafficRoadSegment(road_id="R13", name="演示北路（北→南）", from_intersection_id="I07", to_intersection_id="I04", geometry=[[116.393,39.904],[116.393,39.9055],[116.393,39.907]], lanes=2, capacity=800, free_flow_speed=35),
    TrafficRoadSegment(road_id="R14", name="演示北路（南→北）", from_intersection_id="I04", to_intersection_id="I07", geometry=[[116.393,39.907],[116.3928,39.9055],[116.3928,39.904]], lanes=2, capacity=800, free_flow_speed=35),
    # 东侧纵向
    TrafficRoadSegment(road_id="R15", name="演示南路（北→南）", from_intersection_id="I08", to_intersection_id="I09", geometry=[[116.400,39.904],[116.4035,39.904],[116.407,39.904]], lanes=2, capacity=800, free_flow_speed=35),
    TrafficRoadSegment(road_id="R16", name="演示南路（南→北）", from_intersection_id="I09", to_intersection_id="I08", geometry=[[116.407,39.904],[116.4035,39.9038],[116.400,39.9038]], lanes=2, capacity=800, free_flow_speed=35),
]

CAMERAS: list[TrafficCameraSensor] = [
    TrafficCameraSensor(camera_id="CAM01", name="演示大道中段摄像头（模拟）", longitude=116.3975, latitude=39.910, road_id="R01", status="active", simulated=True),
    TrafficCameraSensor(camera_id="CAM02", name="演示大道东段摄像头（模拟）", longitude=116.4025, latitude=39.910, road_id="R03", status="active", simulated=True),
    TrafficCameraSensor(camera_id="CAM03", name="创新路西段摄像头（模拟）", longitude=116.3965, latitude=39.907, road_id="R05", status="active", simulated=True),
    TrafficCameraSensor(camera_id="CAM04", name="创新路东段摄像头（模拟）", longitude=116.4035, latitude=39.907, road_id="R05b", status="active", simulated=True),
    TrafficCameraSensor(camera_id="CAM05", name="智慧路西段摄像头（模拟）", longitude=116.3965, latitude=39.904, road_id="R11", status="active", simulated=True),
    TrafficCameraSensor(camera_id="CAM06", name="交通路中段摄像头（模拟）", longitude=116.394, latitude=39.9085, road_id="R07", status="active", simulated=True),
]

class DemoNetwork:
    def __init__(self):
        self.intersections = {i.intersection_id: i for i in INTERSECTIONS}
        self.road_segments = {r.road_id: r for r in ROAD_SEGMENTS}
        self.cameras = {c.camera_id: c for c in CAMERAS}

    def get_intersection(self, iid): return self.intersections.get(iid)
    def get_road(self, rid): return self.road_segments.get(rid)
    def get_camera(self, cid): return self.cameras.get(cid)
    def get_cameras_on_road(self, rid): return [c for c in self.cameras.values() if c.road_id == rid]

    def get_roads_at_intersection(self, iid):
        return [r for r in self.road_segments.values() if r.from_intersection_id == iid or r.to_intersection_id == iid]

    def get_connected_intersections(self, iid):
        inter = self.intersections.get(iid)
        if not inter: return []
        neighbor_ids = set()
        for rid in inter.connected_road_ids:
            road = self.road_segments.get(rid)
            if road:
                if road.from_intersection_id == iid: neighbor_ids.add(road.to_intersection_id)
                elif road.to_intersection_id == iid: neighbor_ids.add(road.from_intersection_id)
        return [self.intersections[nid] for nid in neighbor_ids if nid in self.intersections]

    def get_intersections_near_point(self, lng, lat, max_distance=0.01):
        return [i for i in self.intersections.values() if ((i.longitude-lng)**2+(i.latitude-lat)**2)**0.5 <= max_distance]

    def get_cameras_near_point(self, lng, lat, max_distance=0.015):
        return [c for c in self.cameras.values() if ((c.longitude-lng)**2+(c.latitude-lat)**2)**0.5 <= max_distance]

    def to_geojson(self):
        features = []
        for road in self.road_segments.values():
            features.append({"type":"Feature","geometry":{"type":"LineString","coordinates":road.geometry},"properties":{"roadId":road.road_id,"name":road.name,"lanes":road.lanes,"capacity":road.capacity,"freeFlowSpeed":road.free_flow_speed,"featureType":"road"}})
        for inter in self.intersections.values():
            features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[inter.longitude,inter.latitude]},"properties":{"intersectionId":inter.intersection_id,"name":inter.name,"signalState":inter.signal_state,"connectedRoadIds":inter.connected_road_ids,"featureType":"intersection"}})
        for cam in self.cameras.values():
            features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[cam.longitude,cam.latitude]},"properties":{"cameraId":cam.camera_id,"name":cam.name,"roadId":cam.road_id,"status":cam.status,"simulated":cam.simulated,"featureType":"camera"}})
        return {"type":"FeatureCollection","features":features}

DEMO_NETWORK = DemoNetwork()
