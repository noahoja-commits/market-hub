import Papa from "papaparse";
import { unstable_cache } from "next/cache";
import { cache } from "react";

const ONE_WEEK = 60 * 60 * 24 * 7;

const ZHVI_URL =
  "https://files.zillowstatic.com/research/public_csvs/zhvi/County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv";
const ZORI_URL =
  "https://files.zillowstatic.com/research/public_csvs/zori/County_zori_uc_sfrcondomfr_sm_month.csv";

export type Point = { date: string; value: number };

export type CountySeries = {
  regionName: string;
  state: string;
  series: Point[];
};

async function fetchCsv(url: string): Promise<string> {
  const res = await fetch(url, {
    headers: { "User-Agent": "market-hub/0.1" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Zillow fetch failed ${res.status} for ${url}`);
  return res.text();
}

function parseCountyCsv(
  csv: string,
  filter: { state: string; regionNames: string[] },
): CountySeries[] {
  const parsed = Papa.parse<Record<string, string>>(csv, {
    header: true,
    skipEmptyLines: true,
  });
  if (parsed.errors.length) {
    console.warn("zillow csv parse warnings", parsed.errors.slice(0, 3));
  }
  const rows = parsed.data.filter(
    (r) =>
      r.StateName === filter.state &&
      filter.regionNames.includes(r.RegionName ?? ""),
  );
  return rows.map((row) => {
    const series: Point[] = [];
    for (const [key, val] of Object.entries(row)) {
      if (/^\d{4}-\d{2}-\d{2}$/.test(key)) {
        const n = Number(val);
        if (Number.isFinite(n)) series.push({ date: key, value: n });
      }
    }
    series.sort((a, b) => a.date.localeCompare(b.date));
    return {
      regionName: row.RegionName!,
      state: row.StateName!,
      series,
    };
  });
}

const _getZhvi = unstable_cache(
  async (state: string, regionNames: string[]): Promise<CountySeries[]> => {
    const csv = await fetchCsv(ZHVI_URL);
    return parseCountyCsv(csv, { state, regionNames });
  },
  ["zillow-zhvi"],
  { revalidate: ONE_WEEK, tags: ["zillow", "zillow-zhvi"] },
);

const _getZori = unstable_cache(
  async (state: string, regionNames: string[]): Promise<CountySeries[]> => {
    const csv = await fetchCsv(ZORI_URL);
    return parseCountyCsv(csv, { state, regionNames });
  },
  ["zillow-zori"],
  { revalidate: ONE_WEEK, tags: ["zillow", "zillow-zori"] },
);

export const getZhvi = cache(_getZhvi);
export const getZori = cache(_getZori);

export function latest(series: Point[]): Point | null {
  return series.length ? series[series.length - 1] : null;
}

export function pctChange(series: Point[], monthsBack: number): number | null {
  if (series.length < monthsBack + 1) return null;
  const current = series[series.length - 1].value;
  const prior = series[series.length - 1 - monthsBack].value;
  if (!prior) return null;
  return ((current - prior) / prior) * 100;
}

export function tailSeries(series: Point[], months: number): Point[] {
  return series.slice(-months);
}
