# Production-Ready Dynamic Multi-Tenant FastAPI Application

A complete, production-grade, scalable, secure, and maintainable multi-tenant backend architecture built with **FastAPI**, **Starlette**, **SQLAlchemy 2.x Async**, and **PostgreSQL**.

This project implements a dynamic `app.mount("/{tenant}", TenantDispatcher())` pattern where incoming requests are dynamically dispatched to independent, cached, tenant-specific FastAPI sub-applications while strictly enforcing database and context isolation.

---

## 1. Architectural Overview

### The Dynamic Mounting Challenge in Starlette/FastAPI
Standard Starlette `Mount(path, app)` does not support parameterized routing by default (it checks literal path prefix matching or requires exact trailing slashes).
To solve this cleanly and meet the architectural requirement:
1. `DynamicTenantMount` subclasses Starlette's `Mount` and compiles regex matching `^/(?P<tenant>[^/]+)(?P<subpath>/.*)?$`.
2. `DynamicTenantFastAPI` automatically intercepts parameterized paths in `app.mount("/{tenant}", TenantDispatcher())`, inserting the dynamic mount into the routing table.
3. Reserved routes (e.g. `/health`, `/admin`, `/docs`, `/openapi.json`) are prioritized and evaluated first; requests to `/health` or `/admin/...` bypass dynamic tenant resolution.
4. The custom ASGI `TenantDispatcher` dynamically extracts the tenant slug, validates syntax, checks active status in the database, retrieves or lazy-instantiates the tenant's sub-application via an async concurrency-safe LRU cache, injects tenant context, rewrites ASGI scope (`root_path` and `path`), and forwards the request.

### Request Lifecycle Diagram

```mermaid
flowchart TD
    A["Incoming HTTP Request"] --> B["RequestContextMiddleware<br/>(Request ID, Timing, Security Headers)"]
    B --> C{"Is Path Reserved?<br/>(/health, /admin, /docs)"}
    C -- "Yes" --> D["Root / Admin Router"]
    C -- "No" --> E["DynamicTenantMount (/{tenant})"]
    E --> F["TenantDispatcher (ASGI)"]
    F --> G{"Validate Tenant Slug<br/>Syntax & Allowlist"}
    G -- "Invalid" --> H["400 Bad Request"]
    G -- "Valid" --> I["Lookup Tenant in DB / Cache"]
    I -- "Not Found" --> J["404 Tenant Not Found"]
    I -- "Inactive" --> K["400 Tenant is Inactive"]
    I -- "Active" --> L{"In LRU App Cache?"}
    L -- "No" --> M["Tenant Application Factory<br/>(create_tenant_app)"]
    M --> N["Store in TenantAppCache"]
    L -- "Yes" --> N
    N --> O["Set Tenant ContextVar & Request State"]
    O --> P["Dispatch to Tenant Sub-Application"]
    P --> Q["Tenant Route Execution<br/>(Auth, Scoped DB Session, RBAC)"]
    Q --> R["Propagate Response"]
    R --> S["Reset ContextVar & Clean Up"]
```

---

## 2. Directory Structure

