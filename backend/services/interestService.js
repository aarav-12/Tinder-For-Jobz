const UserInterest = require("../models/UserInterest");
const { redisClient } = require("../config/redisClient");

const INTEREST_CACHE_TTL_SECONDS = 300;

function getInterestCacheKey(userId) {
  return `user:${userId}:interests`;
}

async function readCachedInterests(userId) {
  try {
    const cached = await redisClient.get(getInterestCacheKey(userId));
    if (!cached) {
      return null;
    }

    return JSON.parse(cached);
  } catch (error) {
    console.error("Failed to read cached interests:", error.message || error);
    return null;
  }
}

async function writeCachedInterests(userId, interests) {
  try {
    await redisClient.setEx(
      getInterestCacheKey(userId),
      INTEREST_CACHE_TTL_SECONDS,
      JSON.stringify(interests)
    );
  } catch (error) {
    console.error("Failed to cache interests:", error.message || error);
  }
}

async function clearCachedInterests(userId) {
  try {
    await redisClient.del(getInterestCacheKey(userId));
  } catch (error) {
    console.error("Failed to clear cached interests:", error.message || error);
  }
}

async function getUserInterests(userId) {
  const cached = await readCachedInterests(userId);

  if (cached) {
    return cached;
  }

  const rows = await UserInterest.find({ userId }).lean();
  const interests = rows.reduce((accumulator, row) => {
    accumulator[row.category] = row.score;
    return accumulator;
  }, {});

  await writeCachedInterests(userId, interests);

  return interests;
}

async function getUserInterestEntries(userId) {
  return UserInterest.find({ userId }).sort({ score: -1 }).lean();
}

async function upsertUserInterest({ userId, category, delta }) {
  const interest = await UserInterest.findOneAndUpdate(
    { userId, category },
    { $inc: { score: delta } },
    { upsert: true, new: true, setDefaultsOnInsert: true }
  );

  const current = await getUserInterests(userId);
  current[category] = interest.score;
  await writeCachedInterests(userId, current);

  return interest;
}

module.exports = {
  clearCachedInterests,
  getInterestCacheKey,
  getUserInterestEntries,
  getUserInterests,
  upsertUserInterest,
  writeCachedInterests,
};