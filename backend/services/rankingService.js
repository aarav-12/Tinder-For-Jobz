const computeMatchScore = require("../utils/matchScore");

const computeRecencyScore = (job) => {
  const now = new Date();

  const daysOld =
    (now - new Date(job.createdAt)) / (1000 * 60 * 60 * 24);

  return Math.max(0, 1 - daysOld / 30);
};

const computeFinalScore = (job, user, preferences) => {
  const baseScore = computeMatchScore(user, job);
  const recencyScore = computeRecencyScore(job);

  let behaviorBoost = 0;

  const jobId = job._id.toString();

  // boost liked jobs
  if (preferences.liked.has(jobId)) {
    behaviorBoost += 0.2;
  }

  // penalize disliked jobs
  if (preferences.disliked.has(jobId)) {
    behaviorBoost -= 0.3;
  }

  return baseScore * 0.6 + recencyScore * 0.3 + behaviorBoost;
};

const rankJobs = (user, jobs, preferences) => {
  const safePreferences = preferences ?? {
    liked: new Set(),
    disliked: new Set(),
  };

  const scoredJobs = jobs.map((job) => {
    const finalScore = computeFinalScore(job, user, safePreferences);

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