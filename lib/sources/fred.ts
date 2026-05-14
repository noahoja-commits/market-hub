import Papa from "papaparse";
import { unstable_cache } from "next/cache";
import { cache } from "react";

const ONE_DAY = 60 * 60 * 24;

export type FredPoint = { date: string; value: number };

async function fetchSeries(seriesId: string): Promise<FredPoint[]> {
  const url = `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${encodeURIComponent(seriesId)}`;
  const res = await fetch(url, {
    headers: { "User-Agent": "market-hub/0.1" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`FRED fetch failed ${res.status} for ${seriesId}`);
  const csv = await res.text();
  const parsed = Papa.parse<Record<string, string>>(csv, {
    header: true,
    skipEmptyLines: true,
  });
  const points: FredPoint[] = [];
  for (const row of parsed.data) {
    const date = row.observation_date ?? row.DATE ?? "";
    const rawValue = row[seriesId];
    if (!date || rawValue == null) continue;
    if (rawValue === "." || rawValue === "") continue;
    const n = Number(rawValue);
    if (Number.isFinite(n)) points.push({ date, value: n });
  }
  points.sort((a, b) => a.date.localeCompare(b.date));
  return points;
}

function makeCached(seriesId: string, revalidate: number) {
  const cached = unstable_cache(
    () => fetchSeries(seriesId),
    [`fred-${seriesId}`],
    { revalidate, tags: ["fred", `fred:${seriesId}`] },
  );
  return cache(cached);
}

export const getMortgage30 = makeCached("MORTGAGE30US", ONE_DAY);
export const getTampaHomePriceIndex = makeCached("ATNHPIUS45300Q", ONE_DAY * 7);
export const getTampaUnemployment = makeCached("TAMP312URN", ONE_DAY * 7);
