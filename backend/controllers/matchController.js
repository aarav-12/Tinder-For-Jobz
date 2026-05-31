const Swipe = require("../models/Swipe");

const getMatches = async (req, res) => {
  try {
    const candidateId = req.user?.userId || req.query?.candidateId || req.body?.candidateId;

    if (!candidateId) {
      return res.status(400).json({ error: "candidateId is required" });
    }

    const likedSwipes = await Swipe.find({ candidateId, action: "like" })
      .sort({ createdAt: -1 })
      .populate("jobId")
      .lean();

    const matches = likedSwipes.map((swipe) => ({
      _id: swipe._id,
      candidateId: swipe.candidateId,
      jobId: swipe.jobId?._id || swipe.jobId,
      action: swipe.action,
      createdAt: swipe.createdAt,
      updatedAt: swipe.updatedAt,
      job: swipe.jobId || null,
    }));

    res.json({ matches });
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to load matches" });
  }
};

module.exports = { getMatches };