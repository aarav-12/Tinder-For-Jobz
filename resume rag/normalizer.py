"""
Skill normalisation and domain mapping.

Same architecture as biomarker normalizer.py:
  - Canonical names defined once
  - Alias table maps raw strings → canonical form
  - All lookups O(1) via pre-built dict
  - No external calls, no LLM, pure determinism

WHY normalisation matters:
  "React.js", "ReactJS", "react", "React" all mean the same thing.
  Without normalisation:
    - embedding space treats them as different concepts
    - keyword boosting misses exact matches
    - skill matching between resume and job breaks

WHY domain structure:
  Groups related skills (e.g., "frontend", "backend", "devops").
  Used for:
    - skill gap analysis
    - domain coverage scoring
    - interview talking point: "candidate covers 4/6 skill domains"

PUBLIC API:
  normalize_skill(raw)    → canonical name | None
  get_domain(canonical)   → domain name | None
  map_to_domains(skills)  → {domain: [skills]}
"""

from __future__ import annotations

import re


# ─────────────────────────────────────────────────────────────────────────────
# 1. Canonical domain structure (DO NOT MODIFY without updating aliases)
# ─────────────────────────────────────────────────────────────────────────────
DOMAIN_STRUCTURE: dict[str, list[str]] = {
    "frontend": [
        "React", "Angular", "Vue", "NextJS", "Svelte",
        "TypeScript", "JavaScript", "HTML", "CSS", "Tailwind",
        "Redux", "jQuery", "Bootstrap", "SASS",
    ],
    "backend": [
        "NodeJS", "Express", "Python", "Django", "Flask",
        "FastAPI", "Java", "SpringBoot", "Go", "Rust",
        "Ruby", "RubyOnRails", "PHP", "Laravel", "CSharp",
        "DotNet", "GraphQL", "REST",
    ],
    "database": [
        "MongoDB", "PostgreSQL", "MySQL", "Redis", "SQLite",
        "DynamoDB", "Cassandra", "Firebase", "Supabase",
        "Elasticsearch", "Neo4j",
    ],
    "devops": [
        "Docker", "Kubernetes", "AWS", "GCP", "Azure",
        "Terraform", "Jenkins", "GitHubActions", "CircleCI",
        "Nginx", "Linux", "Ansible",
    ],
    "data": [
        "Pandas", "NumPy", "Spark", "Kafka", "Airflow",
        "dbt", "Snowflake", "BigQuery", "Tableau",
        "PowerBI", "SQL", "ETL",
    ],
    "ml_ai": [
        "TensorFlow", "PyTorch", "ScikitLearn", "OpenAI",
        "LangChain", "HuggingFace", "NLP", "ComputerVision",
        "MLOps", "Pinecone", "RAG",
    ],
    "mobile": [
        "ReactNative", "Flutter", "Swift", "Kotlin",
        "iOS", "Android", "Dart",
    ],
    "tools": [
        "Git", "Jira", "Figma", "Postman", "Swagger",
        "VSCode", "Vim", "Webpack", "Vite",
    ],
}

# Reverse map: canonical_name → domain
_CANONICAL_TO_DOMAIN: dict[str, str] = {
    skill: domain
    for domain, skills in DOMAIN_STRUCTURE.items()
    for skill in skills
}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Alias table — lowercased raw strings → canonical name
# ─────────────────────────────────────────────────────────────────────────────
# WHY exhaustive aliases:
#   Resumes are chaos. "react.js", "ReactJS", "react", "React 18" all appear.
#   Missing an alias = missed skill match = worse recommendations.

