# KcpInsights — frontend

Next.js 16 (App Router), React 19, Tailwind 4, shadcn/ui primitives, Recharts, Zod and React Hook Form.

```bash
npm install
npm run dev        # http://localhost:3000, proxies /api/* to KCP_API_URL (default http://127.0.0.1:8000)
npm test           # vitest
npm run lint       # eslint
npm run typecheck  # tsc --noEmit
```

Business logic lives in the FastAPI backend; components only render API responses. See the
repository [README](../README.md) for the full setup.
