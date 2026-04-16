const axios = require("axios");
const Job = require("../models/job");

const fetchLeverJobs = async (company) => {
  const url = `https://api.lever.co/v0/postings/${company}`;
  const response = await axios.get(url);
  return response.data;
};

const processLeverJobs = async (company) => {
  console.log(`📦 Fetching Lever jobs for: ${company}`);

  const jobs = await fetchLeverJobs(company);

  console.log("TOTAL LEVER JOBS:", jobs.length);

  const BATCH_SIZE = 50;

  for (let i = 0; i < jobs.length; i += BATCH_SIZE) {
    const batch = jobs.slice(i, i + BATCH_SIZE);

    console.log(`Processing Lever batch ${i / BATCH_SIZE + 1}`);

    await Promise.all(
      batch.map(job =>
        Job.updateOne(
          { externalId: String(job.id) },
          {
            $set: {
              title: job.text,
              company: company,
              source: "lever",
              location: job.categories?.location || "N/A",
              applyUrl: job.hostedUrl,
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

  console.log(`✅ Lever jobs stored for ${company}`);
};

module.exports = { processLeverJobs };