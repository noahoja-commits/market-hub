import { Suspense } from "react";
import { TAMPA_BAY } from "@/lib/markets";
import {
  getZhvi,
  getZori,
  latest,
  pctChange,
  tailSeries,
  type CountySeries,
} from "@/lib/sources/zillow";
import {
  getMortgage30,
  getTampaHomePriceIndex,
  getTampaUnemployment,
} from "@/lib/sources/fred";
import { money, monthLabel, pct } from "@/lib/format";
import { MetricCard } from "@/components/MetricCard";
import { Sparkline } from "@/components/Sparkline";
import { LineChart } from "@/components/LineChart";

export const revalidate = 3600;

export const metadata = {
  title: "Tampa Bay Market Hub",
  description: "Tampa Bay real estate market data — values, rents, rates",
};

export default function HomePage() {
  return (
    <main className="min-h-screen bg-black text-zinc-100">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <header className="mb-8">
          <h1 className="text-3xl font-semibold tracking-tight">
            Tampa Bay Market Hub
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Hillsborough · Pinellas · Pasco · Hernando
          </p>
        </header>

        <Suspense fallback={<DashboardSkeleton />}>
          <Dashboard />
        </Suspense>
      </div>
    </main>
  );
}

async function Dashboard() {
  const regionNames = TAMPA_BAY.counties.map((c) => c.zillowRegionName);
  const [zhvi, zori, mortgage, hpi, unemp] = await Promise.all([
    getZhvi(TAMPA_BAY.state, regionNames),
    getZori(TAMPA_BAY.state, regionNames),
    getMortgage30(),
    getTampaHomePriceIndex(),
    getTampaUnemployment(),
  ]);

  const lastMortgage = mortgage.at(-1);
  const priorMortgage = mortgage.length > 4 ? mortgage[mortgage.length - 5] : null;
  const mortgageDeltaBps =
    lastMortgage && priorMortgage
      ? (lastMortgage.value - priorMortgage.value) * 100
      : null;

  const lastHpi = hpi.at(-1);
  const yearAgoHpi = hpi.length >= 5 ? hpi[hpi.length - 5] : null;
  const hpiYoy =
    lastHpi && yearAgoHpi ? ((lastHpi.value - yearAgoHpi.value) / yearAgoHpi.value) * 100 : null;

  const lastUnemp = unemp.at(-1);

  const metroValueAvg = avgLatest(zhvi);
  const metroValueYoY = avgPctChange(zhvi, 12);
  const metroRentAvg = avgLatest(zori);
  const metroRentYoY = avgPctChange(zori, 12);
  const rentYield =
    metroValueAvg && metroRentAvg
      ? ((metroRentAvg * 12) / metroValueAvg) * 100
      : null;

  const updatedAt = latest(zhvi[0]?.series ?? [])?.date;

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-zinc-500">
          Metro snapshot
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <MetricCard
            label="Median home value"
            value={money(metroValueAvg)}
            delta={
              metroValueYoY != null
                ? { value: `${pct(metroValueYoY)} YoY`, positive: metroValueYoY > 0 }
                : undefined
            }
            sublabel={updatedAt ? `as of ${monthLabel(updatedAt)}` : undefined}
          />
          <MetricCard
            label="Median rent"
            value={money(metroRentAvg)}
            delta={
              metroRentYoY != null
                ? { value: `${pct(metroRentYoY)} YoY`, positive: metroRentYoY > 0 }
                : undefined
            }
            sublabel="Zillow ZORI · per month"
          />
          <MetricCard
            label="Gross rent yield"
            value={rentYield != null ? `${rentYield.toFixed(2)}%` : "—"}
            sublabel="annual rent / value"
          />
          <MetricCard
            label="30-yr mortgage"
            value={lastMortgage ? `${lastMortgage.value.toFixed(2)}%` : "—"}
            delta={
              mortgageDeltaBps != null
                ? {
                    value: `${mortgageDeltaBps > 0 ? "+" : ""}${mortgageDeltaBps.toFixed(0)} bps 4w`,
                    positive: mortgageDeltaBps < 0,
                  }
                : undefined
            }
            sublabel={
              lastMortgage
                ? `week of ${new Date(lastMortgage.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
                : undefined
            }
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-zinc-500">
          By county
        </h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {TAMPA_BAY.counties.map((c) => {
            const zhviRow = zhvi.find((r) => r.regionName === c.zillowRegionName);
            const zoriRow = zori.find((r) => r.regionName === c.zillowRegionName);
            const v = zhviRow ? latest(zhviRow.series)?.value ?? null : null;
            const r = zoriRow ? latest(zoriRow.series)?.value ?? null : null;
            const vYoy = zhviRow ? pctChange(zhviRow.series, 12) : null;
            const rYoy = zoriRow ? pctChange(zoriRow.series, 12) : null;
            const spark = zhviRow ? tailSeries(zhviRow.series, 60) : [];
            return (
              <div
                key={c.fips}
                className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
              >
                <div className="flex items-baseline justify-between">
                  <div className="text-lg font-medium text-zinc-50">{c.name}</div>
                  <div className="text-xs text-zinc-500">{c.state}</div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <div className="text-xs text-zinc-500">Value</div>
                    <div className="text-zinc-100 tabular-nums">{money(v)}</div>
                    <div
                      className={`text-xs tabular-nums ${
                        vYoy == null
                          ? "text-zinc-500"
                          : vYoy > 0
                          ? "text-emerald-500"
                          : "text-rose-500"
                      }`}
                    >
                      {vYoy != null ? `${pct(vYoy)} YoY` : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-500">Rent</div>
                    <div className="text-zinc-100 tabular-nums">{money(r)}</div>
                    <div
                      className={`text-xs tabular-nums ${
                        rYoy == null
                          ? "text-zinc-500"
                          : rYoy > 0
                          ? "text-emerald-500"
                          : "text-rose-500"
                      }`}
                    >
                      {rYoy != null ? `${pct(rYoy)} YoY` : "—"}
                    </div>
                  </div>
                </div>
                <div className="mt-3">
                  <Sparkline data={spark} color="#0ea5e9" format="currency" />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="text-sm font-medium text-zinc-200">
              Tampa MSA home price index
            </h3>
            <div className="text-xs text-zinc-500">
              FRED · ATNHPIUS45300Q · quarterly
              {hpiYoy != null && (
                <span
                  className={`ml-2 ${hpiYoy > 0 ? "text-emerald-500" : "text-rose-500"}`}
                >
                  {pct(hpiYoy)} YoY
                </span>
              )}
            </div>
          </div>
          <LineChart data={hpi.slice(-40)} color="#0ea5e9" format="decimal1" />
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="text-sm font-medium text-zinc-200">
              Tampa MSA unemployment
            </h3>
            <div className="text-xs text-zinc-500">
              FRED · TAMP312URN · monthly
              {lastUnemp && (
                <span className="ml-2 text-zinc-300">
                  {lastUnemp.value.toFixed(1)}%
                </span>
              )}
            </div>
          </div>
          <LineChart data={unemp.slice(-60)} color="#f59e0b" format="percent" />
        </div>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-medium text-zinc-200">
            30-yr fixed mortgage rate (US)
          </h3>
          <div className="text-xs text-zinc-500">FRED · MORTGAGE30US · weekly</div>
        </div>
        <LineChart data={mortgage.slice(-260)} color="#a855f7" format="percent" />
      </section>

      <footer className="border-t border-zinc-900 pt-4 text-xs text-zinc-500">
        Data: Zillow Research (ZHVI, ZORI) · FRED (Federal Reserve Bank of St.
        Louis). Refreshed weekly.
      </footer>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-xl border border-zinc-800 bg-zinc-950"
          />
        ))}
      </div>
      <div className="text-sm text-zinc-500">
        Loading market data (~5–10s on first request)...
      </div>
    </div>
  );
}

function avgLatest(rows: CountySeries[]): number | null {
  const vals = rows
    .map((r) => latest(r.series)?.value)
    .filter((v): v is number => v != null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function avgPctChange(rows: CountySeries[], monthsBack: number): number | null {
  const vals = rows
    .map((r) => pctChange(r.series, monthsBack))
    .filter((v): v is number => v != null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}
