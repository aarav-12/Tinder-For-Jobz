const axios = require("axios");
const Job = require("../models/Job");

// cleanup function (move it here from worker)
async function cleanupOldJobs() {
  await Job.updateMany(
    {
      lastFetchedAt: {
        $lt: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
      }
    },
    {
      $set: { isActive: false }
    }
  );

  console.log("🧹 Old jobs marked inactive");
}

// main greenhouse processing function
const processGreenhouseJobs = async (company) => {
  try {
    console.log(`📦 Fetching Greenhouse jobs for: ${company}`);

    const url = `https://boards-api.greenhouse.io/v1/boards/${company}/jobs`;
    const response = await axios.get(url);

    const jobs = response.data.jobs;

    console.log("TOTAL GREENHOUSE JOBS:", jobs.length);

    const BATCH_SIZE = 50;

    for (let i = 0; i < jobs.length; i += BATCH_SIZE) {
      const batch = jobs.slice(i, i + BATCH_SIZE);

      console.log(`Processing Greenhouse batch ${i / BATCH_SIZE + 1}`);

      await Promise.all(
        batch.map(job =>
          Job.updateOne(
            { externalId: String(job.id) },
            {
              $set: {
                title: job.title,
                company: company,
                source: "greenhouse",
                location: job.location?.name || "N/A",
                applyUrl: job.absolute_url,
                isActive: true,
                lastFetchedAt: new Date(),
                updatedAt: new Date()
              },
              $setOnInsert: {
                createdAt: new Date()
              }
            },
            { upsert: true }
          )
        )
      );
    }

    await cleanupOldJobs();

    console.log(`✅ Greenhouse jobs stored for ${company}`);

  } catch (err) {
    if (err.response && err.response.status === 404) {
      console.log(`⚠️ ${company} is NOT on Greenhouse → skipping`);
      return; // do NOT retry
    }

    console.error("❌ Error in Greenhouse:", err.message);
    throw err;
  }
};

module.exports = { processGreenhouseJobs };