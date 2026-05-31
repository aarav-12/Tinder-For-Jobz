const express = require("express");
const ragController = require("../controllers/ragController");

const router = express.Router();

router.get("/health", ragController.health);
router.post("/analyze", ...ragController.analyze);
router.post("/retrieve", express.json(), ragController.retrieve);
router.post("/embed-job", express.json(), ragController.embedJob);
router.post("/score-job-quality", express.json(), ragController.scoreJobQuality);
router.post("/explain-match", express.json(), ragController.explainMatch);
router.get("/debug/retrieval-stats", ragController.retrievalStats);
router.post("/debug/clear-cache", ragController.clearRetrievalCache);

module.exports = router;