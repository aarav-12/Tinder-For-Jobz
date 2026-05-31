const express = require("express");
const router = express.Router();

const authMiddleware = require("../middleware/authMiddleware");
const { swipeJob, getSwipeHistory, undoSwipe, getSavedJobs, getJobSwipeState } = require("../controllers/swipeController");
const rateLimiter =
	require("../middleware/rateLimiter");

router.post("/", rateLimiter, swipeJob);
router.get("/", authMiddleware, getSwipeHistory);
router.get("/saved", authMiddleware, getSavedJobs);
router.get("/:jobId", authMiddleware, getJobSwipeState);
router.delete("/:jobId", authMiddleware, undoSwipe);

module.exports = router;