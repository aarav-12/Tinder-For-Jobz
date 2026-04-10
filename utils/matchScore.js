function computeMatchScore(candidate, job) {

  // candidate ke skills agar null/undefined ho to empty array le lo
  const candidateSkills = candidate.skills || []

  // job ke required skills
  const jobSkills = job.requiredSkills || []

  // candidate ka experience (default 0)
  const candidateExperience = candidate.experienceYears || 0

  // job ka minimum experience
  const jobMinExperience = job.minExperience || 0


  // -------------------------------
  // STEP 1: Skill overlap calculate
  // -------------------------------

  // job ke har skill ko check karte hain
  // agar candidate ke skills me exist karta hai to overlap
  const overlapSkills = jobSkills.filter(skill =>
    candidateSkills.includes(skill)
  )

  // kitne skills match hue
  const overlapCount = overlapSkills.length


  // -------------------------------
  // STEP 2: Skill score
  // -------------------------------

  // divide by zero se bachne ke liye guard
  const skillScore =
    jobSkills.length === 0
      ? 0
      : overlapCount / jobSkills.length


  // -------------------------------
  // STEP 3: Experience score
  // -------------------------------

  // agar candidate experience >= job required
  // to score 1 warna 0
  const experienceScore =
    candidateExperience >= jobMinExperience ? 1 : 0


  // -------------------------------
  // STEP 4: Final weighted score
  // -------------------------------

  const matchScore =
    (0.7 * skillScore) +
    (0.3 * experienceScore)


  // decimal ko clean karne ke liye
  return Number(matchScore.toFixed(2))
}

module.exports = computeMatchScore