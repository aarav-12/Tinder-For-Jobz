const computeMatchScore = require("../utils/matchScore");
const { getUserInterests } = require("./interestService");
const { deriveJobCategory } = require("../utils/jobCategory");

const EXPLORATION_RATE = 0.1;
const CATEGORY_REPEAT_PENALTY = 20;

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

function applyDiversityPenalty(scoredJobs) {
  const recentCategories = [];

  return scoredJobs.map((job) => {
    const category = job.category || deriveJobCategory(job);
    let score = job.score;

    if (recentCategories.includes(category)) {
      score -= CATEGORY_REPEAT_PENALTY;
    }

    recentCategories.push(category);
    if (recentCategories.length > 3) {
      recentCategories.shift();
    }

    return {
      ...job,
      category,
      score,
    };
  });
}

function injectExploration(scoredJobs) {
  if (scoredJobs.length < 5) {
    return scoredJobs;
  }

  const explorationCount = Math.max(1, Math.floor(scoredJobs.length * EXPLORATION_RATE));
  const explorationCandidates = [...scoredJobs]
    .sort(() => Math.random() - 0.5)
    .slice(0, explorationCount);
  const explorationIds = new Set(explorationCandidates.map((job) => String(job._id)));
  const mainFeed = scoredJobs.filter((job) => !explorationIds.has(String(job._id)));

  const step = Math.max(1, Math.floor(mainFeed.length / (explorationCandidates.length + 1)));
  const result = [];
  let randomIndex = 0;

  mainFeed.forEach((job, index) => {
    result.push(job);

    if ((index + 1) % step === 0 && randomIndex < explorationCandidates.length) {
      result.push({
        ...explorationCandidates[randomIndex],
        score: explorationCandidates[randomIndex].score - 5,
      });
      randomIndex += 1;
    }
  });

  while (randomIndex < explorationCandidates.length) {
    result.push({
      ...explorationCandidates[randomIndex],
      score: explorationCandidates[randomIndex].score - 5,
    });
    randomIndex += 1;
  }

  return result;
}

const rankJobs = async (user, jobs, preferences) => {
  const safePreferences = preferences ?? {
    liked: new Set(),
    disliked: new Set(),
  };

  const interests = await getUserInterests(user._id);

  const scoredJobs = jobs.map((job) => {
    const finalScore = computeFinalScore(job, user, safePreferences);
    const category = job.category || deriveJobCategory(job);
    const interestScore = interests?.[category] || 0;

    return {
      ...job,
      category,
      baseScore: finalScore,
      score: finalScore + interestScore,
    };
  });

  const diversified = applyDiversityPenalty(scoredJobs);
  diversified.sort((a, b) => b.score - a.score);
  const explored = injectExploration(diversified);

  console.log("🏆 Top score:", explored[0]?.score);

  return explored;
};

module.exports = {
  rankJobs,
};