const multer = require("multer");
const mongoose = require("mongoose");

const Job = require("../../models/Job");
const User = require("../../models/User");
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

      const userId = req.body.user_id || req.body.userId || "";
      if (userId && result && !result.error) {
        await User.findByIdAndUpdate(
          userId,
          {
            $set: {
              resume: {
                filename: req.file.originalname,
                contentType: req.file.mimetype,
                analyzedAt: new Date(),
                analysis: result,
              },
              skills: Array.isArray(result.canonical_skills) ? result.canonical_skills : undefined,
            },
          },
          { new: true }
        );
      }

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

    const matches = Array.isArray(result?.matches) ? result.matches : [];
    if (!matches.length) {
      return res.json(result);
    }

    const matchIds = matches
      .map((match) => {
        const candidateId = match?.job_id || match?.metadata?.job_id;
        return typeof candidateId === "string" ? candidateId : null;
      })
      .filter(Boolean);

    const objectIds = matchIds
      .filter((id) => mongoose.Types.ObjectId.isValid(id))
      .map((id) => new mongoose.Types.ObjectId(id));

    const jobs = await Job.find({
      $or: [
        { _id: { $in: objectIds } },
        { externalId: { $in: matchIds } },
      ],
    }).lean();

    const jobByMongoId = new Map(jobs.map((job) => [String(job._id), job]));
    const jobByExternalId = new Map(
      jobs
        .filter((job) => typeof job.externalId === "string")
        .map((job) => [job.externalId, job])
    );

    const hydratedMatches = matches.map((match) => {
      const candidateId = match?.job_id || match?.metadata?.job_id;
      const job = jobByMongoId.get(String(candidateId)) || jobByExternalId.get(String(candidateId)) || null;

      return {
        ...match,
        job,
      };
    });

    return res.json({
      ...result,
      matches: hydratedMatches,
    });
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

const scoreJobQuality = async (req, res) => {
  try {
    const result = await ragService.scoreJobQuality(req.body);
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

const explainMatch = async (req, res) => {
  try {
    const result = await ragService.explainMatch(req.body);
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

const retrievalStats = async (_req, res) => {
  try {
    const result = await ragService.getRetrievalStats();
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

const clearRetrievalCache = async (_req, res) => {
  try {
    const result = await ragService.clearRetrievalCache();
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
  scoreJobQuality,
  explainMatch,
  retrievalStats,
  clearRetrievalCache,
};