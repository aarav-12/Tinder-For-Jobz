const computeMatchScore = require("../utils/matchScore");

function rankJobs(jobs, candidate) {
  const now = new Date();

  const scoredJobs = jobs.map((job) => {
    const baseScore = computeMatchScore(candidate, job);

    // 🔥 add recency boost
    const daysOld =
      (now - new Date(job.createdAt)) / (1000 * 60 * 60 * 24);

    const recencyScore = Math.max(0, 1 - daysOld / 30);

    const finalScore = baseScore * 0.7 + recencyScore * 0.3;

    return {
      ...job,
      matchScore: finalScore,
    };
  });

  scoredJobs.sort((a, b) => b.matchScore - a.matchScore);

  console.log("🏆 Top score:", scoredJobs[0]?.matchScore);

  return scoredJobs;
}

module.exports = {
  rankJobs,
};