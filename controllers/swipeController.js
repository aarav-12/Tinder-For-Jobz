const Swipe = require("../models/Swipe");

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