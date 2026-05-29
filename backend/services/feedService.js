const mongoose = require("mongoose");
const User = require("../models/User");

const candidateService = require("./candidateService");
const rankingService = require("./rankingService");
const { getUserSwipes } = require("./swipeService");
const { buildPreferenceProfile } = require("./preferenceService");
const { redisClient } = require("../config/redisClient");

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

  try {
    await redisClient.hincrby("analytics:feed_opened", "count", 1);
  } catch (err) {
    console.error("Analytics update failed:", err.message);
  }

  const user = await getUser(candidateId);
  // Previous cache key/read logic kept for reference:
  // const cacheKey = `feed:${user._id}`;
  // console.log(`🔎 Feed cache lookup: ${cacheKey}`);
  //
  // try {
  //   const cachedFeed = await redisClient.get(cacheKey);
  //   if (cachedFeed) {
  //     console.log("⚡ Cache HIT");
  //     return JSON.parse(cachedFeed);
  //   }
  //
  //   console.log("🟡 Cache MISS");
  // } catch (err) {
  //   console.error("Redis read failed:", err);
  // }

  const userId = user._id.toString();
  const cursorKey = cursor || "first";
  const cacheKey = `feed:${userId}:${cursorKey}`;

  let cachedFeed = null;

  try {
    cachedFeed = await redisClient.get(cacheKey);
  } catch (err) {
    console.error("Redis read failed:", err);
  }

  if (cachedFeed) {
    console.log(`⚡ Cache HIT: ${cacheKey}`);
    return JSON.parse(cachedFeed);
  }

  console.log(`❌ Cache MISS: ${cacheKey}`);

  const swipeKey = `swipes:${user._id.toString()}`;

  let sessionSwipes = {
    liked: [],
    disliked: []
  };

  try {
    const cached = await redisClient.get(swipeKey);

    if (cached) {
      sessionSwipes = JSON.parse(cached);
      console.log("⚡ Using session swipes:", swipeKey);
    }
  } catch (err) {
    console.error("❌ Failed to read session swipes:", err);
  }

  if (!Array.isArray(sessionSwipes.liked)) {
    sessionSwipes.liked = [];
  }

  if (!Array.isArray(sessionSwipes.disliked)) {
    sessionSwipes.disliked = [];
  }

  const swipes = await getUserSwipes(candidateId);
  const preferences = buildPreferenceProfile(swipes);
  sessionSwipes.liked.forEach((id) => preferences.liked.add(id.toString()));
  sessionSwipes.disliked.forEach((id) => preferences.disliked.add(id.toString()));
  const swipedJobIds = swipes
    .map((s) => toObjectId(s.jobId))
    .filter(Boolean);

  const candidateJobs = await candidateService.getCandidates({
    user,
    swipes: swipedJobIds,
    cursor,
  });

  const rankedJobs = await rankingService.rankJobs(
    user,
    candidateJobs,
    preferences
  );

  const jobs = rankedJobs.slice(0, 20);
  const nextCursor = jobs.length
    ? jobs[jobs.length - 1].createdAt
    : null;

  const response = {
    jobs,
    nextCursor,
  };

  // Previous cache write logic kept for reference:
  // try {
  //   await redisClient.setEx(cacheKey, 60, JSON.stringify(response));
  //   console.log("💾 Cache SET", cacheKey);
  // } catch (err) {
  //   console.error("Redis write failed:", err);
  // }

  const FEED_TTL = 120; // 2 minutes

  try {
    await redisClient.setEx(
      cacheKey,
      FEED_TTL,
      JSON.stringify(response)
    );
    console.log(`🧠 Cache SET: ${cacheKey}`);
  } catch (err) {
    console.error("Redis write failed:", err);
  }

  return response;
};

module.exports = { getFeed, getJobFeed };