import type { StyleSpecification } from 'maplibre-gl';

const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env;
export const OPENFREEMAP_POSITRON_STYLE = 'https://tiles.openfreemap.org/styles/positron';

// OpenFreeMap is a public local/demo visualization provider, not a production tile SLA.
export function mapStyle(): string | StyleSpecification {
  return env.VITE_MAP_STYLE_URL?.trim() || OPENFREEMAP_POSITRON_STYLE;
}

export function fallbackMapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors' } },
    layers: [{ id: 'public-basemap', type: 'raster', source: 'osm' }],
  };
}
