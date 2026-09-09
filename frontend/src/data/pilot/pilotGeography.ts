// Read-only G1 projection for visualization. Never used by business location resolution.
export const pilotGeography = {
  "type": "FeatureCollection",
  "metadata": {
    "regionId": "QT_BY_XIASHA_PILOT_001",
    "purpose": "visualization_only",
    "canonicalSource": "backend/data/pilot_regions/qt_by_xiasha_pilot_001/intersections.json",
    "source": {
      "sourceId": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
      "title": "OpenStreetMap / Overpass sampled road and intersection geometry for Baiyang-Xiasha pilot",
      "organization": "OpenStreetMap contributors",
      "sourceTier": "C",
      "sourceUrl": "https://overpass.openstreetmap.fr/api/interpreter",
      "retrievedAt": "2026-09-01",
      "dataTypes": [
        "road",
        "intersection",
        "road_relation",
        "coordinate"
      ],
      "licenseNote": "OpenStreetMap data is made available under ODbL. This pack stores a small pilot inventory with attribution and does not claim official GIS topology.",
      "coordinateSystem": "WGS84",
      "usage": "auxiliary_open_geospatial",
      "verificationNotes": "Overpass queries verified sampled named roads and shared road nodes for selected intersections. OSM way/node IDs are retained only in metadata/provenance, not as canonical business IDs.",
      "sampleQueries": [
        "[out:json][timeout:15];way[\"name\"=\"文泽路\"](30.300,120.330,30.330,120.360)->.a;way[\"name\"=\"2号大街\"](30.300,120.330,30.330,120.390)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"文海南路\"](30.300,120.360,30.330,120.395)->.a;way[\"name\"=\"2号大街\"](30.300,120.330,30.330,120.395)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"高沙路\"](30.300,120.320,30.330,120.340)->.a;way[\"name\"=\"金沙大道\"](30.300,120.300,30.330,120.350)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"文泽路\"](30.300,120.330,30.330,120.360)->.a;way[\"name\"=\"学林街\"](30.305,120.320,30.335,120.390)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"高沙路\"](30.300,120.320,30.330,120.340)->.a;way[\"name\"=\"学林街\"](30.305,120.320,30.335,120.390)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"文泽路\"](30.300,120.330,30.330,120.360)->.a;way[\"name\"=\"学源街\"](30.305,120.330,30.330,120.390)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"文海南路\"](30.300,120.360,30.330,120.395)->.a;way[\"name\"=\"学源街\"](30.305,120.330,30.330,120.395)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"文海南路\"](30.300,120.360,30.330,120.395)->.a;way[\"name\"=\"学林街\"](30.305,120.320,30.335,120.390)->.b;node(w.a)(w.b);out;",
        "[out:json][timeout:15];way[\"name\"=\"学正街\"](30.300,120.340,30.320,120.395)->.a;way[\"name\"=\"23号大街\"](30.300,120.340,30.320,120.395)->.b;node(w.a)(w.b);out;"
      ]
    },
    "license": "ODbL-1.0",
    "attribution": "© OpenStreetMap contributors",
    "attributionUrl": "https://www.openstreetmap.org/copyright",
    "projectedAt": "2026-09-07",
    "notOfficialGIS": true
  },
  "features": [
    {
      "type": "Feature",
      "id": "QT_BY_INT_WENZE_NO2",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3438782,
          30.3123153
        ]
      },
      "properties": {
        "name": "文泽路 × 2号大街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "1971533183"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road node; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_WENHAINAN_NO2",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.371803,
          30.3133116
        ]
      },
      "properties": {
        "name": "文海南路 × 2号大街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "661332723",
          "3923155997"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road nodes averaged for pilot display only; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_GAOSHA_JINSHA",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3307635,
          30.3117499
        ]
      },
      "properties": {
        "name": "高沙路 × 金沙大道",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "5181146440",
          "5181146441"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road nodes averaged for pilot display only; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_WENZE_XUELIN",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3438557,
          30.3181135
        ]
      },
      "properties": {
        "name": "文泽路 × 学林街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "1971533265"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road node tagged traffic_signals; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_GAOSHA_XUELIN",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3304192,
          30.31789
        ]
      },
      "properties": {
        "name": "高沙路 × 学林街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "1971533225"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road node; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_WENZE_XUEYUAN",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3438708,
          30.3209437
        ]
      },
      "properties": {
        "name": "文泽路 × 学源街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "1971533186",
          "11097054943"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road nodes averaged for pilot display only; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_WENHAINAN_XUEYUAN",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3747332,
          30.3209106
        ]
      },
      "properties": {
        "name": "文海南路 × 学源街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "661332728",
          "3923156000"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road nodes averaged for pilot display only; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_WENHAINAN_XUELIN",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3730775,
          30.3165954
        ]
      },
      "properties": {
        "name": "文海南路 × 学林街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS",
        "osmNodeIds": [
          "1971533162",
          "3923155999"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road nodes averaged for pilot display only; not official intersection inventory."
      }
    },
    {
      "type": "Feature",
      "id": "QT_BY_INT_XUEZHENG_NO23",
      "geometry": {
        "type": "Point",
        "coordinates": [
          120.3717612,
          30.3089294
        ]
      },
      "properties": {
        "name": "学正街 × 23号大街",
        "regionId": "QT_BY_XIASHA_PILOT_001",
        "verificationStatus": "verified",
        "sourceType": "open_geo",
        "verifiedAt": "2026-09-01T00:00:00Z",
        "sourceReference": "SRC_OSM_OVERPASS_QT_BY_ROADS_INTERSECTIONS,SRC_ZJTIE_HOME",
        "osmNodeIds": [
          "661332716",
          "3923155982"
        ],
        "coordinateSystem": "WGS84",
        "sourceBoundary": "Shared OSM road nodes averaged for pilot display only; not official intersection inventory."
      }
    }
  ]
};