```text
dynamic-tenant-api/
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # Primary FastAPI application with dynamic mounting
│   │
│   ├── core/                       # Core system components
│   │   ├── config.py               # Pydantic v2 Settings from environment
│   │   ├── security.py             # Argon2 password hashing and verification
│   │   ├── exceptions.py           # Standard domain & HTTP exceptions
│   │   ├── logging.py              # Security-sanitized structured logging
│   │   └── middleware.py           # Request ID, process timing, security headers
│   │
│   ├── routing/                    # Dynamic ASGI routing subsystem
│   │   ├── __init__.py
│   │   ├── tenant_dispatcher.py    # Custom ASGI TenantDispatcher
│   │   ├── tenant_router.py        # DynamicTenantMount parameterized mount
│   │   └── route_registry.py       # Concurrency-safe LRU tenant application cache
│   │
│   ├── tenants/                    # Tenant domain models, repositories, and services
│   │   ├── __init__.py
│   │   ├── models.py               # Re-exported Tenant models
│   │   ├── schemas.py              # Pydantic schemas for tenants & resources
│   │   ├── repository.py           # Database repository for tenants & resources
│   │   ├── service.py              # Tenant lifecycle, tokens, and registration service
│   │   ├── dependencies.py         # Tenant ContextVar and FastAPI dependencies
│   │   └── tenant_factory.py       # Sub-application factory (create_tenant_app)
│   │
│   ├── authentication/             # Security, JWT, and authorization
│   │   ├── __init__.py
│   │   ├── jwt_handler.py          # PyJWT encoding, decoding, and signature validation
│   │   ├── password.py             # Password hashing utilities
│   │   ├── dependencies.py         # get_current_tenant_user with strict tenant checks
│   │   └── permissions.py          # Role-Based Access Control (RBAC) permission checks
│   │
│   ├── database/                   # Database layer
│   │   ├── __init__.py
│   │   ├── base.py                 # DeclarativeBase, UUID & Timestamp mixins
│   │   ├── session.py              # Async SQLAlchemy engine & session factory
│   │   ├── models.py               # Tenant, User, Role, Permission, AuditLog models
│   │   └── migrations/             # Alembic migration environment and versions
│   │       ├── env.py
│   │       ├── script.py.mako
│   │       └── versions/
│   │           └── 0001_initial_schema.py
│   │
│   ├── api/                        # Root & Administrative endpoints
│   │   ├── __init__.py
│   │   ├── health.py               # System health check and root landing
│   │   └── admin.py                # Tenant administration CRUD & status lifecycle
│   │
│   └── tenants_apps/               # Tenant application interface
│       ├── __init__.py
│       └── tenant_application.py   # Factory bridge
│
├── tests/                          # Automated Pytest suite
│   ├── conftest.py                 # Async fixtures, SQLite in-memory engine, seed data
│   ├── test_tenant_routing.py      # Routing, mounting, and query preservation tests
│   ├── test_tenant_isolation.py    # Strict cross-tenant isolation and DB scope tests
│   ├── test_authentication.py      # JWT validation, expiration, and refresh rotation tests
│   ├── test_authorization.py       # RBAC and permission enforcement tests
│   ├── test_dispatcher.py          # ASGI scope, lifespan, and app cache reuse tests
│   └── test_tenant_lifecycle.py    # Administrative CRUD, activation, deactivation tests
│
├── scripts/
│   └── create_admin.py             # CLI utility to create superadmin user
│
├── .env.example                    # Documented environment template
├── .gitignore                      # Git ignore rules
├── Dockerfile                      # Production multi-stage Docker build
├── docker-compose.yml              # Production Compose with PostgreSQL service
├── alembic.ini                     # Alembic migration configuration
├── requirements.txt                # Pinned dependencies
├── pyproject.toml                  # Project metadata, Ruff, and Pytest configuration
└── README.md                       # Complete documentation
```

---

## 3. Security and Multi-Tenant Isolation

Tenant isolation is treated as an uncompromising security boundary:

1. **Cross-Tenant Token Prevention**:
   Every JWT access token is scoped with `tenant_slug` and `tenant_id`. When accessing `/{tenant}/*`, `get_current_tenant_user` checks that the token's `tenant_slug` exactly matches the URL tenant. An Acme token cannot authenticate against Globex under any circumstances (`403 Forbidden: {"detail": "Access denied"}`).
2. **Database Query Scoping**:
   All tenant-scoped queries filter strictly by `tenant_id == current_tenant.id`. Even if an attacker provides a known UUID belonging to another tenant, the query returns `404 Not Found`.
3. **Context Isolation**:
   Tenant context is stored using Python's `contextvars.ContextVar` and cleaned up in a `finally:` block on every ASGI request, preventing context leaks between concurrent coroutines.
4. **Credential Protection**:
   Sensitive fields such as `database_url` and password hashes are never serialized in API schemas.
