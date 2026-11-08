"use client";

import { useEffect, useRef } from "react";
import "leaflet/dist/leaflet.css";
import type { MapPin } from "@/lib/map-model";
import type { Verdict } from "@/lib/types";

type SidoFeature = {
  type: "Feature";
  properties: { id: string; name: string };
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
};

type SidoCollection = { type: "FeatureCollection"; features: SidoFeature[] };

const PIN: Record<Verdict, { fill: string; label: string; shape: "circle" | "square" | "diamond" }> = {
  해당: { fill: "#059669", label: "해당", shape: "circle" },
  비해당: { fill: "#e11d48", label: "비해당", shape: "square" },
  확인필요: { fill: "#ea580c", label: "확인필요", shape: "diamond" },
};

function pinHtml(v: Verdict): string {
  const s = PIN[v];
  if (s.shape === "square") {
    return `<span class="nc-pin-mark" style="width:16px;height:16px;background:${s.fill};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)"></span>`;
  }
  if (s.shape === "diamond") {
    return `<span class="nc-pin-mark" style="width:14px;height:14px;background:${s.fill};border:2px solid #fff;transform:rotate(45deg);box-shadow:0 1px 4px rgba(0,0,0,.35)"></span>`;
  }
  return `<span class="nc-pin-mark" style="width:16px;height:16px;background:${s.fill};border:2px solid #fff;border-radius:999px;box-shadow:0 1px 4px rgba(0,0,0,.35)"></span>`;
}

function leafletNs(mod: typeof import("leaflet") | { default: typeof import("leaflet") }): typeof import("leaflet") {
  const m = mod as { default?: typeof import("leaflet"); map?: unknown };
  if (typeof m.map === "function") return m as typeof import("leaflet");
  return m.default as typeof import("leaflet");
}

export function LeafletKoreaMap({ coloredIds, pins }: { coloredIds: string[]; pins: MapPin[] }) {
  const hostRef = useRef<HTMLDivElement>(null);

  const dataKey = `${coloredIds.join("|")}|${pins.map((p) => `${p.id}:${p.overall}:${p.lat}:${p.lng}`).join("|")}`;

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    let cancelled = false;
    let map: import("leaflet").Map | undefined;
    let ro: ResizeObserver | undefined;

    void (async () => {
      const [leafletMod, geo] = await Promise.all([
        import("leaflet"),
        fetch("/korea-sido.geo.json").then((r) => r.json() as Promise<SidoCollection>),
      ]);
      if (cancelled || !hostRef.current) return;
      const L = leafletNs(leafletMod);

      map = L.map(hostRef.current, {
        center: [36.35, 127.4],
        zoom: 7,
        minZoom: 6,
        maxZoom: 18,
        scrollWheelZoom: true,
        attributionControl: true,
      });

      const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      });
      const carto = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
        maxZoom: 20,
        subdomains: "abcd",
      });
      osm.addTo(map);
      osm.on("tileerror", () => {
        if (map && !map.hasLayer(carto)) {
          map.removeLayer(osm);
          carto.addTo(map);
        }
      });

      L.geoJSON(geo, {
        style: (feat) => {
          const id = (feat?.properties as { id?: string } | undefined)?.id;
          const on = Boolean(id && coloredIds.includes(id));
          return {
            color: on ? "#123a63" : "#64748b",
            weight: on ? 2 : 1,
            fillColor: on ? "#2563eb" : "#94a3b8",
            fillOpacity: on ? 0.42 : 0.22,
          };
        },
        onEachFeature: (feat, layer) => {
          const props = feat.properties as { id: string; name: string };
          const on = coloredIds.includes(props.id);
          layer.bindTooltip(`${props.name}${on ? " · 공고 있음" : " · 공고 없음"}`, { sticky: true });
        },
      }).addTo(map);

      for (const pin of pins) {
        const icon = L.divIcon({
          className: "nc-pin",
          html: pinHtml(pin.overall),
          iconSize: [20, 20],
          iconAnchor: [10, 10],
        });
        L.marker([pin.lat, pin.lng], { icon, zIndexOffset: 500 })
          .bindPopup(
            `<p style="margin:0;font-weight:600">${pin.address}</p><p style="margin:6px 0 0;font-size:12px">${PIN[pin.overall].label} · ${pin.noticeName}${pin.sample ? " · 샘플" : ""}</p>`,
          )
          .addTo(map);
      }

      if (pins.length) {
        const bounds = L.latLngBounds(pins.map((p) => [p.lat, p.lng] as [number, number]));
        map.fitBounds(bounds.pad(0.55), { maxZoom: 14, animate: false });
      } else {
        map.setView([36.5, 127.8], 7);
      }

      const invalidate = () => map?.invalidateSize();
      requestAnimationFrame(invalidate);
      window.setTimeout(invalidate, 120);
      ro = new ResizeObserver(invalidate);
      ro.observe(hostRef.current);
    })();

    return () => {
      cancelled = true;
      ro?.disconnect();
      map?.remove();
    };
    // Recreate the map when overlay data changes (tab stays mounted while open).
    // eslint-disable-next-line react-hooks/exhaustive-deps -- dataKey encodes coloredIds and pins
  }, [dataKey]);

  return (
    <div
      ref={hostRef}
      className="h-[36rem] w-full"
      style={{ height: "36rem", width: "100%" }}
      role="application"
      aria-label="대한민국 시·도 현황 지도"
    />
  );
}
