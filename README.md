# HireLens AI — Explainable Resume Intelligence

HireLens AI is a competition-ready recruitment screening platform that ranks candidates against a job description using explainable NLP matching, evidence extraction, skill-gap analysis, and claim/consistency checks.

## What the final build includes

- Recruiter login with protected session
- Job creation and JD analysis
- Multiple PDF/DOCX/TXT resume upload
- Resume information extraction
- Skill normalization
- Hybrid candidate scoring
- Explainable score breakdown
- Evidence snippets for matched skills
- Required vs preferred skills
- Experience and education matching
- Skill-gap analysis
- Unsupported expertise claim detection
- Timeline/experience inconsistency detection
- Duplicate resume detection per job
- Search, score and risk filters
- Candidate decisions: Interview / Maybe / Rejected
- Recruiter analytics dashboard
- Evidence-based recruiter assistant
- Candidate PDF screening report
- Demo mode for a reliable hackathon presentation
- SQLite for simple local development
- PostgreSQL for deployment
- Docker + Render configuration
- Health endpoint for deployment monitoring

## Competition positioning

**Not just matching resumes — finding the right candidate with evidence.**

The differentiator is that HireLens AI does not only reward keyword overlap. It shows why a candidate matches, what is missing, and which claims may require verification.

## Architecture

Browser → Recruiter Authentication → FastAPI → PostgreSQL/SQLite → Resume Parser → JD Analyzer → Matching Engine → Explainability + Claim Verification → Ranking → Recruiter Dashboard

## Local setup — Windows

Open the project in VS Code terminal:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

`http://127.0.0.1:8000`

### Local login

When `ENVIRONMENT` is not `production`, the built-in development credentials are:

- Email: `admin@hirelens.ai`
- Password: `HireLens@2026`

Change these before any public deployment.

## Production environment variables

Set these in Render — **never commit them to GitHub**:

```text
ENVIRONMENT=production
SECRET_KEY=<long-random-secret-at-least-32-characters>
ADMIN_EMAIL=<your-recruiter-email>
ADMIN_PASSWORD=<strong-password>
DATABASE_URL=<Render PostgreSQL Internal Database URL>
```

## Deploy on Render

### 1. Push this project to GitHub

Create a public or private GitHub repository and push the complete project. Do not upload `.env` files or secrets.

### 2. Create PostgreSQL

In Render, create a PostgreSQL database in the same region as the web service. Copy its **Internal Database URL**.

### 3. Create Web Service

Create a new Render Web Service from the GitHub repository.

Runtime: **Docker**

Render will use the included `Dockerfile`.

### 4. Add environment variables

Add:

- `DATABASE_URL`
- `ENVIRONMENT=production`
- `SECRET_KEY`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

### 5. Deploy

After deployment, open the generated Render URL.

The application should show the **Recruiter Login** page first.

### 6. Health check

Open:

`https://YOUR-RENDER-URL.onrender.com/api/health`

A healthy deployment returns JSON with `status: ok`.

## Demo flow for judges

1. Sign in as recruiter.
2. Open Dashboard.
3. Launch Demo Mode.
4. Open Candidates.
5. Show ranked candidates.
6. Open the top candidate.
7. Explain the score breakdown.
8. Show evidence for matched skills.
9. Show missing skills.
10. Show claim verification / inconsistency warnings.
11. Compare the ranking with another candidate.
12. Use the recruiter assistant: “Why is the top candidate ranked highest?”
13. Shortlist the candidate.
14. Open the PDF screening report.

## Important limitation

This is a hackathon/competition deployment, not a regulated enterprise HR system. Automated scores are decision-support signals and should not be the sole basis for employment decisions. Human review remains required.

## Supported resume formats

PDF, DOCX, TXT and MD. Text-readable PDFs work best. Scanned image-only PDFs require OCR to be added before production enterprise use.

## Security notes

- Passwords are not stored in the database.
- Session cookies are HTTP-only and secure in production.
- Secrets are supplied through environment variables.
- Resume uploads are limited to 5 MB per file.
- Unsupported file types are rejected.
- Duplicate resumes for the same job are detected.
- Production should use HTTPS, which Render provides for the deployed service.
