"use client";

export default function ErrorPage({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div className="mx-auto max-w-xl rounded-xl border border-line bg-surface p-6">
      <h1 className="text-lg font-semibold text-down">Something went wrong</h1>
      <p className="mt-2 text-sm text-ink-2">{error.message}</p>
      <p className="mt-2 text-sm text-ink-2">
        Is the API running? Start it with <code className="rounded bg-surface-2 px-1">python -m dse_screener api</code>.
      </p>
      <button className="mt-4 rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-surface-2" onClick={() => retry()}>
        Try again
      </button>
    </div>
  );
}
