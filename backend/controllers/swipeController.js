const Swipe = require("../models/Swipe");
const { redisClient } = require("../config/redisClient");
const { recordBehavior } = require("../services/behaviorService");

const swipeJob = async (req, res) => {
  try {
    const { candidateId, jobId, action } = req.body;

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

    res.json({
      success: true,
      swipe
    });

  } catch (err) {
    console.error("Swipe error:", err.message);
    res.status(500).json({ error: "Internal server error" });
  }
};

module.exports = { swipeJob };