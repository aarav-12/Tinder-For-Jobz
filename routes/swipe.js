const express = require("express");
const router = express.Router();

const { swipeJob } = require("../controllers/swipeController");

router.post("/", swipeJob);

module.exports = router;