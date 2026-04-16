const express = require("express");
const router = express.Router();
const Task = require("../models/Task");
const Job = require("../models/job");
const { getJobFeed } = require("../services/feedService");

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

async function handleJobsFeed(req, res) {
  console.log("🔥 /api/jobs route hit");
  try {
    console.log("CandidateId:", req.query.candidateId);

    const candidateId = req.query.candidateId;

    if (!candidateId) {
      return res.status(400).json({
        error: "candidateId is required",
      });
    }

    const jobs = await getJobFeed(candidateId);

    res.json({
      success: true,
      count: jobs.length,
      data: jobs,
    });
  } catch (error) {
    console.error("Feed Error:", error.message);

    res.status(500).json({
      error: "Something went wrong",
    });
  }
}

router.get("/", handleJobsFeed);

module.exports = router;