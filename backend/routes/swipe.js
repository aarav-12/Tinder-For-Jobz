const express = require("express");
const router = express.Router();

const { swipeJob } = require("../controllers/swipeController");
const rateLimiter =
	require("../middleware/rateLimiter");

router.post("/", rateLimiter, swipeJob);

module.exports = router;