# Mira console

React + Vite UI for the agent. See the [root README](../README.md) for setup.

```bash
pnpm dev     # http://localhost:5173, proxies /api to the FastAPI server on :8000
pnpm build   # type-check and build
pnpm lint
```

- `src/App.tsx`: conversation loading and the SSE event loop
- `src/api.ts`: REST calls and a small SSE reader (EventSource can't POST)
- `src/components/`: Header, ChatPanel, StatePanel, TracePanel
