const multer = require("multer");
const ragService = require("../services/ragService");

const upload = multer({ storage: multer.memoryStorage() });

const health = async (req, res) => {
  try {
    const result = await ragService.getHealth();
    return res.json({ success: true, ...result });
  } catch (error) {
    return res.status(502).json({
      success: false,
      error: error.message,
    });
  }
};

const analyze = [
  upload.single("file"),
  async (req, res) => {
    try {
      if (!req.file) {
        return res.status(400).json({ error: "file is required" });
      }

      const result = await ragService.analyzeResume({
        fileBuffer: req.file.buffer,
        filename: req.file.originalname,
        contentType: req.file.mimetype,
        userId: req.body.user_id || req.body.userId || "",
      });

      return res.json(result);
    } catch (error) {
      const statusCode = error.response?.status || 502;
      return res.status(statusCode).json(
        error.response?.data || {
          error: error.message,
        }
      );
    }
  },
];

const retrieve = async (req, res) => {
  try {
    const { query, top_k, filters } = req.body;

    if (!query || typeof query !== "string") {
      return res.status(400).json({ error: "query is required" });
    }

    const result = await ragService.retrieveJobs({ query, top_k, filters });
    return res.json(result);
  } catch (error) {
    const statusCode = error.response?.status || 502;
    return res.status(statusCode).json(
      error.response?.data || {
        error: error.message,
      }
    );
  }
};

const embedJob = async (req, res) => {
  try {
    const result = await ragService.embedJob(req.body);
    return res.json(result);
  } catch (error) {
    const statusCode = error.response?.status || 502;
    return res.status(statusCode).json(
      error.response?.data || {
        error: error.message,
      }
    );
  }
};

module.exports = {
  health,
  analyze,
  retrieve,
  embedJob,
};