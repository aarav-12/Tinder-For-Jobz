const mongoose = require("mongoose");
const User = require("../models/User");
const Swipe = require("../models/Swipe");

const candidateService = require("./candidateService");
const { rankJobs } = require("./rankingService");

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

async function getUserSwipes(candidateId) {
  const candidateObjectId = toObjectId(candidateId);
  if (!candidateObjectId) {
    throw new Error("Invalid candidate user ID");
  }

  const swipeDocs = await Swipe.find({ userId: candidateObjectId })
    .select("jobId")
    .lean();

  return swipeDocs
    .map((s) => toObjectId(s.jobId))
    .filter(Boolean);
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

  const candidateJobs = await candidateService.getCandidates({
    user,
    swipes,
    cursor,
  });

  const rankedJobs = rankJobs(candidateJobs, user);

  const topJobs = rankedJobs.slice(0, 20);

  return {
    jobs: topJobs,
    nextCursor: topJobs.length
      ? topJobs[topJobs.length - 1].createdAt
      : null,
  };
};

module.exports = { getFeed, getJobFeed };