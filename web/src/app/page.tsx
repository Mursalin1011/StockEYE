import { DateSelect, RunScreenButton } from "@/components/Controls";
import { PickCard } from "@/components/PickCard";
import { AllSignals, WatchList } from "@/components/ScreenLists";
import { Card, Empty, PageTitle, Stat } from "@/components/ui";
import { api, apiOrNull } from "@/lib/api";
import { day, int, num } from "@/lib/format";
import type { Meta, Run, Screen } from "@/lib/types";

export default async function PicksPage(props: PageProps<"/">) {
  const { date } = await props.searchParams;
  const asOf = typeof date === "string" ? date : undefined;
  const [meta, runs, screen] = await Promise.all([
    api<Meta>("/api/meta"),
    api<Run[]>("/api/runs"),
    apiOrNull<Screen>(asOf ? `/api/screens/${asOf}` : "/api/screens/latest"),
  ]);
  const dates = [...new Set(runs.map((r) => r.as_of))].sort().reverse();

  return (
    <>
      <PageTitle
        title="Picks"
        subtitle={screen ? `Screen for ${day(screen.as_of)} · prices stored ${meta.prices_from} → ${meta.prices_to}` : "No saved screens yet"}
      >
        {dates.length > 0 && <DateSelect dates={dates} value={screen?.as_of ?? dates[0]} />}
        <RunScreenButton />
      </PageTitle>

      {!screen ? (
        <Empty>Nothing screened yet. Click “Run screen now”, or wait for the daily 3pm job.</Empty>
      ) : (
        <div className="space-y-6">
          <Card>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Market turnover" value={`৳${num(screen.market.turnover_cr, 0)} cr`} />
              <Stat label="Advances" value={<span className="text-up">▲ {int(screen.market.advances)}</span>} />
              <Stat label="Declines" value={<span className="text-down">▼ {int(screen.market.declines)}</span>} />
              <Stat label="Unchanged" value={`● ${int(screen.market.unchanged)}`} />
            </div>
          </Card>

          {screen.profiles.map((p) => (
            <Card key={p.profile}>
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold capitalize">{p.profile}</h2>
                  <p className="text-sm text-ink-2">{p.description}</p>
                </div>
                <div className="flex gap-6">
                  <Stat label="Pass quality" value={`${p.passed_quality}/${p.universe_size}`} />
                  <Stat label="Signals" value={p.signals} />
                  <Stat label="Shortlist" value={p.picks.length} />
                </div>
              </div>
              {p.picks.length === 0 ? (
                <Empty>No stock meets the bar on this date.</Empty>
              ) : (
                <div className="space-y-3">
                  {p.picks.map((pk) => (
                    <PickCard key={pk.code} pick={pk} profile={p.profile} strategies={meta.strategies} />
                  ))}
                </div>
              )}
              <details className="mt-5 border-t border-line pt-4" open={p.watch.length > 0}>
                <summary className="cursor-pointer text-sm font-medium">
                  Setups to watch ({p.watch.length})
                  <span className="ml-2 font-normal text-muted">not a signal yet: what each needs to trigger, closest first</span>
                </summary>
                <div className="mt-3">
                  <WatchList items={p.watch} profile={p.profile} />
                </div>
              </details>
              <details className="mt-4 border-t border-line pt-4">
                <summary className="cursor-pointer text-sm font-medium">
                  All signals ({p.all_signals.length})
                  <span className="ml-2 font-normal text-muted">every strategy hit, including below the shortlist cut</span>
                </summary>
                <div className="mt-3">
                  <AllSignals signals={p.all_signals} profile={p.profile} />
                </div>
              </details>
            </Card>
          ))}
          <p className="text-xs text-muted">{meta.disclaimer}</p>
        </div>
      )}
    </>
  );
}
