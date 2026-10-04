import io, os, re, math, json, hashlib
from datetime import datetime
from pathlib import Path
from collections import Counter

import fitz
from docx import Document
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@hirelens.ai").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "HireLens@2026")
if ENVIRONMENT == "production" and (SECRET_KEY == "dev-only-change-this-secret" or len(SECRET_KEY) < 32):
    raise RuntimeError("Production requires a strong SECRET_KEY (32+ characters).")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Render provides PostgreSQL through DATABASE_URL.
# Local development falls back to SQLite so the project remains easy to run in VS Code.
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    DB_PATH = BASE.parent / "hirelens.db"
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(Text)
    requirements = Column(Text)
    created_at = Column(String)

class Candidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)
    phone = Column(String)
    location = Column(String)
    resume_text = Column(Text)
    profile = Column(Text)
    score = Column(Float, default=0)
    risk_level = Column(String, default="Low")
    status = Column(String, default="New")
    notes = Column(Text, default="")
    job_id = Column(Integer, nullable=True)

Base.metadata.create_all(engine)

app = FastAPI(title="HireLens AI", version="2.0.0")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="hirelens_session", max_age=60*60*8, same_site="lax", https_only=(ENVIRONMENT == "production"))
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SKILLS = {
    "python":["python"],
    "java":["java"],
    "c++":["c++","cpp"],
    "javascript":["javascript","js"],
    "typescript":["typescript","ts"],
    "sql":["sql","mysql","postgresql","postgres"],
    "machine learning":["machine learning","ml","scikit-learn","sklearn"],
    "deep learning":["deep learning","pytorch","tensorflow","keras"],
    "tensorflow":["tensorflow"],
    "pytorch":["pytorch"],
    "scikit-learn":["scikit-learn","sklearn"],
    "nlp":["nlp","natural language processing"],
    "computer vision":["computer vision","opencv"],
    "pandas":["pandas"],
    "numpy":["numpy"],
    "aws":["aws","amazon web services"],
    "azure":["azure"],
    "gcp":["gcp","google cloud"],
    "docker":["docker","containerization"],
    "kubernetes":["kubernetes","k8s"],
    "fastapi":["fastapi"],
    "flask":["flask"],
    "react":["react","reactjs"],
    "node.js":["node.js","nodejs"],
    "git":["git","github"],
    "power bi":["power bi","powerbi"],
    "tableau":["tableau"],
    "excel":["excel","microsoft excel"],
    "mongodb":["mongodb","mongo"],
    "firebase":["firebase"],
    "blockchain":["blockchain","web3"],
    "solidity":["solidity"],
    "linux":["linux"],
    "data analysis":["data analysis","data analytics"],
    "data visualization":["data visualization","data storytelling"],
}

def extract_pdf(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)

def extract_docx(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)

def extract_text(filename: str, data: bytes) -> str:
    ext = filename.lower().split(".")[-1]
    if ext == "pdf": return extract_pdf(data)
    if ext == "docx": return extract_docx(data)
    if ext in ("txt","md"): return data.decode("utf-8", errors="ignore")
    raise ValueError("Supported formats: PDF, DOCX, TXT")

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()

def find_email(text):
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""

def find_phone(text):
    m = re.search(r"(?:\+91[\s-]?)?[6-9]\d{9}", re.sub(r"[\(\)]","",text))
    return m.group(0) if m else ""

def extract_skills(text):
    t = normalize(text)
    found = []
    evidence = {}
    for canonical, aliases in SKILLS.items():
        hits = [a for a in aliases if re.search(r"(?<!\w)"+re.escape(a.lower())+r"(?!\w)", t)]
        if hits:
            found.append(canonical)
            # evidence sentence
            lines = [x.strip() for x in text.splitlines() if any(h.lower() in x.lower() for h in hits)]
            evidence[canonical] = (lines[0] if lines else f"Mentioned in resume text: {hits[0]}")
    return sorted(set(found)), evidence