5. **Security Headers & Logging**:
   `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, and CSP are injected on every response. Passwords, secrets, and authorization bearer tokens are masked from logs.
6. **Refresh Token Rotation & Revocation**:
   Refresh tokens are stored as SHA-256 hashes. Refreshing rotates the token pair and immediately revokes the old refresh token. Reusing a revoked token results in a `401 Unauthorized`.

---

## 4. API Endpoints

### Administrative Endpoints (`/admin`)
Requires `X-Admin-Key` header or superuser JWT.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/admin/tenants` | Create a new tenant |
| `GET` | `/admin/tenants` | List all tenants (supports `skip`, `limit`, `status` filters) |
| `GET` | `/admin/tenants/{tenant_id}` | Retrieve tenant details by ID |
| `PATCH` | `/admin/tenants/{tenant_id}` | Update tenant name or configuration metadata |
| `DELETE` | `/admin/tenants/{tenant_id}` | Safely deactivate (soft-delete) tenant |
| `POST` | `/admin/tenants/{tenant_id}/activate` | Activate a deactivated tenant |
| `POST` | `/admin/tenants/{tenant_id}/deactivate` | Deactivate an active tenant |

### Root Endpoints
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Root system health check and database ping |
| `GET` | `/` | Root API documentation and pattern information |
| `GET` | `/docs` | Interactive Swagger UI for root application |

### Dynamic Tenant Endpoints (`/{tenant}`)
Each tenant has its own isolated sub-application:

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/{tenant}` | None | Tenant root landing & status |
| `GET` | `/{tenant}/health` | None | Tenant health check |
| `GET` | `/{tenant}/docs` | None | Tenant-specific Swagger UI |
| `GET` | `/{tenant}/openapi.json` | None | Tenant-specific OpenAPI specification |
| `POST` | `/{tenant}/auth/register` | None | Register a user inside this tenant |
| `POST` | `/{tenant}/auth/login` | None | Authenticate and obtain JWT token pair |
| `POST` | `/{tenant}/auth/refresh` | None | Rotate refresh token for new access token |
| `GET` | `/{tenant}/auth/me` | Bearer | Get authenticated user profile & role |
| `POST` | `/{tenant}/auth/logout` | Bearer | Revoke refresh token |
| `GET` | `/{tenant}/users` | Bearer (`users:read`) | List all users in this tenant |
| `POST` | `/{tenant}/users` | Bearer (`users:write`) | Invite / create user in this tenant |
| `GET` | `/{tenant}/dashboard` | Bearer | View tenant analytics and metrics |
| `GET` | `/{tenant}/settings` | Bearer (`settings:read`) | View tenant configuration settings |
| `POST` | `/{tenant}/resources` | Bearer (`resources:write`) | Create isolated tenant resource |
| `GET` | `/{tenant}/resources` | Bearer (`resources:read`) | List resources owned by this tenant |
| `GET` | `/{tenant}/resources/{id}` | Bearer (`resources:read`) | Retrieve specific tenant resource |

---

## 5. Local Setup and Installation

### Prerequisites
- Python 3.11+
- PostgreSQL (or local SQLite for lightweight development)

### 1. Create and Activate Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
copy .env.example .env     # Windows
cp .env.example .env       # Linux / macOS
```

### 4. Run Migrations & Seed Admin
```bash
# Apply database migrations
alembic upgrade head

# Create superadmin user
python scripts/create_admin.py admin@example.com AdminSecretPassword123! "Super Admin"
```

### 5. Start Application
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser.

---

## 6. Docker Deployment

To launch the complete application with PostgreSQL in Docker:

```bash
docker compose up --build -d
```

View logs:
```bash
docker compose logs -f web
```

Stop services:
```bash
docker compose down
```

---

## 7. Vercel Serverless Deployment

This application is ready for Vercel deployment out-of-the-box using Vercel's `@vercel/python` serverless runtime:

### Configuration Files Added
- `vercel.json`: Directs all incoming traffic to the serverless entrypoint `api/index.py`.
- `api/index.py`: Exposes the dynamic FastAPI ASGI instance `app`.
- `.vercelignore`: Strips tests, cache, local databases, and development files to ensure fast build times and small bundle size.
- `app/database/session.py`: Detects Vercel serverless environment (`VERCEL=1`), configures `NullPool` for external PostgreSQL (e.g. Neon, Supabase) to prevent connection saturation, and provides a safe `/tmp` fallback for preview deployments.

### Deploying via Vercel CLI
```bash
# 1. Install Vercel CLI (if not already installed)
npm install -g vercel

# 2. Deploy to preview
vercel

# 3. Deploy to production
vercel --prod
```

