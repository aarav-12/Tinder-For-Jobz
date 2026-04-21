const express = require("express");
const router = express.Router();
const Task = require("../models/Task");
const Job = require("../models/Job");
const { getFeed } = require("../services/feedService");

// Create a sync job task
router.post("/sync-jobs", async (req, res) => {
  try {
    if (!req.body || typeof req.body !== "object") {
      return res.status(400).json({ error: "Request body must be valid JSON" });
    }

    const { company } = req.body;

    if (!company || typeof company !== "string") {
      return res.status(400).json({ error: "'company' is required and must be a string" });
    }

    const existing = await Task.findOne({
      type: "SYNC_GREENHOUSE",
      "payload.company": company,
      status: { $in: ["pending", "running"] },
    });

    if (existing) {
      return res.json({ message: "Task already in progress" });
    }

    const task = await Task.create({
      type: "SYNC_GREENHOUSE",
      payload: { company },
    });

    res.json({
      message: "Job sync started",
      taskId: task._id,
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Something went wrong" });
  }
});

router.get("/", async (req, res) => {
  console.log("🔥 /api/jobs HIT");

  try {
    const { candidateId, cursor } = req.query;

    const result = await getFeed(candidateId, cursor);

    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;