def extract_years(text):
    vals = [int(x) for x in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
    return vals

def extract_experience(text):
    t = normalize(text)
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+)?experience", t)]
    if nums: return max(nums)
    # estimate from explicit job durations
    return 0.0

def extract_education(text):
    t = normalize(text)
    degrees = []
    for d in ["b.tech","btech","b.e","be","m.tech","mtech","mca","bca","b.sc","m.sc","mba","phd","bachelor","master"]:
        if d in t: degrees.append(d.upper())
    return sorted(set(degrees))

def profile_from_text(text, name_hint=""):
    skills, evidence = extract_skills(text)
    years = extract_experience(text)
    years_found = extract_years(text)
    education = extract_education(text)
    return {
        "name": name_hint or "",
        "email": find_email(text),
        "phone": find_phone(text),
        "skills": skills,
        "evidence": evidence,
        "experience_years": years,
        "education": education,
        "years": years_found,
        "projects": extract_projects(text),
    }

def extract_projects(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    out = []
    for i, line in enumerate(lines):
        if re.search(r"\b(project|projects)\b", line, re.I):
            for nxt in lines[i+1:i+4]:
                if len(nxt) > 10:
                    out.append(nxt[:180])
    return out[:5]

def analyze_job(description):
    skills, evidence = extract_skills(description)
    t = normalize(description)
    required = []
    preferred = []
    # crude but transparent classification
    for s in skills:
        aliases = SKILLS[s]
        first_pos = min([t.find(a) for a in aliases if a in t] or [999999])
        window = t[max(0, first_pos-100):first_pos+100]
        if any(k in window for k in ["required","must have","mandatory","essential"]):
            required.append(s)
        else:
            preferred.append(s)
    years = extract_experience(description)
    degree = extract_education(description)
    return {
        "skills": skills,
        "required_skills": sorted(set(required)) or skills[:min(5,len(skills))],
        "preferred_skills": sorted(set(preferred)),
        "experience_years": years,
        "education": degree,
        "evidence": evidence
    }

def semantic_score(job_text, resume_text):
    if not job_text.strip() or not resume_text.strip(): return 0.0
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1,2), max_features=5000)
    try:
        X = vec.fit_transform([job_text, resume_text])
        return float(cosine_similarity(X[0:1], X[1:2])[0][0] * 100)
    except Exception:
        return 0.0

def match_candidate(profile, resume_text, job):
    req = set(job["required_skills"])
    cand = set(profile["skills"])
    matched = sorted(req & cand)
    missing = sorted(req - cand)
    pref = set(job.get("preferred_skills", []))
    pref_match = sorted(pref & cand)
    skill_score = (len(matched)/len(req)*100) if req else 0
    pref_score = (len(pref_match)/len(pref)*100) if pref else 0
    exp_req = float(job.get("experience_years") or 0)
    exp = float(profile.get("experience_years") or 0)
    exp_score = 100 if not exp_req else min(100, exp/exp_req*100)
    edu_score = 100 if not job.get("education") else (100 if set(job["education"]) & set(profile.get("education",[])) else 45)
    sem = semantic_score(job.get("raw_description",""), resume_text)
    project_score = min(100, 60 + 10*len(profile.get("projects",[])))
    cert_score = 100 if "certif" in normalize(resume_text) else 60

    unsupported = detect_unsupported_claims(profile, resume_text)
    contradictions = detect_contradictions(profile, resume_text)
    penalty = min(25, len(unsupported)*5 + len(contradictions)*7)

    final = (
        skill_score*0.35 +
        exp_score*0.20 +
        project_score*0.15 +
        edu_score*0.10 +
        cert_score*0.10 +
        sem*0.10
    )
    final = max(0, min(100, final - penalty))
    risk = "High" if contradictions or len(unsupported) >= 2 else ("Medium" if unsupported or missing else "Low")
    recommendation = "Strong Match" if final >= 80 else ("Potential Match" if final >= 65 else "Low Match")
    return {
        "score": round(final,1),
        "breakdown": {
            "Required Skills": round(skill_score,1),
            "Experience": round(exp_score,1),
            "Projects": round(project_score,1),
            "Education": round(edu_score,1),
            "Certifications": round(cert_score,1),
            "Semantic Match": round(sem,1),
        },
        "matched_skills": matched,
        "missing_skills": missing,
        "preferred_matches": pref_match,
        "unsupported_claims": unsupported,
        "contradictions": contradictions,
        "risk_level": risk,
        "recommendation": recommendation,
        "evidence": {k: profile.get("evidence",{}).get(k,"") for k in matched}
    }

