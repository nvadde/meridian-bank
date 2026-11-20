meridian-bank/
├── README.md
├── .gitignore
├── .env.example
│
├── frontend/                          # React + Vite + TypeScript
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   ├── client.ts              # fetch wrapper, sends session token
│       │   ├── auth.ts                # login / logout
│       │   ├── accounts.ts            # balances, transactions, transfer
│       │   └── admin.ts               # list users, create user, unlock
│       ├── components/
│       │   ├── LoginForm.tsx
│       │   ├── Dashboard.tsx
│       │   ├── AccountCard.tsx
│       │   ├── TransferForm.tsx
│       │   ├── AuthLab.tsx            # FORBIDDEN / lockout test panel
│       │   └── AdminUsers.tsx         # admin-only Users tab
│       ├── chatbot/
│       │   ├── MiraChat.tsx           # floating widget
│       │   ├── intents.ts             # balance, transactions, transfer, rates, freeze
│       │   └── quickReplies.ts
│       └── pages/
│           ├── HomePage.tsx
│           ├── LoginPage.tsx
│           └── DashboardPage.tsx
│
├── backend/                           # Python FastAPI
│   ├── requirements.txt               # fastapi, uvicorn, oracledb, python-dotenv, passlib
│   ├── main.py                        # app entry, CORS, routers
│   ├── .env                           # NEVER commit — DB_USER, DB_PSW, DSN, WALLET_LOC
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py                  # loads .env
│   │   ├── database.py                # Oracle connection pool
│   │   ├── security.py                # PBKDF2-SHA256, session tokens
│   │   ├── auth.py                    # login, logout, lockout 5 fails / 15 min
│   │   ├── authorization.py           # RBAC: customer / teller / admin checks
│   │   ├── audit.py                   # write to AUDIT_LOGS
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── account.py
│   │   │   └── transaction.py
│   │   ├── routes/
│   │   │   ├── auth_routes.py         # POST /login, /logout
│   │   │   ├── account_routes.py      # GET /accounts, POST /transfer, POST /freeze-card
│   │   │   ├── admin_routes.py        # POST /admin/users, unlock, disable, reset-password
│   │   │   └── chatbot_routes.py      # POST /chat — Mira, signed-in context only
│   │   └── services/
│   │       ├── user_service.py
│   │       ├── account_service.py
│   │       └── chatbot_service.py     # intent router
│   └── tests/
│       ├── test_auth.py               # login, lockout, upgrade hash
│       ├── test_authorization.py      # Alex -> MT-1002 = FORBIDDEN
│       └── test_transfer.py
│
├── database/                          # Oracle — all SQL here, no tables in code
│   ├── schema.sql                     # CREATE TABLE users, accounts, transactions,
│   │                                  #   sessions, audit_logs + sequences + indexes
│   ├── seed.sql                       # 5 users, 7 accounts, 16 transactions
│   │                                  #   Alex MT-1001, Priya MT-1002, Sam MT-1003,
│   │                                  #   Teller, Admin — demo123, hashed on load
│   └── wallet/                        # Oracle wallet — NEVER commit
│       ├── cwallet.sso
│       ├── tnsnames.ora
│       └── sqlnet.ora
│
└── docs/
    ├── architecture.md                # diagram from Step 1
    ├── prompts.md                     # Prompts 0-7
    └── test-cases.md                  # Auth Lab checks
