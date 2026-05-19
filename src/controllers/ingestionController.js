const ingestionService = require("../services/ingestionService");

const bulkUploadJobs = async (req, res) => {
  try {
    const { jobs, uploadedBy } = req.body;

    const jobId = await ingestionService.enqueueJobIngestion(
      jobs,
      uploadedBy
    );

    return res.status(202).json({
      success: true,
      message: "Job ingestion queued",
      jobId
    });
  } catch (error) {
    console.error("Ingestion error:", error);

    return res.status(500).json({
      success: false,
      message: "Failed to queue ingestion"
    });
  }
};

module.exports = {
  bulkUploadJobs
};