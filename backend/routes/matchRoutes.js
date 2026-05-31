const express = require("express");

const authMiddleware = require("../middleware/authMiddleware");
const { getMatches } = require("../controllers/matchController");

const router = express.Router();

router.get("/", authMiddleware, getMatches);

module.exports = router;