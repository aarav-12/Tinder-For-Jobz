const { recordBehavior } = require("../services/behaviorService");

async function createBehavior(req, res) {
  try {
    const { userId, postId, action, duration } = req.body || {};
    const actorUserId = req.user?.userId || userId;

    if (!actorUserId || !postId || !action) {
      return res.status(400).json({ error: "userId, postId, and action are required" });
    }

    const behavior = await recordBehavior({
      userId: actorUserId,
      postId,
      action,
      duration,
    });

    res.status(201).json({ success: true, behavior });
  } catch (error) {
    res.status(400).json({ error: error.message || "Failed to record behavior" });
  }
}

module.exports = {
  createBehavior,
};