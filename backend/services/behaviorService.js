const Behavior = require("../models/Behavior");
const Job = require("../models/Job");
const { redisClient } = require("../config/redisClient");
const behaviorWeights = require("../config/behaviorWeights");
const { deriveJobCategory } = require("../utils/jobCategory");
const {
  upsertUserInterest,
} = require("./interestService");

const ALLOWED_ACTIONS = ["view", "like", "save", "apply", "share", "comment"];

function normalizeDuration(duration) {
  const parsed = Number(duration || 0);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }

  return parsed;
}

function getBehaviorWeight(action, duration) {
  if (action === "view") {
    const durationBoost = Math.min(5, Math.max(0, normalizeDuration(duration) / 15));
    return behaviorWeights.view + durationBoost;
  }

  return behaviorWeights[action] || 0;
}

async function clearUserFeedCache(userId) {
  try {
    const keys = await redisClient.keys(`feed:${userId}:*`);
    if (keys.length > 0) {
      await redisClient.del(keys);
    }
  } catch (error) {
    console.error("Failed to clear feed cache:", error.message || error);
  }
}

async function recordBehavior({ userId, postId, action, duration }) {
  if (!userId || !postId || !action) {
    throw new Error("userId, postId, and action are required");
  }

  if (!ALLOWED_ACTIONS.includes(action)) {
    throw new Error("Invalid action");
  }

  const normalizedDuration = normalizeDuration(duration);
  const behavior = await Behavior.create({
    userId,
    postId,
    action,
    duration: normalizedDuration,
  });

  const weight = getBehaviorWeight(action, normalizedDuration);
  const job = await Job.findById(postId).lean();

  if (job) {
    const category = deriveJobCategory(job);

    if (category) {
      await upsertUserInterest({
        userId,
        category,
        delta: weight,
      });
    }
  }

  await clearUserFeedCache(userId);

  try {
    await redisClient.hincrby("analytics:behavior:counts", action, 1);

    if (action === "view") {
      await redisClient.hincrbyfloat("analytics:behavior:view_duration_total", "value", normalizedDuration);
      await redisClient.hincrby("analytics:behavior:view_duration_total", "count", 1);
      await redisClient.hincrby("analytics:feed_opened", "count", 1);
    }
  } catch (error) {
    console.error("Failed to update analytics:", error.message || error);
  }

  return behavior;
}

module.exports = {
  ALLOWED_ACTIONS,
  getBehaviorWeight,
  recordBehavior,
};