### Deploying via GitHub / Git Integration
1. Push this repository to GitHub, GitLab, or Bitbucket.
2. In the [Vercel Dashboard](https://vercel.com/new), click **Import Project**.
3. Select your repository. Vercel will automatically detect the Python configuration and `vercel.json`.
4. Under **Environment Variables**, add:
   - `DATABASE_URL`: Your cloud PostgreSQL async connection string (e.g. from Neon or Supabase: `postgresql+asyncpg://user:password@ep-host.region.aws.neon.tech/neondb?ssl=require`)
   - `JWT_SECRET_KEY`: A secure 32+ character random secret.
   - `ADMIN_API_KEY`: Your secret key for `/admin` management endpoints.
   - `APP_ENV`: `production`
   - `DEBUG`: `false`
5. Click **Deploy**. Your API will be live with Swagger UI at `https://your-domain.vercel.app/docs`.

---

## 8. Automated Testing Results

The comprehensive automated test suite covers all architectural, routing, security, isolation, and lifecycle requirements.

### Run Tests with Coverage
```bash
python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

### Execution Output:
```text
tests/test_authentication.py::test_valid_registration_and_login PASSED
tests/test_authentication.py::test_invalid_login_credentials PASSED
tests/test_authentication.py::test_expired_jwt_rejection PASSED
tests/test_authentication.py::test_invalid_jwt_signature_rejection PASSED
tests/test_authentication.py::test_wrong_issuer_or_audience PASSED
tests/test_authentication.py::test_refresh_token_rotation_and_revocation PASSED
tests/test_authorization.py::test_admin_role_has_full_permissions PASSED
tests/test_authorization.py::test_member_role_cannot_invite_users PASSED
tests/test_authorization.py::test_viewer_role_read_only PASSED
tests/test_dispatcher.py::test_dispatcher_lifespan_events PASSED
tests/test_dispatcher.py::test_tenant_subapplication_caching_and_reuse PASSED
tests/test_tenant_isolation.py::test_cross_tenant_token_rejection PASSED
tests/test_tenant_isolation.py::test_cross_tenant_resource_id_isolation PASSED
tests/test_tenant_isolation.py::test_database_queries_are_strictly_tenant_scoped PASSED
tests/test_tenant_isolation.py::test_concurrent_requests_no_context_leakage PASSED
tests/test_tenant_lifecycle.py::test_full_tenant_lifecycle PASSED
tests/test_tenant_lifecycle.py::test_admin_list_and_get_tenant PASSED
tests/test_tenant_lifecycle.py::test_admin_patch_tenant PASSED
tests/test_tenant_lifecycle.py::test_admin_conflict_duplicate_slug PASSED
tests/test_tenant_lifecycle.py::test_admin_unauthorized_without_key PASSED
tests/test_tenant_routing.py::test_root_health_and_landing PASSED
tests/test_tenant_routing.py::test_valid_tenant_routing PASSED
tests/test_tenant_routing.py::test_multiple_tenant_routing PASSED
tests/test_tenant_routing.py::test_unknown_tenant_rejection PASSED
tests/test_tenant_routing.py::test_invalid_tenant_slug_rejection PASSED
tests/test_tenant_routing.py::test_reserved_slug_rejection PASSED
tests/test_tenant_routing.py::test_query_parameter_and_body_preservation PASSED
tests/test_tenant_routing.py::test_tenant_specific_openapi_docs_and_dashboard PASSED

============================= 28 passed in 7.50s =============================
```

---

## 9. Known Limitations & Future Improvements

1. **Multi-Worker Application Cache**:
   The in-process `TenantAppCache` is stored in process memory. In a multi-worker deployment (`uvicorn --workers 4`), each worker maintains its own sub-application cache. When tenant configuration changes, Redis Pub/Sub can be added to broadcast cache invalidation events across all worker processes.
2. **Dynamic Database Schemas per Tenant**:
   The current implementation uses a shared database with strict `tenant_id` column isolation. The architecture is designed with a nullable `database_url` column on the `Tenant` model, allowing future extension into separate PostgreSQL schemas or dedicated physical databases per enterprise tenant.