def detect_unsupported_claims(profile, text):
    t = normalize(text)
    issues = []
    for skill in profile.get("skills",[]):
        aliases = SKILLS.get(skill, [skill])
        skill_mentions = sum(t.count(a.lower()) for a in aliases)
        if skill_mentions == 1 and re.search(r"(expert|advanced|proficient|master|specialist)", t):
            issues.append({
                "claim": f"{skill.title()} expertise",
                "severity": "Medium",
                "reason": "Skill is strongly claimed but little supporting evidence was found."
            })
    return issues[:5]

def detect_contradictions(profile, text):
    issues = []
    years = profile.get("years", [])
    exp = profile.get("experience_years", 0)
    if exp and years:
        graduation = max(years)
        current = datetime.now().year
        possible = max(0, current - graduation)
        if exp > possible + 3:
            issues.append({
                "claim": f"{exp:g} years of experience",
                "severity": "Medium",
                "reason": "The claimed experience may need verification against the timeline found in the resume."
            })
    # overlapping or suspicious date ranges
    if len(years) >= 4 and len(set(years)) < len(years):
        issues.append({
            "claim": "Repeated timeline dates",
            "severity": "Low",
            "reason": "Repeated dates were found; recruiter review is recommended."
        })
    return issues[:5]

def serialize_candidate(c):
    p = json.loads(c.profile or "{}")
    screening = p.get("screening", {})
    return {
        "id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
        "location": c.location, "score": c.score, "risk_level": c.risk_level,
        "status": c.status, "notes": c.notes, "profile": p, "screening": screening
    }

def _hash_password(password: str, salt: bytes | None = None) -> str:
    import os as _os, hashlib as _hashlib, base64 as _base64
    salt = salt or _os.urandom(16)
    digest = _hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return _base64.b64encode(salt).decode() + ":" + _base64.b64encode(digest).decode()

def _verify_password(password: str, stored: str) -> bool:
    import base64 as _base64, hashlib as _hashlib, hmac as _hmac
    try:
        salt_b64, digest_b64 = stored.split(":", 1)
        salt = _base64.b64decode(salt_b64)
        expected = _base64.b64decode(digest_b64)
        actual = _hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
        return _hmac.compare_digest(actual, expected)
    except Exception:
        return False

ADMIN_PASSWORD_HASH = _hash_password(ADMIN_PASSWORD)

def require_session(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return request.session["user"]

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    public = path in {"/", "/login", "/api/health", "/api/auth/login", "/api/auth/me", "/static/login.html"} or path.startswith("/static/")
    if path.startswith("/api/") and not public and not request.session.get("user"):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (STATIC/"login.html").read_text(encoding="utf-8")

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request):
    email = payload.email.strip().lower()
    if email != ADMIN_EMAIL or not _verify_password(payload.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session["user"] = {"email": ADMIN_EMAIL, "role": "Recruiter"}
    return {"authenticated": True, "user": request.session["user"]}

@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"authenticated": False}

@app.get("/api/auth/me")
def auth_me(request: Request):
    return {"authenticated": bool(request.session.get("user")), "user": request.session.get("user")}

class JobCreate(BaseModel):
    title: str
    description: str

class ChatRequest(BaseModel):
    question: str
    job_id: int | None = None

