import type { StyleSpecification } from 'maplibre-gl';

const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env;
// OSM Standard is a local demo basemap, not a production tile SLA. No prefetch/offline downloads.
export function mapStyle(): string | StyleSpecification {
  return env.VITE_MAP_STYLE_URL?.trim() || {
    version: 8,
    sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors' } },
    layers: [{ id: 'public-basemap', type: 'raster', source: 'osm' }],
  };
}
