const { redisClient } = require("../config/redisClient");

async function getBehaviorAnalytics(req, res) {
  try {
    const counts = await redisClient.hgetall("analytics:behavior:counts");
    const viewDuration = await redisClient.hgetall("analytics:behavior:view_duration_total");
    const feedOpened = await redisClient.hgetall("analytics:feed_opened");

    const totalViews = Number(viewDuration.count || 0);
    const averageViewDuration = totalViews > 0
      ? Number((Number(viewDuration.value || 0) / totalViews).toFixed(2))
      : 0;

    res.json({
      counts,
      feedOpened: Number(feedOpened.count || 0),
      averageViewDuration,
    });
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to load analytics" });
  }
}

module.exports = {
  getBehaviorAnalytics,
};