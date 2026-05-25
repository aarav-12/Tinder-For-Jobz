const express = require("express");
const ragController = require("../controllers/ragController");

const router = express.Router();

router.get("/health", ragController.health);
router.post("/analyze", ...ragController.analyze);
router.post("/retrieve", express.json(), ragController.retrieve);
router.post("/embed-job", express.json(), ragController.embedJob);

module.exports = router;