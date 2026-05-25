const express = require("express");
const router = express.Router();
const Task = require("../models/Task");
const Job = require("../models/Job");
const { getFeed } = require("../services/feedService");
const rateLimiter =
  require("../middleware/rateLimiter");

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

    // Enqueue via BullMQ and persist a Task record for observability
    const taskQueueService = require("../src/services/taskQueueService");

    const jobMeta = await taskQueueService.enqueueTask("SYNC_GREENHOUSE", { company });

    const task = await Task.create({
      type: "SYNC_GREENHOUSE",
      status: "pending",
      attempts: 0,
      payload: { company },
      jobId: String(jobMeta.id)
    });

    res.json({
      message: "Job sync started",
      jobId: jobMeta.id,
      taskId: task._id,
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Something went wrong" });
  }
});

router.get("/", rateLimiter, async (req, res) => {
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