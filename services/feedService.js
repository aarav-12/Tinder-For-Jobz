const mongoose = require("mongoose");
const User = require("../models/User");

const candidateService = require("./candidateService");
const rankingService = require("./rankingService");
const { getUserSwipes } = require("./swipeService");
const { buildPreferenceProfile } = require("./preferenceService");

function toObjectId(value) {
  if (value instanceof mongoose.Types.ObjectId) return value;

  if (typeof value === "string" && mongoose.Types.ObjectId.isValid(value)) {
    return new mongoose.Types.ObjectId(value);
  }

  return null;
}

async function getJobFeed(candidateId) {
  const result = await getFeed(candidateId);
  return result.jobs;
}

async function getUser(candidateId) {
  const candidateObjectId = toObjectId(candidateId);
  if (!candidateObjectId) {
    throw new Error("Invalid candidate user ID");
  }

  const user = await User.findById(candidateObjectId).lean();
  if (!user) {
    throw new Error("Candidate not found");
  }

  return user;
}

const getFeed = async (candidateId, cursor) => {
  if (mongoose.connection.readyState === 0) {
    throw new Error("Database is not connected");
  }
  if (!candidateId) throw new Error("candidateId required");
  if (cursor && isNaN(new Date(cursor))) {
    throw new Error("Invalid cursor");
  }

  const user = await getUser(candidateId);
  const swipes = await getUserSwipes(candidateId);
  const preferences = buildPreferenceProfile(swipes);
  const swipedJobIds = swipes
    .map((s) => toObjectId(s.jobId))
    .filter(Boolean);

  const candidateJobs = await candidateService.getCandidates({
    user,
    swipes: swipedJobIds,
    cursor,
  });

  const rankedJobs = rankingService.rankJobs(
    user,
    candidateJobs,
    preferences
  );

  const topJobs = rankedJobs.slice(0, 20);

  return {
    jobs: topJobs,
    nextCursor: topJobs.length
      ? topJobs[topJobs.length - 1].createdAt
      : null,
  };
};

module.exports = { getFeed, getJobFeed };