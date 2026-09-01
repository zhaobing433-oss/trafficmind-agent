# 钱塘区白杨-金沙湖-下沙高教园试点区 Context Pack

This directory contains the Phase21 G1 bounded pilot regional context pack for TrafficMind.

Source snapshot date: `2026-09-01`. This date means the TrafficMind project verified the cited public sources on that date; it is not an official update date for any road, school, or planning document.

## Reality Boundary

- Region: real Hangzhou Qiantang District administrative context, represented as an internal bounded pilot region.
- Roads: public-source verified or OpenStreetMap/Overpass open-geo verified road names.
- Intersections: selected shared road-node intersections from OpenStreetMap/Overpass, stored as open-geo approximate coordinates.
- Road relations: deterministic `connects` relations derived from the verified road/intersection geometry.
- POIs: first-party institution sources, bound only to a road when the public source verifies the road address.
- Historical events: not included.
- Case memory: not included.
- Realtime traffic: not included.

## Boundary Membership

The pilot uses an explicit-inventory membership rule. An entity belongs to this pack only if it is listed in the imported JSON files and has source-backed membership in the Baiyang-Xiasha higher-education/Jinsha study area. Stored intersection coordinates must fall inside the approximate study area recorded in `region.json`; that area is for dataset validation only and is not an official administrative boundary.

The road inventory includes first-party-address supported roads, OpenStreetMap/Overpass roads that connect listed pilot intersections, and a small number of open-geo auxiliary road samples inside the approximate study area for first-pass regional coverage. Road relations intentionally cover the verified road-to-intersection graph only; absence from `road_relations.json` does not imply the road is outside the pilot inventory.

## Not Claimed

This pack is not official GIS topology, not a complete Qiantang District road network, not realtime production traffic data, and not a Qiantang District government partnership dataset.

## Imported Files

- `package.json`
- `region.json`
- `roads.json`
- `intersections.json`
- `road_relations.json`
- `pois.json`

## Non-Import Provenance Files

- `source_register.json`
- `README.md`

## Attribution

Open geospatial samples are from OpenStreetMap contributors via Overpass and are subject to ODbL. OSM IDs are retained only as provenance metadata; TrafficMind canonical IDs are manually maintained, deterministic IDs.
