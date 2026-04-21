require("dotenv").config();

const express = require("express");
const cors = require("cors");

const userRoutes = require("./routes/userRoutes");
const authRoutes = require("./routes/authRoutes");
const jobRoutes = require("./routes/jobRoutes");
const connectDB = require("./config/db");

const Task = require("./models/Task");

const app = express();

const AUTO_SYNC_COMPANIES = ["stripe", "notion", "airbnb"];

// MIDDLEWARE
app.use(cors());
app.use(express.json());

// Handle bad JSON (your earlier error)
app.use((err, req, res, next) => {
  if (err instanceof SyntaxError && err.status === 400 && "body" in err) {
    return res.status(400).json({ error: "Invalid JSON" });
  }
  next();
});

// ROUTES
app.use("/api/jobs", jobRoutes);   // → GET /api/jobs
app.use("/users", userRoutes);
app.use("/auth", authRoutes);

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

    const task = await Task.create({
      type: "SYNC_GREENHOUSE",
      status: "pending",
      attempts: 0,
      payload: { company }
    });

    res.json({
      message: "Task created",
      task
    });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// AUTO SYNC (EVERY 1 HOUR)
async function enqueueAutoSyncTasks() {
  console.log("⏰ Auto-triggering job sync...");

  for (const company of AUTO_SYNC_COMPANIES) {
    const existing = await Task.findOne({
      type: "SYNC_GREENHOUSE",
      "payload.company": company,
      status: { $in: ["pending", "running"] }
    });

    if (existing) {
      console.log(`⏭️ Skipping ${company}, task already in progress`);
      continue;
    }

    await Task.create({
      type: "SYNC_GREENHOUSE",
      status: "pending",
      attempts: 0,
      payload: { company }
    });

    console.log(`✅ Queued auto sync for ${company}`);
  }
}

setInterval(enqueueAutoSyncTasks, 1000 * 60 * 60);

async function startServer() {
  await connectDB();

  app.listen(5000, () => {
    console.log("Server running on port 5000");
  });
}

startServer().catch(err => {
  console.error("Failed to start server:", err);
  process.exit(1);
});