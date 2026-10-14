# isbree-portal

See [docs/isbree-web.md](../../docs/isbree-web.md) (architecture, security, configuration, tests).

```bash
cp .env.example .env.local   # then fill the secrets
npm install
npm run dev                  # http://localhost:3001
npm run typecheck && npm run lint && npm test
npm run test:e2e             # needs the Django backend (docker compose) and the demo data
npm run build
```
