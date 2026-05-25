const express = require("express");

const router = express.Router();
const ingestionController = require("../controllers/ingestionController");

// POST /api/jobs/bulk
// Hit this endpoint to queue a bulk job ingestion request.
router.post(
  "/bulk",
  ingestionController.bulkUploadJobs
);

module.exports = router;