const Job = require("../models/job");

function buildFilters(swipedJobIds, candidate) {
  const query = {
    isActive: true,
  };

  if (swipedJobIds.length > 0) {
    query._id = { $nin: swipedJobIds };
  }

  // Experience filter
  if (candidate.experience !== undefined) {
    query.minExperience = { $lte: candidate.experience };
  }

  return query;
}

async function fetchCandidates(swipedJobIds, candidate) {
  const filters = buildFilters(swipedJobIds, candidate);

  const jobs = await Job.find(filters)
    .sort({ createdAt: -1 })
    .limit(200)
    .lean();

  console.log("📦 Candidates fetched:", jobs.length);

  return jobs;
}

module.exports = {
  fetchCandidates,
};