class DecisionRequest(BaseModel):
    status: str
    notes: str = ""

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    return (STATIC/"index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"status":"ok","service":"HireLens AI","version":"2.0.0","database":"postgresql" if DATABASE_URL else "sqlite"}

@app.get("/api/jobs")
def jobs():
    db=SessionLocal()
    rows=db.query(Job).order_by(Job.id.desc()).all()
    out=[{"id":j.id,"title":j.title,"description":j.description,"requirements":json.loads(j.requirements or "{}")} for j in rows]
    db.close()
    return out

@app.post("/api/jobs")
def create_job(payload: JobCreate):
    db=SessionLocal()
    req=analyze_job(payload.description)
    req["raw_description"]=payload.description
    j=Job(title=payload.title, description=payload.description, requirements=json.dumps(req), created_at=datetime.now().isoformat())
    db.add(j); db.commit(); db.refresh(j)
    db.close()
    return {"id":j.id,"title":j.title,"requirements":req}

@app.post("/api/jobs/{job_id}/resumes")
async def upload_resumes(job_id: int, files: list[UploadFile] = File(...)):
    db=SessionLocal()
    job=db.query(Job).filter(Job.id==job_id).first()
    if not job:
        db.close(); raise HTTPException(404,"Job not found")
    job_data=json.loads(job.requirements or "{}")
    job_data["raw_description"]=job.description
    results=[]
    existing_hashes = {hashlib.sha256((c.resume_text or "").encode("utf-8", errors="ignore")).hexdigest() for c in db.query(Candidate).filter(Candidate.job_id==job_id).all()}
    for f in files:
        try:
            if not f.filename or f.filename.lower().split(".")[-1] not in {"pdf", "docx", "txt", "md"}:
                raise ValueError("Unsupported file type. Use PDF, DOCX, TXT or MD.")
            data=await f.read()
            if len(data) > 5 * 1024 * 1024:
                raise ValueError("File is larger than 5 MB.")
            file_hash = hashlib.sha256(data).hexdigest()
            if file_hash in existing_hashes:
                results.append({"filename":f.filename,"error":"Duplicate resume detected for this job."})
                continue
            text=extract_text(f.filename,data)
            if len(text.strip()) < 40:
                raise ValueError("Very little readable text was found. If this is a scanned PDF, upload a text-readable PDF/DOCX.")
            profile=profile_from_text(text)
            result=match_candidate(profile,text,job_data)
            profile["screening"]=result
            name=profile.get("name") or Path(f.filename).stem.replace("_"," ").title()
            c=Candidate(name=name,email=profile["email"],phone=profile["phone"],location="",resume_text=text,profile=json.dumps(profile),score=result["score"],risk_level=result["risk_level"],job_id=job_id)
            db.add(c); db.commit(); db.refresh(c)
            existing_hashes.add(file_hash)
            results.append(serialize_candidate(c))
        except Exception as e:
            results.append({"filename":f.filename,"error":str(e)})
    db.close()
    return {"processed":len([x for x in results if "error" not in x]),"results":results}

@app.get("/api/candidates")
def candidates(job_id: int | None=None, q: str="", min_score: float=0, risk: str="All"):
    db=SessionLocal()
    query=db.query(Candidate)
    if job_id: query=query.filter(Candidate.job_id==job_id)
    rows=query.all()
    out=[]
    for c in rows:
        x=serialize_candidate(c)
        if x["score"] < min_score: continue
        if risk!="All" and x["risk_level"]!=risk: continue
        hay=(x["name"]+" "+(x["profile"].get("skills") and " ".join(x["profile"]["skills"]) or "")).lower()
        if q and q.lower() not in hay: continue
        out.append(x)
    db.close()
    return sorted(out,key=lambda x:x["score"],reverse=True)

@app.get("/api/candidates/{candidate_id}")
def candidate(candidate_id:int):
    db=SessionLocal(); c=db.query(Candidate).filter(Candidate.id==candidate_id).first(); db.close()
    if not c: raise HTTPException(404,"Candidate not found")
    return serialize_candidate(c)

@app.post("/api/candidates/{candidate_id}/decision")
def decision(candidate_id:int,payload:DecisionRequest):
    db=SessionLocal(); c=db.query(Candidate).filter(Candidate.id==candidate_id).first()
    if not c: db.close(); raise HTTPException(404,"Candidate not found")
    c.status=payload.status; c.notes=payload.notes
    db.commit(); out=serialize_candidate(c); db.close(); return out

@app.get("/api/analytics")
def analytics(job_id:int|None=None):
    db=SessionLocal(); q=db.query(Candidate)
    if job_id:q=q.filter(Candidate.job_id==job_id)
    rows=q.all(); db.close()
    scores=[r.score for r in rows]
    risks=Counter(r.risk_level for r in rows)
    skills=Counter()
    for r in rows:
        p=json.loads(r.profile or "{}")
        for s in p.get("skills",[]): skills[s]+=1
    return {
        "total":len(rows),
        "strong":sum(x>=80 for x in scores),
        "medium":sum(65<=x<80 for x in scores),
        "low":sum(x<65 for x in scores),
        "average":round(sum(scores)/len(scores),1) if scores else 0,
        "risks":dict(risks),
        "top_skills":[{"skill":k,"count":v} for k,v in skills.most_common(8)]
    }

@app.post("/api/demo")
def demo():
    db=SessionLocal()
    # create/reuse demo job
    j=db.query(Job).filter(Job.title=="ML Engineer — Demo").first()
    if not j:
        desc="""We are hiring an ML Engineer with 3+ years experience.
        Required: Python, Machine Learning, SQL, scikit-learn.
        Preferred: AWS, Docker, NLP.
        Education: B.Tech or M.Tech."""
        req=analyze_job(desc); req["raw_description"]=desc
        j=Job(title="ML Engineer — Demo",description=desc,requirements=json.dumps(req),created_at=datetime.now().isoformat())
        db.add(j); db.commit(); db.refresh(j)
    existing=db.query(Candidate).filter(Candidate.job_id==j.id).count()
    if existing>=8:
        db.close(); return {"job_id":j.id,"message":"Demo already loaded"}
    samples=[
        ("Aarav Mehta","Python Machine Learning SQL scikit-learn AWS Docker. 4 years of professional experience. B.Tech Computer Engineering. Built an NLP recommendation project using Python and scikit-learn."),
        ("Priya Kulkarni","Python ML SQL TensorFlow. 3 years of experience. B.Tech Computer Science. Developed machine learning and NLP projects. Expert in TensorFlow."),
        ("Rohan Shah","Python SQL pandas numpy. 2 years of experience. B.Tech AI. Built data analysis and ML projects."),
        ("Sneha Patil","Java React SQL. 3 years of experience. B.Tech IT. Built web applications and dashboards."),
        ("Kabir Joshi","Python Machine Learning SQL scikit-learn Docker. 5 years of experience. M.Tech AI. Developed ML pipelines and deployed models."),
        ("Neha Deshmukh","Python Machine Learning NLP. 1 year of experience. B.Tech AI. Built sentiment analysis and NLP projects."),
        ("Vivek More","Python SQL AWS. 2 years of experience. B.Tech. Data analysis and cloud projects."),
        ("Isha Jadhav","Python Machine Learning SQL scikit-learn. 6 years of professional experience. B.Tech completed in 2025. Expert in TensorFlow."),
    ]
    for name,text in samples:
        p=profile_from_text(text,name)
        r=match_candidate(p,text,json.loads(j.requirements)|{"raw_description":j.description})
        p["screening"]=r
        c=Candidate(name=name,email="",phone="",location="Pune",resume_text=text,profile=json.dumps(p),score=r["score"],risk_level=r["risk_level"],job_id=j.id)
        db.add(c)
    db.commit(); db.close()
    return {"job_id":j.id,"message":"Demo loaded","count":len(samples)}

@app.post("/api/chat")
def chat(req:ChatRequest):
    db=SessionLocal()
    q=db.query(Candidate)
    if req.job_id:q=q.filter(Candidate.job_id==req.job_id)
    rows=q.order_by(Candidate.score.desc()).all()
    question=req.question.lower()
    if not rows:
        db.close(); return {"answer":"I don't have candidate data yet. Load Demo Mode or upload resumes first."}
    if "top" in question or "best" in question or "strong" in question:
        top=rows[:5]
        answer="Top candidates: " + "; ".join(f"{i+1}. {c.name} ({c.score:.1f}%)" for i,c in enumerate(top))
    elif "why" in question:
        top=rows[0]; p=json.loads(top.profile or "{}"); s=p.get("screening",{})
        answer=f"{top.name} ranks highest at {top.score:.1f}% because they match {len(s.get('matched_skills',[]))} required skills, with strengths in {', '.join(s.get('matched_skills',[])[:5]) or 'the job requirements'}. Missing: {', '.join(s.get('missing_skills',[])) or 'none detected'}. Risk: {top.risk_level}."
    elif "aws" in question:
        hits=[]
        for c in rows:
            p=json.loads(c.profile or "{}")
            if "aws" in p.get("skills",[]): hits.append(c.name)
        answer="Candidates with AWS: " + (", ".join(hits) if hits else "None found.")
    else:
        answer="I can answer questions about candidate ranking, matched/missing skills, AWS, risks, and screening scores using the uploaded candidate data."
    db.close(); return {"answer":answer}

@app.get("/api/report/{candidate_id}")
def report(candidate_id:int):
    db=SessionLocal(); c=db.query(Candidate).filter(Candidate.id==candidate_id).first(); db.close()
    if not c: raise HTTPException(404,"Candidate not found")
    p=json.loads(c.profile or "{}"); s=p.get("screening",{})
    path=BASE.parent/f"report_{candidate_id}.pdf"
    styles=getSampleStyleSheet()
    doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=36,leftMargin=36,topMargin=36,bottomMargin=36)
    story=[Paragraph("HireLens AI — Candidate Screening Report",styles["Title"]),Spacer(1,12),
           Paragraph(f"<b>Candidate:</b> {c.name}",styles["BodyText"]),
           Paragraph(f"<b>Overall Match:</b> {c.score:.1f}%",styles["BodyText"]),
           Paragraph(f"<b>Recommendation:</b> {s.get('recommendation','')}",styles["BodyText"]),Spacer(1,12)]
    data=[["Category","Score"]]+[[k,f"{v:.1f}%"] for k,v in s.get("breakdown",{}).items()]
    t=Table(data,colWidths=[260,120]); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#111827")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.5,colors.grey),("PADDING",(0,0),(-1,-1),7)]))
    story += [t,Spacer(1,14),Paragraph("<b>Matched Skills</b>: "+", ".join(s.get("matched_skills",[])),styles["BodyText"]),
              Paragraph("<b>Missing Skills</b>: "+", ".join(s.get("missing_skills",[])) or "None",styles["BodyText"]),
              Paragraph("<b>Risk</b>: "+c.risk_level,styles["BodyText"]),Spacer(1,10)]
    for item in s.get("unsupported_claims",[]):
        story.append(Paragraph(f"⚠ {item['claim']}: {item['reason']}",styles["BodyText"]))
    for item in s.get("contradictions",[]):
        story.append(Paragraph(f"⚠ {item['claim']}: {item['reason']}",styles["BodyText"]))
    doc.build(story)
    return FileResponse(str(path),media_type="application/pdf",filename=f"HireLens_{c.name.replace(' ','_')}.pdf")

@app.get("/api/reset")
def reset():
    db=SessionLocal()
    db.query(Candidate).delete(); db.query(Job).delete(); db.commit(); db.close()
    return {"message":"Demo data cleared"}
