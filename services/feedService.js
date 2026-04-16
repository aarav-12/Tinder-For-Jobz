const mongoose = require("mongoose");
const User = require("../models/User");
const Swipe = require("../models/Swipe");

const { fetchCandidates } = require("./candidateService");
const { rankJobs } = require("./rankingService");

function toObjectId(value) {
  if (value instanceof mongoose.Types.ObjectId) return value;

  if (typeof value === "string" && mongoose.Types.ObjectId.isValid(value)) {
    return new mongoose.Types.ObjectId(value);
  }

  return null;
}

async function getJobFeed(candidateId) {
  if (mongoose.connection.readyState === 0) {
    throw new Error("Database is not connected");
  }

  const candidateObjectId = toObjectId(candidateId);
  if (!candidateObjectId) {
    throw new Error("Invalid candidate user ID");
  }

  // 1. Candidate
  const candidate = await User.findById(candidateObjectId).lean();
  if (!candidate) {
    throw new Error("Candidate not found");
  }

  // 2. Swipes
  const swipes = await Swipe.find({ userId: candidateObjectId })
    .select("jobId")
    .lean();

  const swipedJobIds = swipes
    .map((s) => toObjectId(s.jobId))
    .filter(Boolean);

  // 3. Candidate Pool
  const candidates = await fetchCandidates(swipedJobIds, candidate);

  // 4. Ranking
  const rankedJobs = rankJobs(candidates, candidate);

  // 5. Return top 20
  return rankedJobs.slice(0, 20);
}

module.exports = { getJobFeed };