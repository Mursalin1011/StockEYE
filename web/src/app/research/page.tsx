import Link from "next/link";
import { AddLinkForm, ImportInboxButton, RunReviewButton } from "@/components/ResearchControls";
import { Table, Td, Th } from "@/components/Table";
import { Badge, Card, Empty, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { pct, signClass } from "@/lib/format";
import type { ResearchOverview, ReviewDetail, Stance, StockCall } from "@/lib/types";

export const metadata = { title: "Research" };

const DOC_TYPES = ["newsflash", "market_review", "macro", "company", "sector", "other"];
const STANCE_TONE: Record<Stance, "good" | "bad" | "neutral"> = { bullish: "good", bearish: "bad", neutral: "neutral" };
const IMPACT_TONE = { positive: "good", negative: "bad", mixed: "neutral", neutral: "neutral" } as const;

function StanceBadge({ stance, confidence, horizon }: { stance: Stance; confidence?: number; horizon?: number }) {
  return (
    <Badge tone={STANCE_TONE[stance]}>
      {stance}
      {horizon ? ` · ${horizon}d` : ""}
      {confidence !== undefined ? ` · ${confidence.toFixed(0)}%` : ""}
    </Badge>
  );
}

function CallRow({ c, score }: { c: StockCall; score?: ReviewDetail["scores"][number] }) {
  return (
    <tr className="align-top">
      <Td className="font-medium">
        <Link className="underline" href={`/casestudy?${new URLSearchParams({ code: c.code })}`}>{c.code}</Link>
        <div className="max-w-40 truncate text-xs font-normal text-muted" title={c.company}>{c.company}</div>
      </Td>
      <Td><StanceBadge stance={c.stance} horizon={c.horizon_days} confidence={c.confidence} /></Td>
      <Td className="!whitespace-normal min-w-72">
        <div>{c.thesis}</div>
        <details className="mt-1 text-xs text-ink-2">
          <summary className="cursor-pointer text-muted">Evidence ({c.evidence.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {c.evidence.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </details>
      </Td>
      <Td className="!whitespace-normal min-w-48 text-ink-2">{c.invalidation}</Td>
      <Td className="!whitespace-normal min-w-40">
        <span className={c.stockeye_view === "agrees" ? "text-up" : c.stockeye_view === "disagrees" ? "text-down" : "text-muted"}>
          {c.stockeye_view}
        </span>
        {c.stockeye_note && <div className="text-xs text-ink-2">{c.stockeye_note}</div>}
      </Td>
      <Td>{c.priced_in}</Td>
      <Td right>
        {score?.excess != null ? (
          <span title={`Return ${pct(score.ret)} vs basket ${pct(score.bench)}`}>
            <span className={signClass(score.excess)}>{pct(score.excess)}</span> {score.correct ? "✓" : "✗"}
          </span>
        ) : c.stance === "neutral" ? (
          <span className="text-muted">not scored</span>
        ) : (
          <span className="text-muted">open</span>
        )}
      </Td>
    </tr>
  );
}

async function ReviewView({ id }: { id: number }) {
  const d = await api<ReviewDetail>(`/api/research/reviews/${id}`);
  const r = d.review;
  const mv = r.market_view;
  const scores = new Map(d.scores.map((s) => [`${s.code}-${s.stance}-${s.horizon_days}`, s]));
  return (
    <div className="space-y-4">
      <Card>
        <div className="text-xs text-muted">
          Review #{d.id} · {d.created_at.replace("T", " ").slice(0, 16)} UTC · StockEYE data to {d.as_of} · {d.model}
        </div>
        <h2 className="mt-1 text-lg font-semibold">{r.headline}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">Market</span>
          <StanceBadge stance={mv.stance} horizon={mv.horizon_days} confidence={mv.confidence} />
        </div>
        <p className="mt-2 text-sm">{mv.summary}</p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2 text-sm">
          <div>
            <div className="text-xs font-medium text-muted">Drivers</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">{mv.drivers.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>
          <div>
            <div className="text-xs font-medium text-muted">Risks</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">{mv.risks.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>
        </div>
      </Card>

      <Card>
        <h2 className="mb-2 font-semibold">Stock calls</h2>
        {r.calls.length === 0 ? (
          <Empty>No stock calls in this review: nothing in the documents justified one.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Stock</Th><Th>Outlook</Th><Th>Thesis</Th><Th>Wrong if</Th><Th>StockEYE</Th>
                <Th title="Has the price already moved on this news?">Priced in</Th>
                <Th right title="Return vs the quality basket once the horizon has passed (python -m dse_screener research score)">Result</Th>
              </tr>
            </thead>
            <tbody>
              {r.calls.map((c) => <CallRow key={`${c.code}-${c.stance}`} c={c} score={scores.get(`${c.code}-${c.stance}-${c.horizon_days}`)} />)}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 font-semibold">Macro and news</h2>
          <ul className="space-y-3 text-sm">
            {r.macro.map((m, i) => (
              <li key={i}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{m.topic}</span>
                  <Badge tone={IMPACT_TONE[m.impact]}>{m.impact}</Badge>
                  {m.sectors.length > 0 && <span className="text-xs text-muted">{m.sectors.join(", ")}</span>}
                </div>
                <p className="mt-0.5 text-ink-2">{m.summary}</p>
                <p className="text-xs text-muted">{m.source}</p>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Sectors</h2>
          <ul className="space-y-2 text-sm">
            {r.sectors.map((s, i) => (
              <li key={i}>
                <span className="font-medium">{s.sector}</span> <StanceBadge stance={s.stance} confidence={s.confidence} />
                <p className="text-ink-2">{s.rationale}</p>
              </li>
            ))}
          </ul>
          {r.watch.length > 0 && (
            <>
              <h2 className="mt-5 mb-2 font-semibold">Watch</h2>
              <ul className="space-y-1 text-sm">
                {r.watch.map((w, i) => <li key={i}><b>{w.code}</b> <span className="text-ink-2">{w.what_to_watch}</span></li>)}
              </ul>
            </>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 font-semibold">Not market-moving</h2>
          <ul className="list-disc space-y-0.5 pl-4 text-sm text-ink-2">{r.noise.map((x, i) => <li key={i}>{x}</li>)}</ul>
          {r.data_gaps.length > 0 && (
            <>
              <h2 className="mt-4 mb-2 font-semibold">Data gaps</h2>
              <ul className="list-disc space-y-0.5 pl-4 text-sm text-ink-2">{r.data_gaps.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </>
          )}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Documents read</h2>
          <ul className="space-y-2 text-sm">
            {r.sources_used.map((s, i) => (
              <li key={i}>
                <div className="font-medium">{s.document}</div>
                <ul className="list-disc pl-4 text-ink-2">{s.key_points.map((k, j) => <li key={j}>{k}</li>)}</ul>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            {d.docs.map((x) => `#${x.id} ${x.source ?? x.filename} (${x.published})`).join(" · ")}
            {d.usage && ` · tokens in ${d.usage.input_tokens}, out ${d.usage.output_tokens}`}
          </p>
        </Card>
      </div>
    </div>
  );
}

export default async function ResearchPage(props: PageProps<"/research">) {
  const sp = await props.searchParams;
  const o = await api<ResearchOverview>("/api/research");
  const reviewId = typeof sp.review === "string" ? Number(sp.review) : o.reviews[0]?.id;
  const unreviewed = o.docs.filter((d) => !d.reviewed).length;
  const tr = o.track_record;

  return (
    <>
      <PageTitle title="Research" subtitle="Broker PDFs read by the AI analyst, checked against StockEYE's data.">
        <RunReviewButton disabled={!o.has_api_key || unreviewed === 0} runningJob={o.running[0]?.id} />
      </PageTitle>

      {!o.has_api_key && (
        <Card className="mb-4">
          <p className="text-sm">
            <b>No Anthropic API key yet.</b> Create one at platform.claude.com, then add it to <code>config/secrets.yaml</code>:{" "}
            <code>anthropic: {"{"} api_key: … {"}"}</code> and restart the API. Documents can be added already.
          </p>
        </Card>
      )}

      {reviewId ? <ReviewView id={reviewId} /> : <Empty>No AI reviews yet. Add documents, then press “Run AI review”.</Empty>}

      <Card className="mt-4">
        <h2 className="mb-2 font-semibold">Add documents</h2>
        <AddLinkForm types={DOC_TYPES} />
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          Or drop PDFs into <code>{o.inbox}</code> and <ImportInboxButton />. Publishers and report types are recognised by{" "}
          <code>{o.sources}</code>; the analyst follows <code>{o.guide}</code> (edit it to change how it judges).
        </p>
      </Card>

      <Card className="mt-4">
        <h2 className="mb-2 font-semibold">Documents ({unreviewed} not yet reviewed)</h2>
        {o.docs.length === 0 ? (
          <Empty>No documents yet.</Empty>
        ) : (
          <Table>
            <thead>
              <tr><Th>#</Th><Th>Published</Th><Th>Type</Th><Th>Source</Th><Th right>Pages</Th><Th>Stocks mentioned</Th><Th /></tr>
            </thead>
            <tbody>
              {o.docs.map((d) => (
                <tr key={d.id}>
                  <Td>{d.id}</Td>
                  <Td>{d.published}</Td>
                  <Td>{d.doc_type.replace("_", " ")}</Td>
                  <Td>
                    {d.url ? <a className="underline" href={d.url} target="_blank" rel="noreferrer">{d.source ?? d.filename}</a> : d.source ?? d.filename}
                  </Td>
                  <Td right>{d.pages}</Td>
                  <Td className="!whitespace-normal text-xs text-ink-2">
                    {d.codes.length} {d.codes.length > 0 && `· ${d.codes.slice(0, 8).join(", ")}${d.codes.length > 8 ? "…" : ""}`}
                  </Td>
                  <Td>{d.reviewed ? <Badge>reviewed</Badge> : <Badge tone="good">new</Badge>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 font-semibold">Track record</h2>
          <p className="mb-2 text-sm text-ink-2">
            {tr.calls_made} calls made, {tr.calls_scored} scored
            {tr.hit_rate_pct !== undefined && <> · hit rate <b>{pct(tr.hit_rate_pct, 0, false)}</b> · average {pct(tr.avg_excess_vs_basket_pct)} vs basket</>}.
            A call is right if the stock beats (bullish) or lags (bearish) the quality basket over its horizon.
          </p>
          <Table>
            <thead>
              <tr><Th>Confidence</Th><Th right>Calls</Th><Th right title="Average stated confidence">Expected</Th><Th right>Actual hit rate</Th><Th right>Avg vs basket</Th></tr>
            </thead>
            <tbody>
              {o.calibration.map((c) => (
                <tr key={c.confidence}>
                  <Td>{c.confidence}%</Td><Td right>{c.calls}</Td><Td right>{pct(c.expected_hit_pct, 0, false)}</Td>
                  <Td right>{pct(c.actual_hit_pct, 0, false)}</Td><Td right className={signClass(c.avg_excess_pct)}>{pct(c.avg_excess_pct)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Past reviews</h2>
          {o.reviews.length === 0 ? (
            <Empty>None yet.</Empty>
          ) : (
            <ul className="space-y-2 text-sm">
              {o.reviews.map((r) => (
                <li key={r.id} className={r.id === reviewId ? "font-medium" : ""}>
                  <Link className="underline" href={`/research?review=${r.id}`}>#{r.id} · {r.as_of}</Link>{" "}
                  <span className="text-ink-2">{r.headline}</span> <span className="text-xs text-muted">({r.calls} calls)</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <p className="mt-4 text-xs text-muted">
        AI views are probabilistic research, not investment advice. Broker reports stay on this PC; they are sent only to the Claude API for the review.
      </p>
    </>
  );
}
