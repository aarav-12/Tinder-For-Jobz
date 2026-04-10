const express = require("express");
const router = express.Router();
const Task = require("../models/Task");

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

    const task = await Task.create({
      type: "SYNC_JOBS",
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

module.exports = router;