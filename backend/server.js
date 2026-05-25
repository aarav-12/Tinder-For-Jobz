require("dotenv").config();

const express = require("express");
const cors = require("cors");

const userRoutes = require("./routes/userRoutes");
const authRoutes = require("./routes/authRoutes");
const jobRoutes = require("./routes/jobRoutes");
const ingestionRoutes = require("./src/routes/ingestionRoutes");
const connectDB = require("./config/db");
const { connectRedis } = require("./src/config/redisClient");

const Task = require("./models/Task");
const swipeRoutes = require("./routes/swipe");
const ingestionController = require("./src/controllers/ingestionController");


const app = express();

const AUTO_SYNC_COMPANIES = ["stripe", "notion", "airbnb"];
  
// MIDDLEWARE
app.use(cors());
app.use(express.json());

// Previous version kept for reference:
// app.get("/test-redis", async (req, res) => {
//   const { redisClient } = require("./config/redisClient");
//
//   await redisClient.set("testKey", "helloRedis");
//   const value = await redisClient.get("testKey");
//
//   res.json({ value });
// });

app.get("/test-redis", async (req, res) => {
  const { redisClient } = require("./src/config/redisClient");

  await redisClient.set("testKey", "helloRedis");
  const value = await redisClient.get("testKey");

  res.json({ value });
});

// Handle bad JSON (your earlier error)
app.use((err, req, res, next) => {
  if (err instanceof SyntaxError && err.status === 400 && "body" in err) {
    return res.status(400).json({ error: "Invalid JSON" });
  }
  next();
});

// ROUTES
app.use("/api/jobs", ingestionRoutes); // → POST /api/jobs/bulk
app.use("/api/jobs", jobRoutes);       // → GET /api/jobs
app.use("/api/swipe", swipeRoutes);
app.use("/users", userRoutes);
app.use("/auth", authRoutes);

// Explicit routes (fallback) to ensure endpoints are reachable
app.post("/api/jobs/bulk", ingestionController.bulkUploadJobs);

app.post('/api/jobs/sync-jobs', async (req, res) => {
  try {
    if (!req.body || typeof req.body !== 'object') {
      return res.status(400).json({ error: 'Request body must be valid JSON' });
    }

    const { company } = req.body;

    if (!company || typeof company !== 'string') {
      return res.status(400).json({ error: "'company' is required and must be a string" });
    }

    const existing = await Task.findOne({
      type: 'SYNC_GREENHOUSE',
      'payload.company': company,
      status: { $in: ['pending', 'running'] }
    });

    if (existing) {
      return res.json({ message: 'Task already in progress' });
    }

    const taskQueueService = require('./src/services/taskQueueService');
    const jobMeta = await taskQueueService.enqueueTask('SYNC_GREENHOUSE', { company });

    const task = await Task.create({
      type: 'SYNC_GREENHOUSE',
      status: 'pending',
      attempts: 0,
      payload: { company },
      jobId: String(jobMeta.id)
    });

    res.json({ message: 'Job sync started', jobId: jobMeta.id, taskId: task._id });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Something went wrong' });
  }
});

// Dump mounted routes for debugging
function listMountedRoutes() {
  try {
    if (!app._router || !Array.isArray(app._router.stack)) {
      console.log('No routes mounted yet');
      return;
    }

    const routes = [];
    app._router.stack.forEach((middleware) => {
      if (!middleware) return;

      if (middleware.route) {
        const methods = Object.keys(middleware.route.methods).join(',').toUpperCase();
        routes.push(`${methods} ${middleware.route.path}`);
      } else if (middleware.name === 'router' && middleware.handle && Array.isArray(middleware.handle.stack)) {
        middleware.handle.stack.forEach((handler) => {
          if (handler && handler.route) {
            const methods = Object.keys(handler.route.methods).join(',').toUpperCase();
            routes.push(`${methods} ${handler.route.path}`);
          }
        });
      }
    });

    console.log('Mounted routes:\n', routes.join('\n'));
  } catch (err) {
    console.error('Failed to list routes:', err && err.message ? err.message : err);
  }
}

listMountedRoutes();

// TEST ROUTES
app.get("/test", (req, res) => {
  console.log("TEST ROUTE HIT");
  res.send("Server is working");
});

app.get("/", (req, res) => {
  res.send("API is running");
});

// TASK CREATION (MANUAL TRIGGER)
app.post("/api/tasks/sync-jobs", async (req, res) => {
  try {
    const { company } = req.body;

      const existing = await Task.findOne({
        type: "SYNC_GREENHOUSE",
        "payload.company": company,
        status: { $in: ["pending", "running"] }
      });

      if (existing) {
        return res.json({ message: "Task already in progress" });
      }

      const taskQueueService = require("./src/services/taskQueueService");

      const jobMeta = await taskQueueService.enqueueTask("SYNC_GREENHOUSE", { company });

      const task = await Task.create({
        type: "SYNC_GREENHOUSE",
        status: "pending",
        attempts: 0,
        payload: { company },
        jobId: String(jobMeta.id)
      });

      res.json({
        message: "Task created",
        jobId: jobMeta.id,
        task
      });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// AUTO SYNC (EVERY 1 HOUR)
async function enqueueAutoSyncTasks() {
  console.log("⏰ Auto-triggering job sync...");

  const taskQueueService = require("./src/services/taskQueueService");

  for (const company of AUTO_SYNC_COMPANIES) {
    try {
      const existing = await Task.findOne({
        type: "SYNC_GREENHOUSE",
        "payload.company": company,
        status: { $in: ["pending", "running"] }
      });

      if (existing) {
        console.log(`⏭️ Skipping ${company}, task already in progress`);
        continue;
      }

      const jobMeta = await taskQueueService.enqueueTask("SYNC_GREENHOUSE", { company });

      await Task.create({
        type: "SYNC_GREENHOUSE",
        status: "pending",
        attempts: 0,
        payload: { company },
        jobId: String(jobMeta.id)
      });

      console.log(`✅ Queued auto sync for ${company} (job ${jobMeta.id})`);
    } catch (err) {
      console.error(`❌ Auto sync failed for ${company}:`, err.message);
    }
  }
}

setInterval(() => {
  enqueueAutoSyncTasks().catch((err) => {
    console.error("❌ Auto sync loop failed:", err.message);
  });
}, 1000 * 60 * 60);

async function startServer() {
  await connectDB();
  await connectRedis();

  const port = process.env.PORT || 5000;

  app.listen(port, () => {
    console.log(`🚀 Server running on port ${port}`);
  });
}

startServer().catch(err => {
  console.error("Failed to start server:", err);
  process.exit(1);
});