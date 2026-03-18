# Bahamut TICC — Trading Intelligence Control Center

Production-grade admin panel for the Bahamut AI trading system.

## Architecture

```
bahamut-ticc/
├── app/
│   ├── layout.tsx              # Root layout (QueryProvider, ToastProvider)
│   ├── page.tsx                # Redirect → /dashboard
│   ├── globals.css             # Tailwind + custom styles
│   ├── login/page.tsx          # Login page (no auth guard)
│   └── (admin)/               # Route group: all admin pages behind AuthGuard
│       ├── layout.tsx          # Admin shell: Sidebar + AuthGuard + ErrorBoundary
│       ├── dashboard/page.tsx  # System overview with KPIs
│       ├── config/page.tsx     # Config control panel (37+ keys)
│       ├── risk/page.tsx       # Kill switch + risk metrics + simulation
│       ├── audit/page.tsx      # Audit log with filters
│       ├── learning/page.tsx   # AI learned patterns
│       ├── overrides/page.tsx  # Temporary config overrides
│       ├── alerts/page.tsx     # System alerts
│       └── ai-opt/page.tsx     # AI optimization suggestions
│
├── components/
│   ├── ui/                     # Reusable primitives
│   │   ├── Card, Badge, Button, Toggle, Tag, Pulse
│   │   ├── ConfirmModal, Skeleton, EmptyState, ErrorBoundary
│   │   └── index.ts (barrel)
│   ├── charts/                 # SVG chart components
│   │   ├── Sparkline, BarChart, DonutChart, RiskGauge
│   │   └── index.ts (barrel)
│   ├── layout/                 # Shell components
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx
│   ├── dashboard/StatusCard.tsx
│   ├── config/ConfigEditor.tsx + ConfigGroup.tsx
│   ├── risk/KillSwitchPanel.tsx + ScenarioChart.tsx
│   ├── audit/AuditTable.tsx
│   └── overrides/OverrideModal.tsx
│
├── lib/
│   ├── api.ts                  # API service layer (real + mock fallback)
│   ├── hooks.ts                # React Query hooks for all endpoints
│   ├── mock-data.ts            # Mock data (dev mode only)
│   └── utils.ts                # cn(), formatters, env helpers
│
├── types/
│   ├── config.ts               # ConfigMap, ConfigEntry, CATEGORY_META
│   ├── portfolio.ts            # SystemSummary, MarginalRiskData, etc.
│   ├── audit.ts                # AuditLogEntry, AuditFilters
│   └── index.ts                # Barrel export
│
├── store/
│   ├── auth.ts                 # Zustand: user, isAuthed, login/logout
│   └── ui.ts                   # Zustand: toasts, sidebar state
│
├── providers/
│   ├── QueryProvider.tsx        # TanStack React Query client
│   ├── ToastProvider.tsx        # Renders toast notifications from Zustand
│   └── AuthGuard.tsx            # Redirects to /login if not authenticated
│
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── next.config.js
└── .env.local.example
```

## Setup

```bash
# 1. Install dependencies
npm install

# 2. Configure environment
cp .env.local.example .env.local
# Edit .env.local with your Bahamut API URL

# 3. Run dev server
npm run dev
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://bahamut-production.up.railway.app` | Backend API base URL |
| `NEXT_PUBLIC_MOCK_MODE` | `false` | Set `true` for local dev without backend |
| `NEXT_PUBLIC_REFRESH_INTERVAL` | `5000` | Auto-refresh interval in ms |

## Mock Mode

Set `NEXT_PUBLIC_MOCK_MODE=true` to run entirely with mock data.
Login with any non-empty credentials in mock mode.

## API Endpoints Expected

The frontend expects these FastAPI endpoints:

| Method | Path | Used By |
|---|---|---|
| POST | `/auth/login` | Login page |
| GET | `/admin/summary` | Dashboard, Risk |
| GET | `/admin/config` | Config page |
| POST | `/admin/config` | Config save |
| POST | `/admin/config/reset/{key}` | Config reset |
| GET | `/admin/config/overrides` | Overrides page |
| POST | `/admin/config/overrides` | Create override |
| DELETE | `/admin/config/overrides/{key}` | Remove override |
| GET | `/admin/audit-log` | Audit page |
| GET | `/portfolio/marginal-risk` | Dashboard, Risk |
| GET | `/portfolio/kill-switch` | Risk page |
| POST | `/portfolio/kill-switch` | Kill switch toggle |
| GET | `/admin/learning/patterns` | Learning page |
| GET | `/admin/alerts` | Alerts page |
| POST | `/admin/alerts/{id}/dismiss` | Dismiss alert |
| GET | `/admin/ai/optimize` | AI Optimizer |

## Auth

- JWT token stored in `localStorage` as `bah_token`
- Sent as `Authorization: Bearer <token>` on all requests
- 401 responses auto-clear token and redirect to `/login`
- AuthGuard wraps all admin routes in the `(admin)` route group

## Key Design Decisions

- **No inline styles** — all styling via Tailwind + custom theme
- **React Query** for all API state — caching, refetching, mutations
- **Zustand** for UI state (toasts) and auth state only
- **Mock data isolated** in `lib/mock-data.ts`, only used when `MOCK_MODE=true`
- **Error boundaries** wrap all admin content
- **Confirm modals** for dangerous operations (kill switch, overrides)
- **Loading skeletons** on every data-dependent page
- **Empty states** for zero-data scenarios