_RAW_ALIASES: dict[str, str] = {
    # ── Frontend ──
    "react": "React", "reactjs": "React", "react.js": "React",
    "react js": "React", "react 18": "React", "react 19": "React",
    "angular": "Angular", "angularjs": "Angular", "angular.js": "Angular",
    "angular 17": "Angular", "angular 18": "Angular",
    "vue": "Vue", "vuejs": "Vue", "vue.js": "Vue", "vue 3": "Vue",
    "nextjs": "NextJS", "next.js": "NextJS", "next js": "NextJS",
    "next": "NextJS",
    "svelte": "Svelte", "sveltejs": "Svelte", "sveltekit": "Svelte",
    "typescript": "TypeScript", "ts": "TypeScript",
    "javascript": "JavaScript", "js": "JavaScript", "ecmascript": "JavaScript",
    "es6": "JavaScript", "es2015": "JavaScript",
    "html": "HTML", "html5": "HTML",
    "css": "CSS", "css3": "CSS",
    "tailwind": "Tailwind", "tailwindcss": "Tailwind", "tailwind css": "Tailwind",
    "redux": "Redux", "redux toolkit": "Redux", "rtk": "Redux",
    "jquery": "jQuery", "j query": "jQuery",
    "bootstrap": "Bootstrap", "bootstrap 5": "Bootstrap",
    "sass": "SASS", "scss": "SASS", "less": "SASS",

    # ── Backend ──
    "node": "NodeJS", "nodejs": "NodeJS", "node.js": "NodeJS",
    "node js": "NodeJS",
    "express": "Express", "expressjs": "Express", "express.js": "Express",
    "python": "Python", "python3": "Python", "python 3": "Python",
    "django": "Django", "django rest framework": "Django", "drf": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI", "fast api": "FastAPI",
    "java": "Java", "java 17": "Java", "java 21": "Java",
    "spring": "SpringBoot", "spring boot": "SpringBoot",
    "springboot": "SpringBoot",
    "go": "Go", "golang": "Go",
    "rust": "Rust", "rust lang": "Rust",
    "ruby": "Ruby",
    "rails": "RubyOnRails", "ruby on rails": "RubyOnRails",
    "rubyonrails": "RubyOnRails",
    "php": "PHP",
    "laravel": "Laravel",
    "c#": "CSharp", "csharp": "CSharp", "c sharp": "CSharp",
    ".net": "DotNet", "dotnet": "DotNet", "asp.net": "DotNet",
    "graphql": "GraphQL", "graph ql": "GraphQL",
    "rest": "REST", "restful": "REST", "rest api": "REST",
    "rest apis": "REST",

    # ── Database ──
    "mongodb": "MongoDB", "mongo": "MongoDB", "mongoose": "MongoDB",
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL", "pg": "PostgreSQL",
    "mysql": "MySQL", "maria": "MySQL", "mariadb": "MySQL",
    "redis": "Redis",
    "sqlite": "SQLite", "sqlite3": "SQLite",
    "dynamodb": "DynamoDB", "dynamo": "DynamoDB",
    "cassandra": "Cassandra",
    "firebase": "Firebase", "firestore": "Firebase",
    "supabase": "Supabase",
    "elasticsearch": "Elasticsearch", "elastic": "Elasticsearch",
    "elastic search": "Elasticsearch",
    "neo4j": "Neo4j",

    # ── DevOps ──
    "docker": "Docker", "docker compose": "Docker",
    "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud": "GCP",
    "google cloud platform": "GCP",
    "azure": "Azure", "microsoft azure": "Azure",
    "terraform": "Terraform", "tf": "Terraform",
    "jenkins": "Jenkins",
    "github actions": "GitHubActions", "gh actions": "GitHubActions",
    "circleci": "CircleCI", "circle ci": "CircleCI",
    "nginx": "Nginx",
    "linux": "Linux", "ubuntu": "Linux", "centos": "Linux",
    "ansible": "Ansible",

    # ── Data ──
    "pandas": "Pandas",
    "numpy": "NumPy",
    "spark": "Spark", "pyspark": "Spark", "apache spark": "Spark",
    "kafka": "Kafka", "apache kafka": "Kafka",
    "airflow": "Airflow", "apache airflow": "Airflow",
    "dbt": "dbt",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery", "big query": "BigQuery",
    "tableau": "Tableau",
    "power bi": "PowerBI", "powerbi": "PowerBI",
    "sql": "SQL", "plsql": "SQL", "t-sql": "SQL",
    "etl": "ETL",

    # ── ML/AI ──
    "tensorflow": "TensorFlow", "tf": "TensorFlow",
    "pytorch": "PyTorch", "torch": "PyTorch",
    "scikit-learn": "ScikitLearn", "sklearn": "ScikitLearn",
    "scikit learn": "ScikitLearn",
    "openai": "OpenAI", "gpt": "OpenAI", "chatgpt": "OpenAI",
    "langchain": "LangChain",
    "huggingface": "HuggingFace", "hugging face": "HuggingFace",
    "nlp": "NLP", "natural language processing": "NLP",
    "computer vision": "ComputerVision", "cv": "ComputerVision",
    "mlops": "MLOps", "ml ops": "MLOps",
    "pinecone": "Pinecone",
    "rag": "RAG", "retrieval augmented generation": "RAG",

    # ── Mobile ──
    "react native": "ReactNative", "reactnative": "ReactNative",
    "flutter": "Flutter",
    "swift": "Swift", "swiftui": "Swift",
    "kotlin": "Kotlin",
    "ios": "iOS",
    "android": "Android",
    "dart": "Dart",

    # ── Tools ──
    "git": "Git", "github": "Git", "gitlab": "Git", "bitbucket": "Git",
    "jira": "Jira", "confluence": "Jira",
    "figma": "Figma",
    "postman": "Postman",
    "swagger": "Swagger", "openapi": "Swagger",
    "vscode": "VSCode", "vs code": "VSCode",
    "vim": "Vim", "neovim": "Vim",
    "webpack": "Webpack",
    "vite": "Vite",
}

