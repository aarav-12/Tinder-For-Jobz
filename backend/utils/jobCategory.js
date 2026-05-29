const CATEGORY_KEYWORDS = [
  {
    category: "AI",
    keywords: ["ai", "machine learning", "ml", "llm", "nlp", "openai", "data scientist", "prompt"],
  },
  {
    category: "Data",
    keywords: ["data", "analytics", "analyst", "bi", "warehouse", "etl", "dbt", "mlops"],
  },
  {
    category: "Engineering",
    keywords: ["engineer", "software", "backend", "frontend", "full stack", "platform", "infrastructure", "developer", "devops", "mobile"],
  },
  {
    category: "Design",
    keywords: ["design", "ux", "ui", "product designer", "visual", "brand"],
  },
  {
    category: "Product",
    keywords: ["product manager", "product", "pm", "roadmap"],
  },
  {
    category: "Marketing",
    keywords: ["marketing", "growth", "seo", "content", "brand"],
  },
  {
    category: "Sales",
    keywords: ["sales", "account executive", "biz dev", "business development", "revenue"],
  },
  {
    category: "Finance",
    keywords: ["finance", "accounting", "fp&a", "controller", "treasury"],
  },
  {
    category: "Operations",
    keywords: ["operations", "ops", "supply chain", "logistics", "program manager"],
  },
  {
    category: "Security",
    keywords: ["security", "privacy", "risk", "infosec", "compliance"],
  },
  {
    category: "People",
    keywords: ["hr", "recruiter", "talent", "people", "human resources"],
  },
  {
    category: "Support",
    keywords: ["support", "customer success", "customer service", "helpdesk", "success"],
  },
  {
    category: "Health",
    keywords: ["fitness", "health", "wellness", "nutrition", "medical", "clinical", "sports", "gym"],
  },
  {
    category: "Travel",
    keywords: ["travel", "hospitality", "hotel", "restaurant", "airline", "aviation"],
  },
];

function normalizeText(value) {
  return String(value || "").toLowerCase();
}

function deriveJobCategory(job = {}) {
  const haystack = [
    job.category,
    job.title,
    job.company,
    job.source,
    job.location,
    ...(Array.isArray(job.requiredSkills) ? job.requiredSkills : []),
  ]
    .filter(Boolean)
    .map(normalizeText)
    .join(" ");

  for (const entry of CATEGORY_KEYWORDS) {
    if (entry.keywords.some((keyword) => haystack.includes(keyword))) {
      return entry.category;
    }
  }

  return job.category || "General";
}

module.exports = {
  deriveJobCategory,
};