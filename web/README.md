# StockEYE web dashboard

Next.js 16 (App Router) + Tailwind 4 + TradingView Lightweight Charts. It reads everything from the
Python API (`python -m dse_screener api`, 127.0.0.1:8000): server components fetch it directly, and
browser calls to `/api/*` are proxied by `next.config.ts`.

```powershell
npm install
npm run dev        # http://127.0.0.1:3000 (this PC only)
npm run typecheck
npm run lint
```

- `src/lib/api.ts`: server-side API client; `src/lib/types.ts`: response shapes.
- `src/components/StockChart.tsx`: price, volume, RSI and MACD panes on one date axis.
- Theme tokens (light/dark) live in `src/app/globals.css`.

Set `API_URL` to point at a different API host.