# Pre-build lowercased lookup (belt-and-suspenders)
_ALIAS_MAP: dict[str, str] = {k.lower().strip(): v for k, v in _RAW_ALIASES.items()}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Public API
# ─────────────────────────────────────────────────────────────────────────────
def normalize_skill(raw: str) -> str | None:
    """
    Return canonical skill name or None if unknown.

    Strategy (same as biomarker normalizer):
      1. Direct lookup
      2. Strip trailing version numbers and retry
      3. Substring match as last resort
    """
    if not raw:
        return None
    cleaned = raw.strip().lower()

    # Direct lookup
    if cleaned in _ALIAS_MAP:
        return _ALIAS_MAP[cleaned]

    # Strip trailing version numbers: "React 18" → "react"
    shortened = re.sub(r"\s*\d+(\.\d+)*\s*$", "", cleaned).strip()
    if shortened in _ALIAS_MAP:
        return _ALIAS_MAP[shortened]

    # Strip dots: "Node.js" → "nodejs"
    dotless = cleaned.replace(".", "")
    if dotless in _ALIAS_MAP:
        return _ALIAS_MAP[dotless]

    return None


def get_domain(canonical: str) -> str | None:
    """Return domain name for a canonical skill."""
    return _CANONICAL_TO_DOMAIN.get(canonical)


def normalize_skills(raw_skills: list[str]) -> list[dict]:
    """
    Normalize a list of raw skills.
    Returns [{"raw": str, "canonical": str, "domain": str}] for each recognized skill.
    Unknown skills included with canonical=None, domain=None.
    """
    results = []
    seen = set()

    for raw in raw_skills:
        canonical = normalize_skill(raw)
        key = (canonical or raw).lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "raw": raw,
            "canonical": canonical,
            "domain": get_domain(canonical) if canonical else None,
        })

    return results


def map_to_domains(skills: list[str]) -> dict[str, list[str]]:
    """Return domain → [canonical_names] for recognized skills."""
    result: dict[str, list[str]] = {}
    for raw in skills:
        canonical = normalize_skill(raw)
        if canonical:
            domain = get_domain(canonical)
            if domain:
                result.setdefault(domain, []).append(canonical)
    return result