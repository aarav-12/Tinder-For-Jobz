const Swipe = require("../models/Swipe");
const Job = require("../models/Job");
const { redisClient } = require("../config/redisClient");
const { recordBehavior } = require("../services/behaviorService");

function resolveCandidateId(req) {
  return req.user?.userId || req.body?.candidateId || req.query?.candidateId || null;
}

async function clearSwipeCaches(candidateId) {
  const userId = candidateId.toString();
  const pattern = `feed:${userId}:*`;

  try {
    const keys = await redisClient.keys(pattern);

    if (keys.length > 0) {
      await redisClient.del(keys);
      console.log(`🧹 Cache cleared for user: ${userId}`);
    }
  } catch (err) {
    console.error("Cache invalidation failed:", err);
  }
}

const swipeJob = async (req, res) => {
  try {
    const candidateId = resolveCandidateId(req);
    const { jobId, action } = req.body;

    // 🔒 Validation (don’t trust frontend)
    if (!candidateId || !jobId || !action) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    if (!["like", "dislike"].includes(action)) {
      return res.status(400).json({ error: "Invalid action" });
    }

    // 🔥 Core logic: upsert swipe
    const swipe = await Swipe.findOneAndUpdate(
      { candidateId, jobId },
      { action },
      {
        upsert: true,   // create if not exists
        new: true,      // return updated doc
        setDefaultsOnInsert: true
      }
    );

      if (action === "like") {
        try {
          await recordBehavior({
            userId: candidateId,
            postId: jobId,
            action: "like",
            duration: 0,
          });
        } catch (error) {
          console.error("Behavior tracking failed for like:", error.message || error);
        }
      }

    const swipeKey = `swipes:${candidateId.toString()}`;

    let sessionSwipes = {
      liked: [],
      disliked: []
    };

    try {
      const existing = await redisClient.get(swipeKey);
      const normalizedJobId = jobId.toString();

      if (existing) {
        sessionSwipes = JSON.parse(existing);
      }

      if (!Array.isArray(sessionSwipes.liked)) {
        sessionSwipes.liked = [];
      }

      if (!Array.isArray(sessionSwipes.disliked)) {
        sessionSwipes.disliked = [];
      }

      if (action === "like") {
        if (!sessionSwipes.liked.some((id) => id.toString() === normalizedJobId)) {
          sessionSwipes.liked.push(normalizedJobId);
        }
      } else {
        if (!sessionSwipes.disliked.some((id) => id.toString() === normalizedJobId)) {
          sessionSwipes.disliked.push(normalizedJobId);
        }
      }

      await redisClient.setEx(
        swipeKey,
        300, // 5 minutes
        JSON.stringify(sessionSwipes)
      );

      console.log("⚡ Swipe cached in session:", swipeKey);

    } catch (err) {
      console.error("❌ Swipe session cache failed:", err);
    }

    // Previous invalidation approach kept for reference:
    // await redisClient.del(`feed:${candidateId}`);

    await clearSwipeCaches(candidateId);

    res.json({
      success: true,
      swipe
    });

  } catch (err) {
    console.error("Swipe error:", err.message);
    res.status(500).json({ error: "Internal server error" });
  }
};

const getSwipeHistory = async (req, res) => {
  try {
    const candidateId = resolveCandidateId(req);

    if (!candidateId) {
      return res.status(400).json({ error: "candidateId is required" });
    }

    const swipes = await Swipe.find({ candidateId })
      .sort({ createdAt: -1 })
      .populate("jobId")
      .lean();

    res.json({ swipes });
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to load swipe history" });
  }
};

const undoSwipe = async (req, res) => {
  try {
    const candidateId = resolveCandidateId(req);
    const { jobId } = req.params;

    if (!candidateId || !jobId) {
      return res.status(400).json({ error: "candidateId and jobId are required" });
    }

    const swipe = await Swipe.findOneAndDelete({ candidateId, jobId });

    if (!swipe) {
      return res.status(404).json({ error: "Swipe not found" });
    }

    await clearSwipeCaches(candidateId);

    res.json({ success: true, swipe });
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to undo swipe" });
  }
};

const getSavedJobs = async (req, res) => {
  try {
    const candidateId = resolveCandidateId(req);

    if (!candidateId) {
      return res.status(400).json({ error: "candidateId is required" });
    }

    const likedSwipes = await Swipe.find({ candidateId, action: "like" })
      .sort({ createdAt: -1 })
      .populate("jobId")
      .lean();

    const jobs = likedSwipes
      .map((swipe) => swipe.jobId)
      .filter(Boolean);

    res.json({ jobs, swipes: likedSwipes });
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to load saved jobs" });
  }
};

const getJobSwipeState = async (req, res) => {
  try {
    const candidateId = resolveCandidateId(req);
    const { jobId } = req.params;

    if (!candidateId || !jobId) {
      return res.status(400).json({ error: "candidateId and jobId are required" });
    }

    const swipe = await Swipe.findOne({ candidateId, jobId }).lean();
    const job = await Job.findById(jobId).lean();

    res.json({ swipe, job });
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to load swipe state" });
  }
};

module.exports = { swipeJob, getSwipeHistory, undoSwipe, getSavedJobs, getJobSwipeState };